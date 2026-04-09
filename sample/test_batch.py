#!/usr/bin/env python3
"""get_hist_batch 테스트 - 12개 요청 (3심볼 x 4타임프레임), batch_size=4"""

import os
import sys
import time
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tvDatafeed import TvDatafeed, Interval
from tvDatafeed.auth import load_tv_auth_data, save_tv_auth_data

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "conf", "tradingview.json")


def main():
    # auth
    auth = load_tv_auth_data(CONFIG_PATH)
    if auth is None:
        print("ERROR: auth 데이터 로드 실패")
        return
    tv = TvDatafeed(auth=auth)
    if tv.token == "unauthorized_user_token":
        print(f"FAIL: 인증 실패 - {tv.get_errmsg()}")
        return
    print(f"auth OK: token = {tv.token[:40]}...")

    # 12개 요청: 3심볼 x 4타임프레임
    requests = [
        {"symbol": "NQ1!", "exchange": "CME_MINI", "interval": Interval.in_5_minute, "count": 6},
        {"symbol": "NQ1!", "exchange": "CME_MINI", "interval": Interval.in_15_minute, "count": 6},
        {"symbol": "NQ1!", "exchange": "CME_MINI", "interval": Interval.in_1_hour, "count": 6},
        {"symbol": "NQ1!", "exchange": "CME_MINI", "interval": Interval.in_daily, "count": 6},
        {"symbol": "ES1!", "exchange": "CME_MINI", "interval": Interval.in_5_minute, "count": 6},
        {"symbol": "ES1!", "exchange": "CME_MINI", "interval": Interval.in_15_minute, "count": 6},
        {"symbol": "ES1!", "exchange": "CME_MINI", "interval": Interval.in_1_hour, "count": 6},
        {"symbol": "ES1!", "exchange": "CME_MINI", "interval": Interval.in_daily, "count": 6},
        {"symbol": "GC1!", "exchange": "COMEX", "interval": Interval.in_5_minute, "count": 6},
        {"symbol": "GC1!", "exchange": "COMEX", "interval": Interval.in_15_minute, "count": 6},
        {"symbol": "GC1!", "exchange": "COMEX", "interval": Interval.in_1_hour, "count": 6},
        {"symbol": "GC1!", "exchange": "COMEX", "interval": Interval.in_daily, "count": 6},
    ]

    print(f"\n=== get_hist_batch: {len(requests)} requests, batch_size=4 ===")
    start = time.time()
    results = tv.get_hist_batch(requests, batch_size=4)
    elapsed = time.time() - start

    if results is None:
        print("FATAL: get_hist_batch returned None")
        return

    print(f"\n=== 결과: {elapsed:.1f}초 소요 ===")
    success = 0
    fail = 0
    for r in results:
        symbol = r["symbol"]
        exchange = r["exchange"]
        interval = r["interval"]
        if r["data"] is not None:
            success += 1
            print(f"  OK  {symbol}:{exchange} {interval.value} - {len(r['data'])} bars")
            print(r["data"].to_string(max_rows=3))
            print()
        else:
            fail += 1
            print(f"  ERR {symbol}:{exchange} {interval.value} - {r['error']}")

    print(f"\n=== 요약: {success} 성공, {fail} 실패, {elapsed:.1f}초 ===")

    # auth 저장
    if tv.auth:
        save_tv_auth_data(tv.auth, CONFIG_PATH)


if __name__ == "__main__":
    main()
