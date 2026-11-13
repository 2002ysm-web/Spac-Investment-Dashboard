#!/usr/bin/env python3
"""스팩 대시보드 자동 업데이트 수집기 (표준 라이브러리만 사용).

data/spacs.json 을 읽어 아래 소스로 갱신하고 다시 저장한다. 각 소스는 독립적으로 실행되며
실패하면 기존 값을 유지하고 data/spacs.json 의 `status` 에 오류를 기록한다.

  1) KRX 정보데이터시스템  : 소속부 SPAC 전종목(누락 방지), 상장일, 상장주식수, 종가(현재가)
  2) KIND 공시           : 합병 승인(상장예비심사 승인) / 합병결정 철회 / 거래정지 공시
  3) OpenDART            : 공모금·공모주식수·공모가·예치비율·예치이자율 (투자설명서/정기보고서)
  4) 네이버 증권          : 현재가(실시간) 및 종목별 공시 목록 (KRX 시세 실패 시 보조)

환경변수
  DART_API_KEY  OpenDART 인증키 (https://opendart.fss.or.kr)  - 없으면 DART 단계 건너뜀
  KRX_COOKIE    (선택) KRX 데이터포털이 로그인 세션을 요구할 때 브라우저 쿠키 문자열(JSESSIONID=...)

주의: 이 스크립트의 엔드포인트/응답 필드는 공개 문서와 기존 사용례 기준으로 작성했으며,
      배포 환경에서 첫 실행 시 `python scripts/update_data.py --dry-run -v` 로 확인하세요.
      data/overrides.json 에 적은 값은 자동 수집값보다 항상 우선합니다.
"""
import argparse, datetime as dt, io, json, os, re, sys, time, zipfile
import urllib.parse, urllib.request
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data', 'spacs.json')
OVR = os.path.join(ROOT, 'data', 'overrides.json')
UA = 'Mozilla/5.0 (compatible; spac-dashboard/1.0)'
KST = dt.timezone(dt.timedelta(hours=9))
SPAC_NAME = re.compile(r'스팩|기업인수목적')
VERBOSE = False


def log(*a):
    if VERBOSE: print(*a, file=sys.stderr)


def http(url, data=None, headers=None, timeout=30, retries=2):
    h = {'User-Agent': UA}; h.update(headers or {})
    body = urllib.parse.urlencode(data).encode() if isinstance(data, dict) else data
    last = None
    for i in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=body, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa
            last = e; time.sleep(1.5 * (i + 1))
    raise last


def num(x):
    if x is None: return None
    s = re.sub(r'[,\s]', '', str(x))
    try: return float(s)
    except ValueError: return None


# ------------------------------------------------------------------ 1) KRX
KRX_URL = 'https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd'

KRX_OA = 'https://data-dbg.krx.co.kr/svc/apis/sto/'
OA_MAP = {'dbms/MDC/STAT/standard/MDCSTAT01901': 'ksq_isu_base_info',
          'dbms/MDC/STAT/standard/MDCSTAT01501': 'ksq_bydd_trd'}


def last_weekdays(n=6):
    d = dt.datetime.now(KST).date(); out = []
    while len(out) < n:
        if d.weekday() < 5: out.append(d)
        d -= dt.timedelta(days=1)
    return out


def krx_openapi(bld, **params):
    """KRX Open API (openapi.krx.co.kr, 헤더 AUTH_KEY). 포털과 같은 키 이름으로 정규화해 돌려준다."""
    key = os.environ['KRX_OPENAPI_KEY']; ep = OA_MAP[bld]
    days = [dt.datetime.strptime(params['trdDd'], '%Y%m%d').date()] if params.get('trdDd') else last_weekdays()
    for d in days:
        j = json.loads(http(KRX_OA + ep + '?basDd=' + d.strftime('%Y%m%d'), headers={'AUTH_KEY': key}).decode('utf-8'))
        rows = j.get('OutBlock_1', [])
        if rows: break
    for r in rows:
        r['ISU_SRT_CD'] = r.get('ISU_SRT_CD') or r.get('ISU_CD', '')
        r.setdefault('ISU_ABBRV', r.get('ISU_NM', '')); r.setdefault('SECT_TP_NM', r.get('SECT_TP_NM', ''))
        if 'LIST_DD' in r: r['LIST_DD'] = str(r['LIST_DD']).replace('/', '-')
    return {'OutBlock_1': rows}


