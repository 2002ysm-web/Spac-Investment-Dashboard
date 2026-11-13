#!/usr/bin/env python3
"""엑셀(SPAC 투자 판단표)의 스냅샷을 data/spac.json 으로 변환한다. (최초 1회용 시드 생성기)

읽는 시트: 총괄표(공모가·공모금·예치비율·예치이자율·공모주식수), 종목 정보(상장일·소속부·코드),
          종목 시세(종가), 지정 내역(거래정지·관리종목), 합병 승인, 합병 철회
사용: python3 build_seed_from_xlsx.py <엑셀경로> [출력경로]
"""
import datetime as dt
import json
import re
import sys

import openpyxl

SRC = sys.argv[1]
OUT = sys.argv[2] if len(sys.argv) > 2 else "data/spac.json"

wb = openpyxl.load_workbook(SRC, data_only=True)
tot, info, px, flag = wb["총괄표"], wb["종목 정보"], wb["종목 시세"], wb["지정 내역"]
ap, wd = wb["합병 승인"], wb["합병 철회"]


def iso(v):
    """엑셀 날짜 셀(datetime / '2026-02-0517:50' / '2026-05-26')을 ISO 문자열로."""
    if v is None:
        return None
    if isinstance(v, dt.datetime):
        return v.strftime("%Y-%m-%dT%H:%M") if (v.hour or v.minute) else v.strftime("%Y-%m-%d")
    s = str(v).strip()
    m = re.match(r"(\d{4}-\d{2}-\d{2})(\d{2}:\d{2})?", s)
    if not m:
        return None
    return m.group(1) + ("T" + m.group(2) if m.group(2) else "")


def code6(v):
    if isinstance(v, (int, float)):
        return f"{int(v):06d}"
    return str(v).strip()


# 종목명(약명) 기준 조회표
info_by = {info.cell(r, 4).value: r for r in range(2, info.max_row + 1)}
px_by = {px.cell(r, 2).value: r for r in range(2, px.max_row + 1)}
flag_by = {flag.cell(r, 2).value: r for r in range(2, flag.max_row + 1)}


def latest_by_key(ws):
    """공시 시트를 종목코드(없으면 회사명)별 최신 시각으로 요약. 공시 시점 사명이 현재 종목명과 달라도 코드로 매칭된다."""
    out = {}
    for r in range(2, ws.max_row + 1):
        code, n, t = ws.cell(r, 4).value, ws.cell(r, 2).value, iso(ws.cell(r, 3).value)
        key = code6(code) if code else n
        if key and t and (key not in out or t > out[key]):
            out[key] = t
    return out


approved, withdrawn = latest_by_key(ap), latest_by_key(wd)

# 엑셀 TODAY() 캐시값 = 데이터 기준일
price_date = tot["Y3"].value.strftime("%Y-%m-%d")

spacs = []
for r in range(3, tot.max_row + 1):
    name = tot.cell(r, 2).value
    if not name:
        continue
    ir, pr, fr = info_by[name], px_by[name], flag_by[name]
    rates = [tot.cell(r, c).value for c in (13, 14, 15)]  # M,N,O = 1·2·3년차 예치이자율
    section = str(info.cell(ir, 9).value)
    spacs.append({
        "code": code6(info.cell(ir, 2).value),
        "name": name,
        "full_name": info.cell(ir, 3).value,
        "listed": iso(info.cell(ir, 6).value),
        "section": "SPAC" if section.startswith("SPAC") else section.split("(")[0],
        "ipo_price": tot.cell(r, 3).value,
        "ipo_amount": tot.cell(r, 8).value,
        "ipo_shares": tot.cell(r, 16).value,
        "deposit_ratio": tot.cell(r, 9).value,
        "rates": rates,
        "price": px.cell(pr, 4).value,
        "price_date": price_date,
        "halted": flag.cell(fr, 3).value == "O",
        "managed": flag.cell(fr, 5).value == "O",
        "merger": {
            "approved": approved.get(code6(info.cell(ir, 2).value)) or approved.get(name),
            "withdrawn": withdrawn.get(code6(info.cell(ir, 2).value)) or withdrawn.get(name),
        },
    })

spacs.sort(key=lambda s: s["name"])
doc = {
    "meta": {
        "generated_at": price_date + "T00:00:00+09:00",
        "price_date": price_date,
        "constants": {
            "deposit_net": 0.845,   # 예치금 이자 세후율 (15.5% = 배당소득세 14% + 지방소득세 1.4% + 수수료 0.1%)
            "gain_net": 0.846,      # 일반계좌 세후율 (세금 15.4%)
            "life_days": 1095,      # 상장일 + 365×3
            "merge_days": 365,      # 상장폐지일까지 365일 이상 → 합병, 미만 → 청산
            "liq_lag_days": 30,     # 청산금 지급까지 상장폐지일 + 30일
        },
        "universe": {
            "rule": "코스닥 소속부 SPAC + 종목명 '기업인수목적'(관리종목 등 소속부 변경 종목 포함)",
            "count": len(spacs),
        },
        "sources": {
            "krx_listing": {"label": "KRX 코스닥 종목정보·시세", "status": "seed", "at": price_date, "note": ""},
            "krx_flags": {"label": "KRX 거래정지·관리종목 지정", "status": "seed", "at": price_date, "note": ""},
            "kind_merger": {"label": "KIND 합병 승인·철회 공시", "status": "seed", "at": price_date, "note": ""},
            "dart_offering": {"label": "DART 공모가·공모금·공모주식수·예치비율", "status": "seed", "at": price_date, "note": ""},
            "dart_rates": {"label": "DART·네이버 증권 예치이자율", "status": "seed", "at": price_date, "note": ""},
        },
    },
    "spacs": spacs,
}
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(doc, f, ensure_ascii=False, indent=1)
print(f"{len(spacs)}종목 → {OUT} (기준일 {price_date})")
