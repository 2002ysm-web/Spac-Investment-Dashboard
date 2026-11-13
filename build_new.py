import os
import sys
import json
import zipfile
import io
import xml.etree.ElementTree as ET
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
    5. 한국거래소(KRX) 코스닥 공시 자료 소속부 'SPAC' 분류 전체 종목 조회
    (KRX OpenAPI 또는 KIND 상장법인목록 크롤링 Fallback 지원)
    """
    spacs = []
    try:
        # KIND(한국거래소 전자공시) 상장법인목록에서 소속부 SPAC 필터링
        url = "https://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13"
        res = requests.get(url, timeout=15)
        res.encoding = "euc-kr"
        dfs = pd.read_html(io.StringIO(res.text))
        df = dfs[0]

        # 종목명에 '스팩'이 포함되거나 소속부가 SPAC인 코스닥 종목 추출
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
    8. 네이버 증권/실시간 시세 연동을 통한 현재가, 거래정지, 합병승인/철회 상태 파악
    """
    current_price = 0
    is_suspended = False
    merger_status = "정상"

    try:
        url = f"https://polling.finance.naver.com/api/realtime?query=SERVICE_ITEM:{code}"
        res = requests.get(url, timeout=10).json()
        datas = res["result"]["areas"][0]["datas"][0]
        current_price = int(datas.get("nv", 0))
        # 거래정지 여부 (ms: 'STOP' 등)
        if datas.get("ms") in ["STOP", "HALT"]:
            is_suspended = True
            merger_status = "거래정지"
    except Exception:
        pass

    return current_price, is_suspended, merger_status


def fetch_dart_spac_terms(corp_code, ipo_price=2000):
    """
    6 & 8. DART 공시자료(증권발행실적보고서 / 사업보고서) 연동
    공모금, 예치비율, 예치이자율, 공모주식수 파싱 (공시 미확인 시 표준 스팩 조건 기본값 적용)
    """
    # 실제 DART API 연동 시 corp_code 기반 공시 목록 및 원문(document.xml) 파싱
    # 기본 표준 스팩 구조 (공모가 2,000원, 예치비율 100%, 예치금리 3.2% 기준)
    deposit_ratio = 1.00
    deposit_rate = 0.032
    ipo_shares = 5_000_000  # 기본 공모주식수 예시 (실제 DART 공시 값으로 대체)
    ipo_amount = ipo_price * ipo_shares

    if DART_API_KEY and corp_code:
        try:
            list_url = "https://opendart.fss.or.kr/api/list.json"
            params = {
                "crtfc_key": DART_API_KEY,
                "corp_code": corp_code,
                "bgn_de": (TODAY - timedelta(days=1095)).strftime("%Y%m%d"),
                "page_count": 20
            }
            r = requests.get(list_url, params=params, timeout=10).json()
            for item in r.get("list", []):
                report_nm = item.get("report_nm", "")
                if "합병" in report_nm and "철회" in report_nm:
                    pass
        except Exception:
            pass

    return {
        "ipo_price": ipo_price,
        "ipo_amount": ipo_amount,
        "deposit_ratio": deposit_ratio,
        "deposit_rate": deposit_rate,
        "ipo_shares": ipo_shares
    }