def krx(bld, **params):
    if os.environ.get('KRX_OPENAPI_KEY') and bld in OA_MAP: return krx_openapi(bld, **params)
    hdr = {'Referer': 'https://data.krx.co.kr/contents/MDC/MDI/mdiLoader',
           'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'}
    if os.environ.get('KRX_COOKIE'): hdr['Cookie'] = os.environ['KRX_COOKIE']
    p = dict(bld=bld, locale='ko_KR', share='1', csvxls_isNo='false'); p.update(params)
    return json.loads(http(KRX_URL, p, hdr).decode('utf-8'))


def update_krx(spacs, today):
    # 종목 기본정보(코스닥) -> 소속부 SPAC + 이름에 스팩/기업인수목적 포함(관리종목 등으로 표기된 스팩 포함)
    base = krx('dbms/MDC/STAT/standard/MDCSTAT01901', mktId='KSQ')['OutBlock_1']
    found = [r for r in base if str(r.get('SECT_TP_NM', '')).startswith('SPAC')
             or SPAC_NAME.search(r.get('ISU_ABBRV', '') + r.get('ISU_NM', ''))]
    have = {s['code']: s for s in spacs}
    added = []
    for r in found:
        code = r['ISU_SRT_CD'].zfill(6)
        if code not in have:
            s = dict(code=code, name=r['ISU_ABBRV'], fullName=r['ISU_NM'], ipoPrice=2000.0,
                     rates=[None, None, None], depositRatio=1.0, halted=False,
                     mergerApprovedAt=None, mergerWithdrawnAt=None, sources={}, isNew=True)
            spacs.append(s); have[code] = s; added.append(r['ISU_ABBRV'])
        s = have[code]
        s['section'] = r.get('SECT_TP_NM'); s['name'] = r['ISU_ABBRV']
        s['listDate'] = r['LIST_DD'].replace('/', '-')
        lst = num(r.get('LIST_SHRS'))
        if lst and not s.get('shares'):      # 공모주식수 미확정 시 상장주식수로 임시 대체
            s['shares'] = lst; s.setdefault('sources', {})['shares'] = 'krx-listed'
    # 상장폐지된 종목은 목록에서 빠지므로 제거(상장 목록에 없고 새로 수집한 경우만)
    live = {r['ISU_SRT_CD'].zfill(6) for r in found}
    gone = [s['name'] for s in spacs if s['code'] not in live]
    spacs[:] = [s for s in spacs if s['code'] in live]
    # 전종목 시세 (가장 최근 영업일) - 거래 중 여부 및 보조 시세
    day, rows = None, []
    for back in range(0, 6):
        d = (today - dt.timedelta(days=back))
        if d.weekday() >= 5: continue
        rows = krx('dbms/MDC/STAT/standard/MDCSTAT01501', mktId='KSQ', trdDd=d.strftime('%Y%m%d'),
                   money='1').get('OutBlock_1', [])
        if rows: day = d; break
    px = {r['ISU_SRT_CD'].zfill(6): num(r['TDD_CLSPRC']) for r in rows}
    trading = {c for c, v in px.items() if v}
    for s in spacs:
        s['krxClose'] = px.get(s['code'])
        s['tradingOnKrx'] = s['code'] in trading
        if px.get(s['code']) and not s.get('price'):
            s['price'] = px[s['code']]; s.setdefault('sources', {})['price'] = 'krx'
    krx_codes = sorted(live)
    return dict(added=added, removed=gone, priceDate=day.isoformat() if day else None, count=len(found),
                tradingCount=len([c for c in krx_codes if c in trading]),
                notTrading=[s['name'] for s in spacs if s['code'] not in trading], codes=krx_codes)


