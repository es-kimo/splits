"""R-26 공개 대상자 후보군 규모 산출.

데이터로 식별 가능한 성인 경쟁 선수 규모를 세어 리포트와 사이트 계약 JSON을 만든다.
실명은 출력하지 않는다. 규모와 분포만 낸다.
"""

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ATHLETE_INFO = Path("data/athlete_info_full.csv")
RECORDS_FULL = Path("data/records_full.csv")
PUBLIC_FIGURES = Path("data/public_figures.csv")

# 팀 단위 최소 노출 인원. 이보다 적은 팀은 '기타'로 합친다.
TEAM_MIN_SIZE = 3

# 실업팀 판정: 지자체팀 / 체육회 / 기업 빙상단 / 국군체육부대
PRO_TEAM_PATTERNS = [
    r"시청",
    r"도청",
    r"군청",
    r"구청",
    r"체육회",
    r"빙상단",
    r"스포츠토토",
    r"콜핑",
    r"국민은행",
    r"대한항공",
    r"알펜시아",
    r"롯데월드",
    r"국군체육부대",
    r"시설관리공단",
    r"오주건설",
]
# 실업팀이 아닌 것: 무소속(일반) / 시도연맹 등록 / 동호회·클럽 / 학교
NON_PRO_PATTERNS = [
    r"일반$",
    r"연맹",
    r"클럽",
    r"스포츠클럽",
    r"학교",
    r"대학",
    r"초등$",
    r"중학$",
    r"고등$",
]

PRO_RE = re.compile("|".join(PRO_TEAM_PATTERNS))
NON_PRO_RE = re.compile("|".join(NON_PRO_PATTERNS))


def is_pro_team(name):
    if not isinstance(name, str):
        return False
    text = name.strip()
    if not text:
        return False
    if NON_PRO_RE.search(text) and not PRO_RE.search(text):
        return False
    return bool(PRO_RE.search(text))


def read_csv(path, **kwargs):
    frame = pd.read_csv(path, dtype=str, **kwargs)
    frame.columns = [c.strip("﻿") for c in frame.columns]
    return frame


def build(as_of_year, active_since):
    athletes = read_csv(ATHLETE_INFO)
    records = read_csv(RECORDS_FULL, low_memory=False)

    records["일자_정규화"] = pd.to_datetime(records["일자_정규화"], errors="coerce")
    records["연도"] = records["일자_정규화"].dt.year

    grouped = records.groupby("idNo")["연도"]
    summary = pd.DataFrame(
        {
            "첫출전연도": grouped.min(),
            "마지막출전연도": grouped.max(),
            "기록수": records.groupby("idNo").size(),
        }
    )

    pro_mask = records["소속"].map(is_pro_team)
    summary["실업팀기록수"] = records.loc[pro_mask].groupby("idNo").size()

    df = athletes.set_index("idNo").join(summary)
    df["실업팀기록수"] = df["실업팀기록수"].fillna(0).astype(int)
    df["기록수"] = df["기록수"].fillna(0).astype(int)
    df["출생년도"] = pd.to_numeric(df["출생년도"], errors="coerce")
    df["만나이"] = as_of_year - df["출생년도"]

    df["현재실업등록"] = (df["종별"] == "실업(일반)") & df["소속팀"].map(is_pro_team)
    df["실업팀이력"] = df["실업팀기록수"] > 0
    df["성인"] = (df["만나이"] >= 18).fillna(False)
    df["최근활동"] = (df["마지막출전연도"] >= active_since).fillna(False)

    public = read_csv(PUBLIC_FIGURES)
    public_ids = set(public.loc[public["상태"] == "active", "idNo"])
    df["공인국가대표"] = df.index.isin(public_ids)

    df["후보"] = df["현재실업등록"] | df["실업팀이력"] | df["공인국가대표"]
    df["최종후보"] = df["후보"] & df["성인"] & df["최근활동"]
    return df, records


def team_breakdown(target):
    counts = target.loc[target["소속팀"].map(is_pro_team), "소속팀"].value_counts()
    named = counts[counts >= TEAM_MIN_SIZE]
    rest = int(counts[counts < TEAM_MIN_SIZE].sum())
    rows = [{"team": str(k), "count": int(v)} for k, v in named.items()]
    if rest:
        rows.append({"team": f"그 외 소규모 팀({TEAM_MIN_SIZE}명 미만)", "count": rest})
    return rows


