"""엑셀(SPAC 총괄표 등)에서 초기 시드 데이터(data/spacs.json)를 만든다."""
import json, sys, datetime as dt, openpyxl

def d(x): return x.strftime('%Y-%m-%d') if hasattr(x,'strftime') else None
def code6(v):
    s = str(int(v)) if isinstance(v,(int,float)) else str(v)
    return s.zfill(6)

def main(path, out):
    wf = openpyxl.load_workbook(path)           # formulas (for hard-coded inputs)
    wv = openpyxl.load_workbook(path, data_only=True)
    tot = wv['총괄표']; info = wv['종목 정보']; px = wv['종목 시세']; flag = wv['지정 내역']
    info_by = {r[3]: r for r in info.iter_rows(min_row=2, values_only=True)}
    px_by = {r[1]: r for r in px.iter_rows(min_row=2, values_only=True)}
    halt_by = {r[1]: r[2] for r in flag.iter_rows(min_row=2, values_only=True)}
    appr, wdr = {}, {}
    for sh, dct in ((wv['합병 승인'], appr), (wv['합병 철회'], wdr)):
        for r in sh.iter_rows(min_row=2, values_only=True):
            if r[1] and r[2]:
                t = str(r[2])[:10]
                if r[1] not in dct or t > dct[r[1]]: dct[r[1]] = t
    items = []
    for r in range(3, tot.max_row+1):
        name = tot.cell(r,2).value
        if not name: continue
        i = info_by[name]; p = px_by[name]
        rates = [tot.cell(r,c).value for c in (13,14,15)]
        items.append(dict(
            code=code6(i[1]), name=name, fullName=i[2], section=i[8],
            ipoPrice=tot.cell(r,3).value, listDate=d(i[5]),
            price=p[3], offerAmount=tot.cell(r,8).value, depositRatio=tot.cell(r,9).value,
            rates=rates, shares=tot.cell(r,16).value,
            halted=(halt_by.get(name)=='O'),
            mergerApprovedAt=appr.get(name), mergerWithdrawnAt=wdr.get(name),
            sources=dict(price='excel', rates='excel', offer='excel', shares='excel'),
        ))
    doc = dict(updatedAt='2026-11-12T15:30:00+09:00', priceDate='2026-11-12',
               note='엑셀(2026-11-12 저장본) 기준 초기 시드', spacs=items)
    json.dump(doc, open(out,'w'), ensure_ascii=False, indent=1)
    print(len(items), 'spacs')

if __name__ == '__main__': main(sys.argv[1], sys.argv[2])