# ------------------------------------------------------------------ 2) KIND
KIND_URL = 'https://kind.krx.co.kr/disclosure/details.do'

def kind_search(keyword, since, until):
    """KIND 공시상세검색 HTML 표에서 (회사명, 시각, 종목코드, 제목) 목록을 읽는다."""
    out, page = [], 1
    while page <= 10:
        html = http(KIND_URL, dict(method='searchDetailsSub', currentPageSize='100', pageIndex=str(page),
                                   orderMode='1', orderStat='D', forward='details_sub',
                                   fromDate=since, toDate=until, reportNm=keyword,
                                   bfrDsclsType='on'),
                    {'Referer': 'https://kind.krx.co.kr/disclosure/details.do?method=searchDetailsMain'}
                    ).decode('utf-8', 'replace')
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.S)
        got = 0
        for tr in rows:
            tds = re.findall(r'<td[^>]*>(.*?)</td>', tr, re.S)
            if len(tds) < 4: continue
            txt = [re.sub(r'<[^>]+>|\s+', ' ', t).strip() for t in tds]
            when = next((t for t in txt if re.match(r'\d{4}-\d{2}-\d{2}', t)), None)
            name = next((t for t in txt if SPAC_NAME.search(t) and len(t) < 30), None)
            title = max(txt, key=len)
            if when and name:
                out.append(dict(name=name.replace('\xa0', '').strip(), at=when[:10], title=title)); got += 1
        if got < 100 and page > 1 or not rows: break
        page += 1
    return out


def update_kind(spacs, today):
    since = (today - dt.timedelta(days=900)).isoformat(); until = today.isoformat()
    appr = kind_search('상장예비심사결과통지(승인)', since, until)
    wdr = kind_search('합병결정', since, until)
    wdr = [e for e in wdr if '철회' in e['title']]
    halt = kind_search('매매거래정지', (today - dt.timedelta(days=120)).isoformat(), until)
    by = {s['name']: s for s in spacs}
    for kind, evs in (('mergerApprovedAt', appr), ('mergerWithdrawnAt', wdr)):
        latest = {}
        for e in evs:
            if e['name'] in by and e['at'] > latest.get(e['name'], ''): latest[e['name']] = e['at']
        for n, t in latest.items():
            if t >= (by[n].get(kind) or ''): by[n][kind] = t
    # 거래정지: 최근 '정지' 공시가 '해제' 공시보다 늦으면 정지 중
    state = {}
    for e in sorted(halt, key=lambda e: e['at']):
        if e['name'] not in by: continue
        if '해제' in e['title']: state[e['name']] = False
        elif '정지' in e['title']: state[e['name']] = True
    for n, v in state.items(): by[n]['halted'] = v
    dl = kind_search('상장폐지', (today - dt.timedelta(days=90)).isoformat(), until)
    dl = [e for e in dl if e['name'] in by and not re.search(r'해제|이의|유예|사유 발생|심사', e['title'])]
    for e in dl: by[e['name']]['delisted'] = True
    spacs[:] = [s for s in spacs if not s.get('delisted')]
    return dict(approvals=len(appr), withdrawals=len(wdr), halts=len(halt), delisted=[e['name'] for e in dl])


def kind_listed_spacs():
    """KIND 코스닥 상장법인목록(별도 소스)에서 스팩 종목코드 집합을 만든다. KRX 목록과 교차검증용."""
    html = http('https://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13&marketType=kosdaqMkt',
                timeout=60).decode('euc-kr', 'replace')
    out = {}
    for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.S):
        tds = [re.sub(r'<[^>]+>|\s+', ' ', t).strip() for t in re.findall(r'<td[^>]*>(.*?)</td>', tr, re.S)]
        if len(tds) >= 3 and SPAC_NAME.search(tds[0]):
            code = next((t for t in tds if re.fullmatch(r'[0-9A-Z]{6}', t)), None)
            if code: out[code] = tds[0]
    return out


