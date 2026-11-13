import os
import sys
import json
import base64
import io
from datetime import datetime as dt, timedelta
import requests
import pandas as pd

# 환경변수에서 API 키 로드 (GitHub Secrets 설정 연동)
DART_API_KEY = os.environ.get("DART_API_KEY", "")
KRX_OPENAPI_KEY = os.environ.get("KRX_OPENAPI_KEY", "")
KIS_APP_KEY = os.environ.get("KIS_APP_KEY", "")
KIS_APP_SECRET = os.environ.get("KIS_APP_SECRET", "")

TODAY = dt.now().date()


def get_krx_spac_list():
    """
    한국거래소(KRX) 코스닥 공시 자료 소속부 'SPAC' 분류 전체 종목 조회
    (KIND 상장법인목록 크롤링 활용)
    """
    spacs = []
    try:
        url = "https://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13"
        res = requests.get(url, timeout=15)
        res.encoding = "euc-kr"
        dfs = pd.read_html(io.StringIO(res.text))
        df = dfs[0]

        # 종목명에 '스팩'이 포함된 코스닥 종목 추출
        spac_df = df[df["회사명"].str.contains("스팩", na=False)].copy()
        for _, row in spac_df.iterrows():
            code = str(row["종목코드"]).zfill(6)
            name = str(row["회사명"]).strip()
            listing_date = str(row["상장일"]).strip()
            spacs.append({
                "code": code,
                "name": name,
                "listing_date": listing_date
            })
    except Exception as e:
        print(f"[Warn] KRX 목록 조회 중 오류 발생: {e}")
    return spacs


def get_market_price_and_status(code):
    """
    네이버 증권/실시간 시세 연동을 통한 현재가, 거래정지, 합병승인/철회 상태 파악
    """
    current_price = 0
    is_suspended = False
    merger_status = "정상"

    try:
        url = f"https://polling.finance.naver.com/api/realtime?query=SERVICE_ITEM:{code}"
        res = requests.get(url, timeout=10).json()
        datas = res["result"]["areas"][0]["datas"][0]
        current_price = int(datas.get("nv", 0))
        if datas.get("ms") in ["STOP", "HALT"]:
            is_suspended = True
            merger_status = "거래정지"
    except Exception:
        pass

    return current_price, is_suspended, merger_status


def fetch_dart_spac_terms(corp_code, ipo_price=2000):
    """
    DART 공시자료 연동 및 스팩 조건 설정
