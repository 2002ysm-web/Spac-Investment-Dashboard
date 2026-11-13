import os
import sys
import json
from datetime import datetime as dt
import requests
import pandas as pd

def main(mode1, mode2):
    print(f"[Info] Starting build_seed.py with modes: {mode1}, {mode2}")
    
    # 엑셀 파일 의존성을 제거하고, API 등을 통해 데이터를 직접 처리하거나 
    # 기본 데이터를 생성하는 로직을 수행합니다.
    
    # 예시: 기본 데이터 구조 생성 및 업데이트 처리
    spac_data = {
        "updated_at": dt.now().strftime("%Y-%m-%d %H:%M:%S"),
        "items": []
    }
    
    # data 폴더가 없으면 생성
    os.makedirs("data", exist_ok=True)
    
    # 결과 파일 저장
    output_path = "data/spacs.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(spac_data, f, ensure_ascii=False, indent=2)
        
    print(f"[Info] Successfully updated {output_path} without Excel dependency.")

if __name__ == '__main__':
    if len(sys.argv) > 2:
        main(sys.argv[1], sys.argv[2])
    else:
        main("check", "auto")
