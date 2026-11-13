// 엑셀 캐시 값(2026-11-12 기준)과 calc.js 결과를 전 종목 대조
const fs=require('fs'); const C=require('../calc.js');
const seed=JSON.parse(fs.readFileSync('data/spacs.json','utf8')).spacs;
const xl=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
let bad=0;
for(const s of seed){
  const r=C.compute(s,'2026-11-12'), e=xl[s.name];
  const chk=[['liq',r.liq,e.liq],['isa',r.yieldISA,e.isa],['gen',r.yieldGen,e.gen]];
  for(const [k,a,b] of chk) if(Math.abs(a-b)>1e-6){bad++;console.log('DIFF',s.name,k,a,b);}
  if(r.type!==e.type){bad++;console.log('TYPE',s.name,r.type,e.type);}
  if(e.buy.trim()!=='' && (r.buyOK?'O':'X')!==e.buy){bad++;console.log('BUY',s.name,r.buyOK,e.buy);}
  if(e.buy.trim()==='') console.log('엑셀 공란(산식상 '+(r.buyOK?'O':'X')+'):',s.name);
}
console.log(seed.length+'종목 대조, 불일치 '+bad);
