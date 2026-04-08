#!/usr/bin/env python3
"""TradingView 로그인/인증 샘플 테스트"""

import os
import logging

from tvDatafeed import TvDatafeed, Interval
from tvDatafeed.auth import load_tv_auth_data, save_tv_auth_data

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "tradingview.json")


def main():
    print(f"=== config: {CONFIG_PATH}")

    # 1. auth 데이터 로드
    print("\n[1] auth 데이터 로드")
    auth = load_tv_auth_data(CONFIG_PATH)
    if auth is None:
        print("ERROR: auth 데이터 로드 실패")
        return
    print(f"  loaded: {auth}")

    # 2. TvDatafeed 초기화 (로그인/토큰 발급)
    print("\n[2] TvDatafeed 초기화")
    tv = TvDatafeed(auth=auth)

    if tv.token == "unauthorized_user_token":
        errmsg = tv.get_errmsg()
        print(f"  FAIL: 인증 실패 - {errmsg}")
        return

    print(f"  SUCCESS: token = {tv.token[:40]}...")
    print(f"  auth: {tv.auth}")

    # 3. 간단한 데이터 조회 테스트
    print("\n[3] 데이터 조회 테스트 (AAPL, NASDAQ, 1D, 3bars)")
    try:
        df = tv.get_hist(
            symbol="AAPL",
            exchange="NASDAQ",
            interval=Interval.in_daily,
            n_bars=3,
        )
        if df is not None:
            print(f"  SUCCESS: {len(df)} bars")
            print(df.to_string())
        else:
            print("  FAIL: 데이터 없음")
    except Exception as e:
        print(f"  ERROR: {e}")

    # 4. auth 데이터 저장
    print(f"\n[4] auth 데이터 저장: {CONFIG_PATH}")
    if tv.auth:
        ok = save_tv_auth_data(tv.auth, CONFIG_PATH)
        print(f"  {'SUCCESS' if ok else 'FAIL'}")
    else:
        print("  SKIP: tv.auth 없음")


if __name__ == "__main__":
    main()
