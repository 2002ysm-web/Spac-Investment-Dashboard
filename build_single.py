"""index.html + calc.js + data/spacs.json -> 단일 HTML (dist/spac-dashboard.html)"""
import json, os
R=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
h=open(f'{R}/index.html',encoding='utf-8').read()
h=h.replace('<script src="calc.js"></script>','<script>'+open(f'{R}/calc.js',encoding='utf-8').read()+'</script>')
seed=json.dumps(json.load(open(f'{R}/data/spacs.json',encoding='utf-8')),ensure_ascii=False,separators=(',',':')).replace('</','<\\/')
h=h.replace('<script type="application/json" id="seed">null</script>','<script type="application/json" id="seed">'+seed+'</script>')
os.makedirs(f'{R}/dist',exist_ok=True); open(f'{R}/dist/spac-dashboard.html','w',encoding='utf-8').write(h); print(len(h))
