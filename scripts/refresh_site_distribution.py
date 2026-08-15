#!/usr/bin/env python3
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from build_data import build_distribution

DATA_DIR = Path("data")
SITE_DATA_DIR = Path("site/data")
STATS_DISTRIBUTION_CSV = DATA_DIR / "stats_distribution.csv"
DISTRIBUTION_JSON = SITE_DATA_DIR / "distribution.json"
META_JSON = SITE_DATA_DIR / "meta.json"


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    if not STATS_DISTRIBUTION_CSV.exists():
        raise FileNotFoundError(f"[error] 파일이 없습니다: {STATS_DISTRIBUTION_CSV}")
    if not META_JSON.exists():
        raise FileNotFoundError(f"[error] 파일이 없습니다: {META_JSON}")

    frame = pd.read_csv(STATS_DISTRIBUTION_CSV, dtype=str, encoding="utf-8-sig").fillna("")
    distribution = build_distribution(frame)
    _write_json(DISTRIBUTION_JSON, distribution)

    meta = json.loads(META_JSON.read_text(encoding="utf-8"))
    meta["generatedAt"] = date.today().isoformat()
    _write_json(META_JSON, meta)

    print(f"[ok] 생성 완료: {DISTRIBUTION_JSON}")
    print(f"[ok] 갱신 완료: {META_JSON}")


if __name__ == "__main__":
    main()
