import os
import sys
import json
import base64
import io
from datetime import datetime as dt, timedelta
import requests
import pandas as pd

DART_API_KEY = os.environ.get("DART_API_KEY", "")
KRX_OPENAPI_KEY = os.environ.get("KRX_OPENAPI_KEY", "")
KIS_APP_KEY = os.environ.get("KIS_APP_KEY", "")
KIS_APP_SECRET = os.environ.get("KIS_APP_SECRET", "")

TODAY = dt.now().date()

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

def get_market_price_and_status(code):
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

    principal = ipo_amount * deposit_ratio
    after_tax_rate = deposit_rate * (1 - 0.154)
    final_trust_fund = principal * ((1 + after_tax_rate) ** 3)
    liquidation_price = round(final_trust_fund / ipo_shares)

    invest_type = "합병" if days_to_delisting >= 365 else "청산"

    holding_days = max(1, days_to_delisting + 30)
    if current_price > 0:
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
    is_fair_buy = "O" if (current_price > 0 and fair_buy_price >= current_price) else "X"

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
        "status": spac_info.get("merger_status", "정상"),
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
    results = []

    for sp in raw_spacs:
        cur_price, is_susp, status = get_market_price_and_status(sp["code"])
        if cur_price == 0:
            continue
        terms = fetch_dart_spac_terms(corp_code=None, ipo_price=2000)
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
