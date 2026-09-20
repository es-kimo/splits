"""공인 선수 레이팅 순위표(site/data/ranking.json)를 만든다.

남녀는 맞대결이 없어 mu가 서로 비교되지 않는다(R-01 연결성 리포트).
따라서 순위는 반드시 성별로 나눠서 낸다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from local_env import load_local_env

SEX_LABELS = {"여": "여자", "남": "남자"}


def opaque(id_no: str, salt: str) -> str:
    return hashlib.sha256(f"{id_no}{salt}".encode("utf-8")).hexdigest()[:12]


def read_csv(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype=str)
    frame.columns = [c.strip("﻿") for c in frame.columns]
    return frame


def latest_snapshots(registry: Path, run_id: str) -> pd.DataFrame:
    with sqlite3.connect(f"file:{registry}?mode=ro", uri=True) as connection:
        frame = pd.read_sql(
            "SELECT athlete_id, valid_date, mu, sigma, n_games FROM rating_snapshot WHERE run_id = ?",
            connection,
            params=(run_id,),
        )
    return frame.sort_values("valid_date").groupby("athlete_id", as_index=False).tail(1)


def pinned_run(registry: Path) -> tuple[str, str]:
    with sqlite3.connect(f"file:{registry}?mode=ro", uri=True) as connection:
        row = connection.execute(
            "SELECT run_id, algo_version FROM rating_run WHERE status = 'complete' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    if row is None:
        raise SystemExit("[error] 완료된 레이팅 실행이 없습니다.")
    return str(row[0]), str(row[1])


def main() -> None:
    load_local_env()
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, default=Path("out/rating_runs/registry.sqlite"))
    parser.add_argument("--athletes", type=Path, default=Path("site/data/athletes.json"))
    parser.add_argument("--athlete-info", type=Path, default=Path("data/athlete_info_full.csv"))
    parser.add_argument("--out", type=Path, default=Path("site/data/ranking.json"))
    parser.add_argument("--run-id")
    args = parser.parse_args()

    salt = os.environ.get("SPLITS_ANON_SALT", "").strip()
    if not salt:
        raise SystemExit("[error] SPLITS_ANON_SALT가 필요합니다.")

    run_id, algo_version = pinned_run(args.registry)
    if args.run_id:
        run_id = args.run_id

    snapshots = latest_snapshots(args.registry, run_id)
    info = read_csv(args.athlete_info)
    info["athlete_id"] = info["idNo"].map(lambda x: opaque(x, salt))

    population = snapshots.merge(info[["athlete_id", "성별"]], on="athlete_id", how="left")
    public = json.loads(args.athletes.read_text(encoding="utf-8"))["athletes"]

    groups = []
    for sex, label in SEX_LABELS.items():
        pool = population.loc[population["성별"] == sex, "mu"]
        members = []
        for athlete in public:
            if athlete.get("gender") != sex:
                continue
            row = snapshots.loc[snapshots["athlete_id"] == opaque(athlete["idNo"], salt)]
            if row.empty:
                continue
            record = row.iloc[0]
            mu = float(record["mu"])
            members.append(
                {
                    "name": athlete["name"],
                    "slug": athlete["slug"],
                    "url": athlete["url"],
                    "birth": athlete.get("birth"),
                    "team": athlete.get("team") or "",
                    "mu": round(mu, 1),
                    "sigma": round(float(record["sigma"]), 1),
                    "games": int(record["n_games"]),
                    "topPercent": round(float((pool >= mu).mean() * 100), 2),
                    "asOf": str(record["valid_date"]),
                }
            )
        members.sort(key=lambda item: item["mu"], reverse=True)
        for index, member in enumerate(members, start=1):
            member["rank"] = index
        groups.append(
            {
                "sex": sex,
                "label": label,
                "populationSize": int(pool.notna().sum()),
                "athletes": members,
            }
        )

    doc = {
        "generatedAt": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "runId": run_id,
        "algoVersion": algo_version,
        "asOf": max((m["asOf"] for g in groups for m in g["athletes"]), default=""),
        "groups": groups,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    total = sum(len(g["athletes"]) for g in groups)
    print(f"[ok] {args.out} — run {run_id} ({algo_version}), {total}명")
    for group in groups:
        print(f"  {group['label']}: {len(group['athletes'])}명 / 모집단 {group['populationSize']}명")


if __name__ == "__main__":
    main()