def cross_check(spacs, today, status, doc):
    """KRX 소속부 SPAC / KIND 상장법인목록 / 상장폐지 공시 / 대시보드 목록을 서로 대조한다."""
    cc = dict(checkedAt=dt.datetime.now(KST).isoformat(timespec='seconds'), tracked=len(spacs))
    mine = {s['code'] for s in spacs}
    krx_codes = set(status.get('krx', {}).get('_codes') or [])
    if krx_codes:
        cc.update(krx=len(krx_codes), krxBySection=status['krx'].get('bySection'),
                  krxByNameOnly=status['krx'].get('byNameOnly'),
                  missingInDashboard=sorted(krx_codes - mine), notInKrx=sorted(mine - krx_codes))
    try:
        kl = kind_listed_spacs()
        cc.update(kind=len(kl))
        if krx_codes:
            cc.update(onlyInKrx=sorted(krx_codes - set(kl)), onlyInKind={c: kl[c] for c in set(kl) - krx_codes})
    except Exception as e:  # noqa
        cc['kindError'] = str(e)[:200]
    try:   # 상장폐지 공시가 있는데 아직 목록에 남은 종목(확인 필요)
        dl = kind_search('상장폐지', (today - dt.timedelta(days=60)).isoformat(), today.isoformat())
        by = {s['name']: s['code'] for s in spacs}
        cc['delistNotices'] = sorted({e['name'] for e in dl if e['name'] in by and '상장폐지' in e['title']})
    except Exception as e:  # noqa
        cc['delistError'] = str(e)[:200]
    n = status.get('naver', {})
    if n.get('ok'): cc['priceDiff'] = n.get('priceDiff', [])
    doc['crossCheck'] = cc
    for k in ('krx',):                     # 내부용 키는 상태에서 제거
        status.get(k, {}).pop('_codes', None)


# ------------------------------------------------------------------ 3) DART
DART = 'https://opendart.fss.or.kr/api'
RATE_RE = re.compile(r'(?:이자율|이율|금리)[^0-9%]{0,40}(?:연\s*)?(\d{1,2}(?:\.\d{1,4})?)\s*%')
AMT_RE = re.compile(r'공모(?:금액|총액)[^0-9]{0,20}([\d,]{6,})\s*원')
SHR_RE = re.compile(r'(?:공모\s*주식수|모집\(매출\)\s*총액|모집주식수)[^0-9]{0,20}([\d,]{5,})\s*주')
PRICE_RE = re.compile(r'(?:발행가액|공모가)[^0-9]{0,20}([\d,]{3,6})\s*원')
RATIO_RE = re.compile(r'(?:예치|신탁)\s*비율[^0-9]{0,20}(\d{2,3}(?:\.\d+)?)\s*%')


def dart_corp_codes(key):
    z = zipfile.ZipFile(io.BytesIO(http(f'{DART}/corpCode.xml?crtfc_key={key}', timeout=90)))
    root = ET.fromstring(z.read(z.namelist()[0]))
    return {(c.findtext('stock_code') or '').strip(): c.findtext('corp_code')
            for c in root.iter('list') if (c.findtext('stock_code') or '').strip()}


def dart_list(key, corp, since):
    q = urllib.parse.urlencode(dict(crtfc_key=key, corp_code=corp, bgn_de=since, page_count=100))
    j = json.loads(http(f'{DART}/list.json?{q}').decode())
    return j.get('list', []) if j.get('status') == '000' else []


def dart_text(key, rcept):
    z = zipfile.ZipFile(io.BytesIO(http(f'{DART}/document.xml?crtfc_key={key}&rcept_no={rcept}', timeout=90)))
    raw = b''.join(z.read(n) for n in z.namelist())
    return re.sub(r'<[^>]+>|&[a-z#0-9]+;|\s+', ' ', raw.decode('utf-8', 'replace'))


