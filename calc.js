/* 스팩 투자 판단 산식 (엑셀 '총괄표' 수식과 동일). 브라우저/Node 공용 */
(function (root) {
  var DAY = 86400000;
  var NET = 0.845;      // 예치이자 세후계수 (배당소득세14%+지방소득세1.4%+수수료0.1% 제외)
  var TAX_GEN = 0.846;  // 일반계좌 매매차익 세후계수 (세금 15.4% 제외)

  function utc(s) { var p = s.split('-'); return Date.UTC(+p[0], +p[1] - 1, +p[2]); }
  function iso(ms) { return new Date(ms).toISOString().slice(0, 10); }
  function todayKST(now) { // 'YYYY-MM-DD' (한국 표준시)
    return new Date((now || Date.now()) + 9 * 3600 * 1000).toISOString().slice(0, 10);
  }
  function has(x) { return x !== null && x !== undefined && x !== '' && !isNaN(x); }

  function compute(s, todayStr) {
    var out = { code: s.code, name: s.name };
    var ok = has(s.price) && has(s.ipoPrice) && has(s.offerAmount) && has(s.shares) && s.shares > 0 &&
             s.listDate && s.rates && has(s.rates[0]);
    out.complete = !!ok;
    if (!s.listDate) return out;
    var today = utc(todayStr), list = utc(s.listDate);
    var delist = list + 1095 * DAY;                         // 상장폐지일 = 상장일 + 365*3
    out.delistDate = iso(delist);
    out.daysLeft = Math.round((delist - today) / DAY);
    out.type = out.daysLeft < 365 ? '청산' : '합병';        // 1년 이상 남으면 합병
    if (!ok) return out;

    var r1 = +s.rates[0];
    var r2 = has(s.rates[1]) ? +s.rates[1] : r1;
    var r3 = has(s.rates[2]) ? +s.rates[2] : r2;
    var ratio = has(s.depositRatio) ? +s.depositRatio : 1;
    var y1 = s.offerAmount * ratio * (1 + r1 * NET);        // 1년차 말
    var y2 = y1 * (1 + r2 * NET);                           // 2년차 말
    var fin = y2 * (1 + r3 * NET * 6 / 12);                 // 3년차: 6개월 예치(보수적)
    var liq = fin / s.shares;                               // 최종 청산단가
    out.liq = liq;

    var span = (delist + 30 * DAY - today) / DAY * 1;       // 상장폐지일+30-오늘
    if (span > 0) {
      var gain = (liq - s.price) / s.price;
      out.yieldISA = gain / span * 365;
      out.yieldGen = (liq - s.price) * TAX_GEN / s.price / span * 365;
    } else { out.yieldISA = null; out.yieldGen = null; }

    var elapsed = (today - list) / DAY;
    out.fairPrice = s.ipoPrice + (liq - s.ipoPrice) / 1095 * elapsed;   // 매수적정가
    out.buyOK = out.fairPrice >= s.price;

    // 합병 승인 후 철회가 없거나 철회가 승인보다 앞서면 '합병 진행'
    var a = s.mergerApprovedAt, w = s.mergerWithdrawnAt;
    out.mergerActive = !!a && (!w || w < a);
    return out;
  }
  var api = { compute: compute, todayKST: todayKST, NET: NET, TAX_GEN: TAX_GEN };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.SpacCalc = api;
})(typeof window !== 'undefined' ? window : globalThis);