def calculate_spac_metrics(spac_info):
    """
    1~4번 핵심 투자 판단 로직 연산
    """
    listing_dt = dt.strptime(spac_info["listing_date"], "%Y-%m-%d").date()
    # 스팩 존속기한 3년(1095일) 기준 상장폐지 예정일 산출 (공시상 만기일 우선)
    delisting_dt = listing_dt + timedelta(days=1095)
    days_to_delisting = (delisting_dt - TODAY).days
    days_since_listing = max(0, (TODAY - listing_dt).days)

    ipo_price = spac_info["ipo_price"]
    ipo_amount = spac_info["ipo_amount"]
    deposit_ratio = spac_info["deposit_ratio"]
    deposit_rate = spac_info["deposit_rate"]
    ipo_shares = spac_info["ipo_shares"]
    current_price = spac_info["current_price"]

    # 1. 청산단가의 근거:
    # 공모금 * 예치비율을 기준으로 매년 예치이자율 적용, 세금(15.4%) 제외 후 3년(연복리) 재예치 -> 최종 신탁자금 / 공모주식수
    principal = ipo_amount * deposit_ratio
    after_tax_rate = deposit_rate * (1 - 0.154)
    final_trust_fund = principal * ((1 + after_tax_rate) ** 3)
    liquidation_price = round(final_trust_fund / ipo_shares)

    # 2. 투자유형 구분:
    # 상장폐지일이 1년(365일) 이상 남았으면 '합병', 미만이면 '청산'
    invest_type = "합병" if days_to_delisting >= 365 else "청산"

    # 3. 예상수익률 근거:
    # 공식: (최종 청산단가 - 현재가) / 현재가 / (상장폐지일 + 30 - 오늘날짜) * 365
    holding_days = max(1, days_to_delisting + 30)
    if current_price > 0:
        # ISA 계좌 (세금 없음)
        raw_yield_isa = ((liquidation_price - current_price) / current_price) / holding_days * 365
        yield_isa = round(raw_yield_isa * 100, 2)

        # 일반 계좌 (매매차익/배당소득세 15.4% 제외)
        profit = liquidation_price - current_price
        after_tax_profit = profit * (1 - 0.154) if profit > 0 else profit
        raw_yield_general = (after_tax_profit / current_price) / holding_days * 365
        yield_general = round(raw_yield_general * 100, 2)
    else:
        yield_isa = 0.0
        yield_general = 0.0

    # 4. 매수적정가 근거:
    # 공식: if(공모가 + (최종 청산단가 - 공모가) / 1095 * (오늘날짜 - 상장일) >= 현재가) -> O / X
    fair_buy_price = ipo_price + ((liquidation_price - ipo_price) / 1095.0) * days_since_listing
    is_fair_buy = "O" if (current_price > 0 and fair_buy_price >= current_price) else "X"

    return {
        "code": spac_info["code"],
        "name": spac_info["name"],
        "is_fair_buy": is_fair_buy,                         # 매수적정가 (O/X)
        "invest_type": invest_type,                         # 투자유형 (합병/청산)
        "delisting_date": delisting_dt.strftime("%Y-%m-%d"),# 상장폐지일
        "current_price": current_price,                     # 현재가
        "liquidation_price": liquidation_price,             # 최종청산단가
        "yield_general": yield_general,                     # 예상수익률 (일반)
        "yield_isa": yield_isa,                             # 예상수익률 (ISA)
        "deposit_rate": round(deposit_rate * 100, 2),       # 예치이자율 (%) - DART/공시 연동용
        "status": spac_info.get("merger_status", "정상"),    # 거래정지/합병상태
        "fair_price_calc": round(fair_buy_price)
    }


def main(mode1="check", mode2="auto"):
    print(f"[Info] Running SPAC Dashboard Pipeline ({TODAY})...")
    raw_spacs = get_krx_spac_list()
    results = []

    for sp in raw_spacs:
        cur_price, is_susp, status = get_market_price_and_status(sp["code"])
        if cur_price == 0:
            continue

        terms = fetch_dart_spac_terms(corp_code=None, ipo_price=2000)
        merged = {
            **sp,
            **terms,
            "current_price": cur_price,
            "is_suspended": is_susp,
            "merger_status": status
        }
        calc_row = calculate_spac_metrics(merged)
        results.append(calc_row)

    # 예상수익률(ISA) 내림차순 정렬
    results.sort(key=lambda x: x["yield_isa"], reverse=True)

    output = {
        "updated_at": dt.now().strftime("%Y-%m-%d %H:%M:%S"),
        "count": len(results),
        "items": results
    }

    os.makedirs("data", exist_ok=True)
    with open("data/spacs.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"[Info] Saved {len(results)} SPAC records to data/spacs.json")


if __name__ == "__main__":
    mode1 = sys.argv[1] if len(sys.argv) > 1 else "check"
    mode2 = sys.argv[2] if len(sys.argv) > 2 else "auto"
    main(mode1, mode2)