def update_dart(spacs, today, key, only_incomplete=False):
    codes = dart_corp_codes(key)
    since = (today - dt.timedelta(days=1200)).strftime('%Y%m%d')
    n_ok, errs = 0, []
    for s in spacs:
        corp = codes.get(s['code'])
        if not corp: continue
        has_all = s.get('offerAmount') and s.get('shares') and s['rates'][0] is not None
        if only_incomplete and has_all and not s.get('isNew'): continue
        try:
            items = dart_list(key, corp, since)
            src = s.setdefault('sources', {})
            # 투자설명서/증권신고서 -> 공모금·주식수·공모가·예치비율·1년차 이자율
            ipo = [i for i in items if re.search(r'투자설명서|증권신고서', i['report_nm'])]
            if ipo and (s.get('isNew') or not s.get('offerAmount')):
                t = dart_text(key, sorted(ipo, key=lambda i: i['rcept_dt'])[-1]['rcept_no'])
                m = AMT_RE.search(t); a = num(m.group(1)) if m else None
                m = SHR_RE.search(t); sh = num(m.group(1)) if m else None
                m = PRICE_RE.search(t); pr = num(m.group(1)) if m else None
                m = RATIO_RE.search(t); ra = num(m.group(1)) if m else None
                if a: s['offerAmount'] = a; src['offer'] = 'dart'
                if sh: s['shares'] = sh; src['shares'] = 'dart'
                if pr: s['ipoPrice'] = pr
                if ra: s['depositRatio'] = ra / 100
                m = RATE_RE.search(t)
                if m and s['rates'][0] is None:
                    s['rates'][0] = float(m.group(1)) / 100; src['rates'] = 'dart-prospectus'
                s['dartIpoUrl'] = 'https://dart.fss.or.kr/dsaf001/main.do?rcpNo=' + sorted(ipo, key=lambda i: i['rcept_dt'])[-1]['rcept_no']
            # 최근 분기/반기/사업보고서 -> 예치이자율(재예치 후 2·3년차)
            reg = sorted([i for i in items if re.search(r'(분기|반기|사업)보고서', i['report_nm'])],
                         key=lambda i: i['rcept_dt'])
            if reg and s.get('listDate'):
                t = dart_text(key, reg[-1]['rcept_no'])
                rates = [float(x) / 100 for x in RATE_RE.findall(t) if 0 < float(x) < 15]
                s['dartRateCandidates'] = sorted(set(rates))[:6]   # 사람이 검증하도록 후보만 저장
                s['dartRegUrl'] = 'https://dart.fss.or.kr/dsaf001/main.do?rcpNo=' + reg[-1]['rcept_no']
            n_ok += 1
        except Exception as e:  # noqa
            errs.append(f"{s['name']}: {e}")
    return dict(updated=n_ok, errors=errs[:10])


# ------------------------------------------------------------------ 4) 현재가 (네이버 -> 구글 -> KRX)
_KIS = {}
KIS_HOST = 'https://openapi.koreainvestment.com:9443'


def kis_prices(codes):
    """한국투자증권 Open API 현재가(국내주식 inquire-price). 환경변수 KIS_APP_KEY / KIS_APP_SECRET."""
    ak, sk = os.environ['KIS_APP_KEY'], os.environ['KIS_APP_SECRET']
    if 'tok' not in _KIS:
        j = json.loads(http(KIS_HOST + '/oauth2/tokenP', json.dumps(dict(grant_type='client_credentials', appkey=ak, appsecret=sk)).encode(),
                            {'Content-Type': 'application/json'}).decode())
        _KIS['tok'] = j['access_token']
    out = {}
    for c in codes:
        try:
            q = urllib.parse.urlencode(dict(FID_COND_MRKT_DIV_CODE='J', FID_INPUT_ISCD=c))
            j = json.loads(http(f'{KIS_HOST}/uapi/domestic-stock/v1/quotations/inquire-price?{q}',
                                headers={'authorization': 'Bearer ' + _KIS['tok'], 'appkey': ak, 'appsecret': sk,
                                         'tr_id': 'FHKST01010100', 'custtype': 'P'}).decode())
            p = num(j.get('output', {}).get('stck_prpr'))
            if p: out[c] = (p, 'KIS')
        except Exception as e: log('kis', c, e)
        time.sleep(0.08)      # 초당 호출 제한 여유
    if not out: raise RuntimeError('KIS 응답 없음')
    return out


