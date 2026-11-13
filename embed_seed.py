#!/usr/bin/env python3
"""data/spac.json 을 index.html 의 내장 시드(<script id="seed">)에 복사한다.
file:// 로 직접 열었을 때도 최신 데이터가 보이도록 하는 용도. update_data.py 가 끝에 자동 호출한다."""
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def embed(root=ROOT):
    data = json.loads((root / "data" / "spac.json").read_text(encoding="utf-8"))
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    html = (root / "index.html").read_text(encoding="utf-8")
    pat = re.compile(r'(<script type="application/json" id="seed">)(.*?)(</script>)', re.S)
    if not pat.search(html):
        sys.exit("index.html 에 seed 블록이 없습니다")
    html = pat.sub(lambda m: m.group(1) + blob + m.group(3), html, count=1)
    (root / "index.html").write_text(html, encoding="utf-8")
    return len(data["spacs"])


if __name__ == "__main__":
    print(f"seed 내장 완료: {embed()}종목")
