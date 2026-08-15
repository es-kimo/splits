#!/usr/bin/env python3
"""data/records_anon.csv에 classCd 컬럼을 채우고 출생년도 컬럼명을 출생연도로 통일한다.

익명키를 다시 만들지 않는다. 익명화 솔트가 없는 환경에서도 안전하게 재실행할 수 있도록
기존 행을 그대로 두고 컬럼만 추가·정리한다. 스피드스케이팅 행은 삭제하지 않고 classCd로 표시만 한다.
"""
import sys
from pathlib import Path

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from analyze import RECORDS_ANON_REQUIRED_COLUMNS, SHORTTRACK_CLASS_CD, classify_class_cd

RECORDS_ANON_CSV = Path("data/records_anon.csv")


def backfill(frame):
    out = frame.copy()
    if "출생년도" in out.columns and "출생연도" not in out.columns:
        out = out.rename(columns={"출생년도": "출생연도"})
    out["classCd"] = [
        classify_class_cd(meet, round_name, round_kind)
        for meet, round_name, round_kind in zip(out["대회명"], out["라운드"], out["라운드종류"])
    ]
    missing = [name for name in RECORDS_ANON_REQUIRED_COLUMNS if name not in out.columns]
    if missing:
        raise ValueError(f"[error] {RECORDS_ANON_CSV} 필수 컬럼이 없습니다: {', '.join(missing)}")
    return out[RECORDS_ANON_REQUIRED_COLUMNS]


def main():
    if not RECORDS_ANON_CSV.exists():
        raise FileNotFoundError(f"[error] 파일이 없습니다: {RECORDS_ANON_CSV}")
    frame = pd.read_csv(RECORDS_ANON_CSV, dtype=str, encoding="utf-8-sig").fillna("")
    out = backfill(frame)
    out.to_csv(RECORDS_ANON_CSV, index=False, encoding="utf-8-sig")

    counts = out["classCd"].value_counts().to_dict()
    shorttrack = int(counts.get(SHORTTRACK_CLASS_CD, 0))
    print(f"[ok] 갱신 완료: {RECORDS_ANON_CSV} ({len(out)}행)")
    print(f"[ok] classCd 분포: {counts}")
    print(f"[ok] 통계 집계 대상(classCd=2): {shorttrack}행 / 제외 {len(out) - shorttrack}행")


if __name__ == "__main__":
    main()