def naver_poll(codes):
    """네이버 금융 실시간 폴링 API (한 번에 여러 종목). code -> (price, state)"""
    out = {}
    for i in range(0, len(codes), 40):
        q = ','.join(codes[i:i + 40])
        j = json.loads(http('https://polling.finance.naver.com/api/realtime?query=SERVICE_ITEM:' + q,
                            headers={'Referer': 'https://finance.naver.com/'}).decode('utf-8', 'replace'))
        for area in j['result']['areas']:
            for d in area['datas']:
                if d.get('nv'): out[d['cd']] = (float(d['nv']), d.get('ms'))
    return out


def naver_mobile(code):
    j = json.loads(http(f'https://m.stock.naver.com/api/stock/{code}/basic',
                        headers={'Referer': 'https://m.stock.naver.com/'}).decode('utf-8', 'replace'))
    p = num(j.get('closePrice'))
    if not p: raise ValueError('no price')
    return p


def google_quote(code):
    html = http(f'https://www.google.com/finance/quote/{code}:KOSDAQ?hl=ko',
                headers={'Accept-Language': 'ko-KR,ko;q=0.9'}).decode('utf-8', 'replace')
    m = re.search(r'data-last-price="([\d.,]+)"', html)
    if not m: raise ValueError('no price')
    return num(m.group(1))


def update_prices(spacs, now):
    """종목별로 네이버 실시간 -> 네이버 모바일 -> 구글 -> (이미 있는) KRX 종가 순으로 현재가를 채운다."""
    codes = [s['code'] for s in spacs]
    kis = {}
    if os.environ.get('KIS_APP_KEY') and os.environ.get('KIS_APP_SECRET'):
        try: kis = kis_prices(codes)
        except Exception as e: log('kis fail', e)
    try: bulk = naver_poll(codes)
    except Exception as e: bulk = {}; log('naver poll fail', e)
    cnt = dict(kis=0, naver=0, google=0, krx=0, kept=0, warn=[])
    for s in spacs:
        src = s.setdefault('sources', {}); p = None; how = None
        if s['code'] in kis: p, how = kis[s['code']][0], 'kis'
        if p is None and s['code'] in bulk: p, how = bulk[s['code']][0], 'naver'
        if p is None:
            try: p, how = naver_mobile(s['code']), 'naver'
            except Exception: pass
        if p is None:
            try: p, how = google_quote(s['code']), 'google'
            except Exception: pass
        if p is None and s.get('krxClose'): p, how = s['krxClose'], 'krx'
        if p:
            # 교차검증: KRX 종가와 30% 이상 차이나면 경고(상하한가 30%)
            k = s.get('krxClose')
            if k and abs(p - k) / k > 0.30: cnt['warn'].append(s['name'])
            s['price'] = p; src['price'] = how; s['priceAt'] = now.isoformat(timespec='seconds'); cnt[how] += 1
        else: cnt['kept'] += 1   # 기존 값 유지
    if not (cnt['kis'] or cnt['naver'] or cnt['google'] or cnt['krx']): raise RuntimeError('모든 시세 소스 실패')
    return cnt


# ------------------------------------------------------------------ main
def apply_overrides(spacs):
    if not os.path.exists(OVR): return 0
    ov = json.load(open(OVR, encoding='utf-8')); n = 0
    for s in spacs:
        for k, v in (ov.get(s['code']) or ov.get(s['name']) or {}).items():
            if k.startswith('_'): continue
            s[k] = v; s.setdefault('sources', {})[k] = 'override'; n += 1
    return n


