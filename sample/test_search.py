#!/usr/bin/env python3
"""search_symbol 테스트 스크립트

직접 requests 호출과 TvDatafeed.search_symbol() 비교 테스트.
403 등 응답 상태코드와 헤더를 확인할 수 있다.

Usage:
    # tvdatafeed 디렉토리에서
    python3 sample/test_search.py

    # tradingview_cron 디렉토리에서
    python3 tvdatafeed/sample/test_search.py

    # 특정 심볼만 테스트
    python3 sample/test_search.py AAPL NASDAQ
"""

import sys
import os
import json
import requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PACKAGE_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
sys.path.insert(0, PACKAGE_DIR)

from tvDatafeed import TvDatafeed
import tvDatafeed as _tvmod

SEARCH_URL = "https://symbol-search.tradingview.com/symbol_search/?text={}&hl=1&exchange={}&lang=en&type=&domain=production"


def test_raw(text, exchange=""):
    """헤더 없이 requests 직접 호출"""
    url = SEARCH_URL.format(text, exchange)
    print(f"\n[RAW] {text} / {exchange}")
    try:
        resp = requests.get(url, timeout=10)
        print(f"  status={resp.status_code}")
        if resp.status_code == 200:
            data = json.loads(resp.text.replace("</em>", "").replace("<em>", ""))
            print(f"  results={len(data)}")
            for item in data[:3]:
                print(f"    {item.get('symbol')} ({item.get('exchange')})")
        else:
            print(f"  body: {resp.text[:200]}")
    except Exception as e:
        print(f"  error: {e}")


def test_with_headers(text, exchange=""):
    """User-Agent 등 헤더 추가하여 호출"""
    url = SEARCH_URL.format(text, exchange)
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
        "Accept": "application/json",
    }
    print(f"\n[+Headers] {text} / {exchange}")
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        print(f"  status={resp.status_code}")
        if resp.status_code == 200:
            data = json.loads(resp.text.replace("</em>", "").replace("<em>", ""))
            print(f"  results={len(data)}")
            for item in data[:3]:
                print(f"    {item.get('symbol')} ({item.get('exchange')})")
        else:
            print(f"  body: {resp.text[:200]}")
    except Exception as e:
        print(f"  error: {e}")


def test_tvdatafeed(text, exchange=""):
    """TvDatafeed.search_symbol() 메서드 호출"""
    print(f"\n[TvDatafeed] {text} / {exchange}")
    tv = TvDatafeed()
    result = tv.search_symbol(text, exchange)
    print(f"  results={len(result)}")
    for item in result[:3]:
        print(f"    {item.get('symbol')} ({item.get('exchange')})")


def main():
    # 커맨드라인 인자로 심볼 지정 가능
    if len(sys.argv) >= 2:
        text = sys.argv[1]
        exchange = sys.argv[2] if len(sys.argv) >= 3 else ""
        cases = [(text, exchange)]
    else:
        cases = [
            ("AAPL", "NASDAQ"),
            ("NQ1!", "CME_MINI"),
            ("005930", "KRX"),
            ("TSLA", ""),
        ]

    print(f"tvDatafeed loaded from: {os.path.dirname(_tvmod.__file__)}")

    print("\n" + "=" * 50)
    print("1. Raw requests (no headers)")
    print("=" * 50)
    for text, ex in cases:
        test_raw(text, ex)

    print("\n" + "=" * 50)
    print("2. With browser headers")
    print("=" * 50)
    for text, ex in cases:
        test_with_headers(text, ex)

    print("\n" + "=" * 50)
    print("3. Via TvDatafeed.search_symbol()")
    print("=" * 50)
    for text, ex in cases:
        test_tvdatafeed(text, ex)


if __name__ == "__main__":
    main()