def race_bins(target):
    bins = [(0, 49), (50, 99), (100, 199), (200, 499), (500, None)]
    rows = []
    for low, high in bins:
        if high is None:
            mask = target["기록수"] >= low
            label = f"{low}건 이상"
        else:
            mask = (target["기록수"] >= low) & (target["기록수"] <= high)
            label = f"{low}~{high}건"
        rows.append({"label": label, "count": int(mask.sum())})
    return rows


def sensitivity(df, as_of_year, years):
    rows = []
    for year in years:
        mask = df["후보"] & df["성인"] & (df["마지막출전연도"] >= year).fillna(False)
        rows.append({"since": int(year), "count": int(mask.sum())})
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of-year", type=int, default=2026)
    parser.add_argument("--active-since", type=int, default=2021)
    parser.add_argument("--out", type=Path, default=Path("out/public_candidates.md"))
    parser.add_argument("--json-out", type=Path, default=Path("site/data/candidates.json"))
    args = parser.parse_args()

    df, records = build(args.as_of_year, args.active_since)
    target = df.loc[df["최종후보"]]

    years = sorted(records["연도"].dropna().unique())
    doc = {
        "generatedAt": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "asOfYear": args.as_of_year,
        "activeSince": args.active_since,
        "totals": {
            "allAthletes": int(len(df)),
            "currentProRegistered": int(df["현재실업등록"].sum()),
            "everPro": int(df["실업팀이력"].sum()),
            "nationalTeam": int(df["공인국가대표"].sum()),
            "candidatePool": int(df["후보"].sum()),
            "activePool": int(len(target)),
        },
        "gender": [{"label": str(k), "count": int(v)} for k, v in target["성별"].value_counts().items()],
        "birthYear": {"min": int(target["출생년도"].min()), "max": int(target["출생년도"].max())},
        "raceCount": {
            "median": int(target["기록수"].median()),
            "min": int(target["기록수"].min()),
            "max": int(target["기록수"].max()),
            "bins": race_bins(target),
        },
        "teams": team_breakdown(target),
        "sensitivity": sensitivity(df, args.as_of_year, [2017, 2019, 2021, 2023, 2025]),
        "dataRange": {
            "yearStart": int(min(years)),
            "yearEnd": int(max(years)),
            "recordCount": int(len(records)),
        },
    }

    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = []

    def emit(text=""):
        print(text)
        lines.append(text)

    t = doc["totals"]
    emit("# R-26 공개 대상자 후보군 규모")
    emit()
    emit(f"- 기준 연도: {args.as_of_year}년 (만나이 계산 기준)")
    emit(f"- 최근 활동 기준: {args.active_since}년 이후 출전 기록")
    emit(f"- 전체 선수: {t['allAthletes']:,}명")
    emit()
    emit("## 경로별 후보군")
    emit()
    emit("| 경로 | 인원 |")
    emit("| --- | ---: |")
    emit(f"| 현재 실업팀 등록 | {t['currentProRegistered']:,} |")
    emit(f"| 실업팀 출전 이력(역대) | {t['everPro']:,} |")
    emit(f"| 공인 국가대표 | {t['nationalTeam']:,} |")
    emit(f"| 합집합 | {t['candidatePool']:,} |")
    emit(f"| **합집합 + 성인 + 최근활동** | **{t['activePool']:,}** |")
    emit()
    emit("## 최근 활동 기준 민감도")
    emit()
    emit("| 기준 연도 이후 출전 | 인원 |")
    emit("| --- | ---: |")
    for row in doc["sensitivity"]:
        emit(f"| {row['since']}년 | {row['count']:,} |")
    emit()
    emit("## 최종 후보군 프로필")
    emit()
    emit("- 성별: " + ", ".join(f"{g['label']} {g['count']}명" for g in doc["gender"]))
    emit(f"- 출생연도: {doc['birthYear']['min']}~{doc['birthYear']['max']}년")
    emit(
        f"- 1인당 기록 수: 중앙값 {doc['raceCount']['median']}건, "
        f"최소 {doc['raceCount']['min']}건, 최대 {doc['raceCount']['max']}건"
    )
    emit()
    emit("| 소속팀 | 인원 |")
    emit("| --- | ---: |")
    for row in doc["teams"]:
        emit(f"| {row['team']} | {row['count']:,} |")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print()
    print(f"[ok] {args.out}")
    print(f"[ok] {args.json_out}")


if __name__ == "__main__":
    main()
