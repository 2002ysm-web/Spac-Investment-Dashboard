import sys,os,datetime as dt; sys.path.insert(0,os.path.dirname(__file__))
import update_data as u
t="... 예치금 이자율은 연 3.45% 로 ... 공모금액 10,000,000,000원 ... 공모주식수 5,000,000주 ... 예치 비율 100% ..."
assert u.RATE_RE.search(t).group(1)=='3.45'; assert u.num(u.AMT_RE.search(t).group(1))==1e10
assert u.num(u.SHR_RE.search(t).group(1))==5e6; assert u.RATIO_RE.search(t).group(1)=='100'
html='<table><tr><td>1</td><td>2026-02-05 17:50</td><td>엔에이치스팩29호</td><td>주권매매거래정지해제(상장예비심사결과통지(승인))</td></tr></table>'
u.http=lambda *a,**k: html.encode()
r=u.kind_search('x','2026-01-01','2026-12-31'); assert r[0]['name']=='엔에이치스팩29호' and r[0]['at']=='2026-02-05',r
print('parser tests OK')

# --- 가격 폴백 체인 / KRX 교차검증 (모의 응답)
import json
now=dt.datetime(2026,11,13,10,0,tzinfo=u.KST)
sp=[dict(code='000001',name='A스팩1호',price=2000.0,krxClose=2010.0,sources={}),
    dict(code='000002',name='B스팩2호',price=2000.0,krxClose=2010.0,sources={}),
    dict(code='000003',name='C스팩3호',price=2000.0,krxClose=2010.0,sources={})]
u.naver_poll=lambda c:{'000001':(2105.0,'OPEN')}
def nm(c): raise ValueError('x')
u.naver_mobile=nm
u.google_quote=lambda c:2222.0 if c=='000002' else (_ for _ in ()).throw(ValueError('x'))
r=u.update_prices(sp,now)
assert [s['price'] for s in sp]==[2105.0,2222.0,2010.0] and [s['sources']['price'] for s in sp]==['naver','google','krx'],sp
rows_info=[{'ISU_SRT_CD':'000001','ISU_ABBRV':'A스팩1호','ISU_NM':'A기업인수목적','SECT_TP_NM':'SPAC(소속부없음)','LIST_DD':'2024/01/02','LIST_SHRS':'3,000,000'},
           {'ISU_SRT_CD':'000009','ISU_ABBRV':'Z스팩9호','ISU_NM':'Z기업인수목적','SECT_TP_NM':'관리종목(소속부없음)','LIST_DD':'2024/02/03','LIST_SHRS':'1,000,000'},
           {'ISU_SRT_CD':'111111','ISU_ABBRV':'일반회사','ISU_NM':'일반회사','SECT_TP_NM':'우량기업부','LIST_DD':'2000/01/01','LIST_SHRS':'1'}]
rows_px=[{'ISU_SRT_CD':'000001','TDD_CLSPRC':'2,010'},{'ISU_SRT_CD':'000009','TDD_CLSPRC':'2,000'}]
u.krx=lambda bld,**k:{'OutBlock_1':rows_info if '01901' in bld else rows_px}
sp2=[dict(code='000001',name='A스팩1호',rates=[.03],sources={}),dict(code='000002',name='B스팩2호(상폐)',rates=[.03],sources={})]
k=u.update_krx(sp2,dt.date(2026,11,13))
assert k['added']==['Z스팩9호'] and k['removed']==['B스팩2호(상폐)'] and k['count']==2 and k['tradingCount']==2,k
print('price chain + krx cross-check tests OK')
# --- KRX Open API 정규화 / KIS 우선순위
import importlib; importlib.reload(u); now=dt.datetime(2026,11,13,10,0,tzinfo=u.KST)
os.environ['KRX_OPENAPI_KEY']='k'
u.http=lambda url,*a,**k: json.dumps({'OutBlock_1':[{'ISU_CD':'000001','ISU_NM':'A스팩1호','TDD_CLSPRC':'2,010'}]}).encode()
rr=u.krx('dbms/MDC/STAT/standard/MDCSTAT01501')['OutBlock_1'][0]; assert rr['ISU_SRT_CD']=='000001' and rr['ISU_ABBRV']=='A스팩1호'
os.environ['KIS_APP_KEY']='a'; os.environ['KIS_APP_SECRET']='b'
u.kis_prices=lambda c:{'000001':(2111.0,'KIS')}; u.naver_poll=lambda c:{'000001':(2105.0,'x')}
s3=[dict(code='000001',name='A',price=1,krxClose=2010.0,sources={})]; u.update_prices(s3,now); assert s3[0]['price']==2111.0 and s3[0]['sources']['price']=='kis'
print('open api tests OK')