def check():
    """연결 점검: python scripts/update_data.py --check"""
    now = dt.datetime.now(KST); e = os.environ
    def t(name, fn):
        try: r = fn(); print(f'[OK]   {name}: {r}')
        except KeyError as x: print(f'[SKIP] {name}: 환경변수 {x} 없음')
        except Exception as x: print(f'[FAIL] {name}: {str(x)[:160]}')
    t('KRX Open API (KRX_OPENAPI_KEY)', lambda: len(krx_openapi('dbms/MDC/STAT/standard/MDCSTAT01901')['OutBlock_1']) if e['KRX_OPENAPI_KEY'] else (_ for _ in ()).throw(KeyError('KRX_OPENAPI_KEY')) )
    t('KRX 데이터포털', lambda: len(json.loads(http(KRX_URL, dict(bld='dbms/MDC/STAT/standard/MDCSTAT01901', locale='ko_KR', mktId='KSQ', share='1', csvxls_isNo='false'), {'Referer': 'https://data.krx.co.kr/contents/MDC/MDI/mdiLoader'}).decode())['OutBlock_1']))
    t('DART Open API (DART_API_KEY)', lambda: json.loads(http(f"{DART}/list.json?crtfc_key={e['DART_API_KEY']}&bgn_de={now:%Y%m%d}&page_count=1").decode())['status'] + ' (000=정상)')
    t('KIS 증권사 API (KIS_APP_KEY/SECRET)', lambda: kis_prices(['005930']))
    t('네이버 실시간', lambda: naver_poll(['005930']))
    t('구글 금융', lambda: google_quote('005930'))
    t('KIND 공시', lambda: len(kind_search('상장예비심사결과통지(승인)', (now.date() - dt.timedelta(days=60)).isoformat(), now.date().isoformat())))


def main():
    global VERBOSE
    ap = argparse.ArgumentParser(); ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('-v', action='store_true'); ap.add_argument('--skip', default=''); ap.add_argument('--check', action='store_true')
    a = ap.parse_args(); VERBOSE = a.v
    if a.check: check(); return 0
    doc = json.load(open(DATA, encoding='utf-8')); spacs = doc['spacs']
    today = dt.datetime.now(KST).date(); skip = a.skip.split(',')
    status = {}
    steps = [('krx', lambda: update_krx(spacs, today)),
             ('kind', lambda: update_kind(spacs, today)),
             ('dart', lambda: update_dart(spacs, today, os.environ['DART_API_KEY'], only_incomplete=True)
                       if os.environ.get('DART_API_KEY') else (_ for _ in ()).throw(RuntimeError('DART_API_KEY 없음'))),
             ('price', lambda: update_prices(spacs, dt.datetime.now(KST)))]
    for name, fn in steps:
        if name in skip: continue
        try:
            status[name] = dict(ok=True, **fn()); krx_ok = krx_ok or (name == 'krx')
        except Exception as e:  # noqa
            status[name] = dict(ok=False, error=str(e)[:300]); log(name, 'FAIL', e)
    try: cross_check(spacs, today, status, doc)
    except Exception as e: log('cross_check FAIL', e)
    apply_overrides(spacs)
    now = dt.datetime.now(KST)
    if any(v.get('ok') for v in status.values()):
        doc['updatedAt'] = now.isoformat(timespec='seconds')
        if status.get('krx', {}).get('priceDate'): doc['priceDate'] = status['krx']['priceDate']
        if status.get('price', {}).get('ok') and (status['price'].get('kis') or status['price'].get('naver') or status['price'].get('google')):
            doc['priceDate'] = now.date().isoformat(); doc['priceAt'] = now.isoformat(timespec='seconds')
    k = status.get('krx', {})
    if k.get('ok'):
        mine = {s['code'] for s in spacs}
        doc['validation'] = dict(checkedAt=now.isoformat(timespec='seconds'), krxSpacListed=k['count'],
                                 krxTrading=k['tradingCount'], dashboard=len(mine),
                                 missing=sorted(set(k['codes']) - mine), extra=sorted(mine - set(k['codes'])),
                                 notTrading=k['notTrading'], matched=(mine == set(k['codes'])))
    k.pop('codes', None)
    doc['status'] = status; doc['checkedAt'] = now.isoformat(timespec='seconds')
    spacs.sort(key=lambda s: s['name'])
    log(json.dumps(status, ensure_ascii=False, indent=1))
    if not a.dry_run:
        json.dump(doc, open(DATA, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return 0 if any(v.get('ok') for v in status.values()) else 1


if __name__ == '__main__':
    sys.exit(main())
