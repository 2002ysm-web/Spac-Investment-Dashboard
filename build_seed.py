import os
import sys
import json
from datetime import datetime as dt

def main(mode1="check", mode2="auto"):
    print(f"[Info] Starting build_seed.py with modes: {mode1}, {mode2}")
    
    spac_data = {
        "updated_at": dt.now().strftime("%Y-%m-%d %H:%M:%S"),
        "items": []
    }
    
    os.makedirs("data", exist_ok=True)
    output_path = "data/spacs.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(spac_data, f, ensure_ascii=False, indent=2)
        
    print(f"[Info] Successfully updated {output_path}.")

if __name__ == '__main__':
    mode1 = sys.argv[1] if len(sys.argv) > 1 else "check"
    mode2 = sys.argv[2] if len(sys.argv) > 2 else "auto"
    main(mode1, mode2)
