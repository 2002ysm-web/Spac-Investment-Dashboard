import os
import sys
import json
from datetime import datetime as dt
import requests
import pandas as pd

def main(mode1, mode2):
    print(f"[Info] Starting build_seed.py with modes: {mode1}, {mode2}")
    
    # SPAC 투자 데이터 처리 및 API 연동 로직이 들어갈 자리입니다.
    spac_data = {
        "updated_at": dt.now().strftime("%Y-%m-%d %H:%M:%S"),
        "items": []
    }
    
    # data 폴더 생성 및 결과 JSON 저장
    os.makedirs("data", exist_ok=True)
    output_path = "data/spacs.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(spac_data, f, ensure_ascii=False, indent=2)
        
    print(f"[Info] Successfully updated {output_path}.")

if __name__ == '__main__':
    # 인자가 부족해도 에러가 나지 않도록 안전하게 기본값 처리
    mode1 = sys.argv[1] if len(sys.argv) > 1 else "check"
    mode2 = sys.argv[2] if len(sys.argv) > 2 else "auto"
    main(mode1, mode2)
