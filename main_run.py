import os
import sys
import json
import base64
import io
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime as dt, timedelta
import requests
import pandas as pd

DART_API_KEY = os.environ.get("DART_API_KEY", "")
KRX_OPENAPI_KEY = os.environ.get("KRX_OPENAPI_KEY", "")
TODAY = dt.now().date()

def get_dart_corp_codes():
    mapping = {}
    if not DART_API_KEY:
        return mapping
    try:
        url = f"https://opendart.fss.or.kr/api/corpCode.xml?crtfc_key={DART_API_KEY}"
        res = requests.get(url, timeout=20)
        if res.status_code == 200:
            with zipfile.ZipFile(io.BytesIO(res.content)) as z:
                with z.open(z.namelist()[0]) as f:
                    tree = ET.parse(f)
                    root = tree.getroot()
                    for item in root.findall("list"):
                        stock_code = item.findtext("stock_code")
                        corp_code = item.findtext("corp_code")
                        if stock_code and stock_code.strip():
                            mapping[stock_code.strip().zfill(6)] = corp_code.strip()
    except Exception as e:
        print(f"DART corpCode error: {e}")
    return mapping

def get_krx_spac_list():
    spacs = []
    try:
        url = "https://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13"
        res = requests.get(url, timeout=15)
        res.encoding = "euc-kr"
        dfs = pd.read_html(io.StringIO(res.text))
        df = dfs[0]
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
        print(f"KRX error: {e}")
    return spacs

def check_market_and_dart_status(code, corp_code):
    status = "정상"
    is_suspended = False
    current_price = 0

    # 1. 네이버 금융 실시간 시세 및 거래정지 여부 확인
    try:
        url = f"https://polling.finance.naver.com/api/realtime?query=SERVICE_ITEM:{code}"
        res = requests.get(url, timeout=10).json()
        datas = res["result"]["areas"][0]["datas"][0]
        current_price = int(datas.get("nv", 0))
        ms = str(datas.get("ms", ""))
        if ms in ["STOP", "HALT", "SUSPENSION"] or current_price == 0:
            is_suspended = True
            status = "거래정지"
    except Exception:
        is_suspended = True
        status = "거래정지"

    # 2. DART 공시 기반 상태 확인 (최신 접수일자 순 정렬 후 반영)
    if DART_API_KEY and corp_code and not is_suspended:
        try:
            bgn_de = (TODAY - timedelta(days=365)).strftime('%Y%m%d')
            url = f"https://opendart.fss.or.kr/api/list.json?crtfc_key={DART_API_KEY}&corp_code={corp_code}&bgn_de={bgn_de}&pblntf_ty=A"
            res = requests.get(url, timeout=5).json()
            if res.get("status") == "000":
                reports = res.get("list", [])
                # 접수일자(rcept_dt) 기준 내림차순(최신순) 정렬
                reports_sorted = sorted(reports, key=lambda x: x.get("rcept_dt", ""), reverse=True)
                
                for r in reports_sorted:
                    report_nm = r.get("report_nm", "")
                    # 최신순으로 스캔하므로 가장 먼저 매칭되는 결정적 공시가 최종 상태가 됨
                    if "매매거래정지" in report_nm:
                        status = "거래정지"
                        break
                    elif "합병철회" in report_nm or "합병의 철회" in report_nm:
                        status = "합병철회"
                        break
                    elif "합병종료" in report_nm or "합병승인" in report_nm:
                        status = "합병승인"
                        break
        except Exception:
            pass

    return current_price, is_suspended, status

def fetch_dart_spac_terms(ipo_price=2000):
    return {
        "ipo_price": ipo_price,
        "ipo_amount": ipo_price * 5_000_000,
        "deposit_ratio": 1.00,
        "deposit_rate": 0.032,
        "ipo_shares": 5_000_000
    }

