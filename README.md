# 스팩 투자 대시보드

정적 사이트(`index.html` + `calc.js` + `data/spacs.json`)와 자동 수집기(`scripts/update_data.py`)로 구성됩니다.

## 배포 (GitHub Pages 권장)
1. 이 폴더를 GitHub 저장소로 올리고 Settings > Pages 에서 main 브랜치 루트를 게시
2. Settings > Secrets 에 `DART_API_KEY`(https://opendart.fss.or.kr 에서 무료 발급) 등록
   KRX 데이터포털이 로그인 세션을 요구하면 `KRX_COOKIE`(브라우저 쿠키 문자열)도 등록
3. Actions 탭에서 `update-spac-data` 를 한 번 수동 실행(workflow_dispatch)해 상태 확인
   이후 평일 09:00 / 16:10 KST 자동 실행 → `data/spacs.json` 커밋 → 페이지가 즉시 새 데이터 표시

## 수집 소스 → 필드
| 소스 | 필드 |
|---|---|
| KRX 정보데이터시스템 | 소속부 SPAC 전종목(신규 상장 자동 추가), 상장일, 상장주식수, 종가(현재가) |
| KIND 공시 | 합병 승인(상장예비심사 승인), 합병결정 철회, 거래정지/해제 |
| OpenDART | 공모금, 공모주식수, 공모가, 예치비율, 예치이자율(투자설명서·정기보고서) |
| 네이버 증권 | 현재가 보조(KRX 시세 실패 시), 종목 링크 |

- 자동 수집값보다 `data/overrides.json` 의 수동 보정이 항상 우선합니다.
- 예치이자율은 공시 문서에서 정규식으로 후보를 찾는 방식이라 `dartRateCandidates` 를 표의 행 펼침에서 확인하고, 틀리면 overrides 로 고정하세요.
- 로컬 확인: `python scripts/update_data.py --dry-run -v`

## 검증
- `node scripts/verify_calc.js <엑셀값.json>` : 엑셀 수식 결과와 72종목 대조(불일치 0)
- `python scripts/test_parsers.py` : 파서 단위 테스트(가정한 응답 형식 기준)

## 현재가 / 상장폐지 / 교차검증 규칙
- 현재가: 네이버 금융 실시간 → 네이버 모바일 → 구글 금융 → KRX 종가 순. 종목별 출처와 시각이 행 펼침에 표시되고, KRX 종가와 30% 넘게 다르면 경고로 기록
- 상장폐지: KRX 코스닥 목록에서 사라진 종목, KIND 상장폐지 공시 종목, 상장폐지일+30일이 지난 종목은 표에서 제외
- 교차검증: KRX 소속부 SPAC(+이름에 스팩/기업인수목적 포함) 목록과 대시보드 종목을 매 실행마다 대조해 누락 추가·초과 제거, 결과(`validation`)를 화면 상단에 표시
- 갱신 주기: 장중 10분마다(GitHub Actions 최소 간격 한계로 몇 분 지연될 수 있음) + 16:30 종가. 열려 있는 화면은 1분마다 `data/spacs.json` 을 다시 읽음