def calculate_spac_metrics(spac_info):
    listing_dt = dt.strptime(spac_info["listing_date"], "%Y-%m-%d").date()
    delisting_dt = listing_dt + timedelta(days=1095)
    days_to_delisting = (delisting_dt - TODAY).days
    days_since_listing = max(0, (TODAY - listing_dt).days)

    ipo_price = spac_info["ipo_price"]
    ipo_amount = spac_info["ipo_amount"]
    deposit_ratio = spac_info["deposit_ratio"]
    deposit_rate = spac_info["deposit_rate"]
    ipo_shares = spac_info["ipo_shares"]
    current_price = spac_info["current_price"]
    merger_status = spac_info.get("merger_status", "정상")

    principal = ipo_amount * deposit_ratio
    after_tax_rate = deposit_rate * (1 - 0.154)
    final_trust_fund = principal * ((1 + after_tax_rate) ** 3)
    liquidation_price = round(final_trust_fund / ipo_shares)

    invest_type = "합병" if days_to_delisting >= 365 else "청산"

    holding_days = max(1, days_to_delisting + 30)
    if current_price > 0 and merger_status != "거래정지":
        raw_yield_isa = ((liquidation_price - current_price) / current_price) / holding_days * 365
        yield_isa = round(raw_yield_isa * 100, 2)

        profit = liquidation_price - current_price
        after_tax_profit = profit * (1 - 0.154) if profit > 0 else profit
        raw_yield_general = (after_tax_profit / current_price) / holding_days * 365
        yield_general = round(raw_yield_general * 100, 2)
    else:
        yield_isa = 0.0
        yield_general = 0.0

    fair_buy_price = ipo_price + ((liquidation_price - ipo_price) / 1095.0) * days_since_listing
    is_fair_buy = "O" if (current_price > 0 and merger_status != "거래정지" and fair_buy_price >= current_price) else "X"

    return {
        "code": spac_info["code"],
        "name": spac_info["name"],
        "is_fair_buy": is_fair_buy,
        "invest_type": invest_type,
        "delisting_date": delisting_dt.strftime("%Y-%m-%d"),
        "current_price": current_price,
        "liquidation_price": liquidation_price,
        "yield_general": yield_general,
        "yield_isa": yield_isa,
        "deposit_rate": round(deposit_rate * 100, 2),
        "status": merger_status,
        "fair_price_calc": round(fair_buy_price)
    }

def upload_json_to_github(file_path="data/spacs.json"):
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("REPO") or os.environ.get("GITHUB_REPOSITORY")
    
    if not token or not repo:
        print("Error: No Token or Repo")
        sys.exit(1)

    url = f"https://api.github.com/repos/{repo}/contents/{file_path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json"
    }

    sha = None
    res = requests.get(url, headers=headers)
    if res.status_code == 200:
        sha = res.json().get("sha")

    if not os.path.exists(file_path):
        print(f"Error: File not found {file_path}")
        sys.exit(1)

    with open(file_path, "rb") as f:
        content_bytes = f.read()
    content_encoded = base64.b64encode(content_bytes).decode("utf-8")

    payload = {
        "message": "data: auto update spacs.json via API",
        "content": content_encoded,
        "branch": "main"
    }
    if sha:
        payload["sha"] = sha

    put_res = requests.put(url, headers=headers, json=payload)
    if put_res.status_code in [200, 201]:
        print("Success API upload")
    else:
        print(f"Error API upload: {put_res.status_code}, {put_res.text}")
        sys.exit(1)

def main():
    print(f"Running SPAC Pipeline ({TODAY})...")
    raw_spacs = get_krx_spac_list()
    corp_mapping = get_dart_corp_codes()
    results = []

    for sp in raw_spacs:
        code = sp["code"]
        corp_code = corp_mapping.get(code, None)
        
        cur_price, is_susp, status = check_market_and_dart_status(code, corp_code)
        terms = fetch_dart_spac_terms()
        
        merged = {**sp, **terms, "current_price": cur_price, "is_suspended": is_susp, "merger_status": status}
        calc_row = calculate_spac_metrics(merged)
        results.append(calc_row)

    results.sort(key=lambda x: x["yield_isa"], reverse=True)
    output = {
        "updated_at": dt.now().strftime("%Y-%m-%d %H:%M:%S"),
        "count": len(results),
        "items": results
    }

    os.makedirs("data", exist_ok=True)
    with open("data/spacs.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"Saved {len(results)} records.")

if __name__ == "__main__":
    main()
    upload_json_to_github()
