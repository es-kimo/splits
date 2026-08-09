import json
import re
from datetime import date
from pathlib import Path

import pandas as pd

DATA_DIR = Path("data")
SITE_DATA_DIR = Path("site/data")
ATHLETES_JSON = SITE_DATA_DIR / "athletes.json"
MEETS_JSON = SITE_DATA_DIR / "meets.json"
DISTRIBUTION_JSON = SITE_DATA_DIR / "distribution.json"
META_JSON = SITE_DATA_DIR / "meta.json"
INPUT_FILES = [
    "placements.csv",
    "youth_summary.csv",
    "age_matrix.csv",
    "athlete_info.csv",
    "coverage.csv",
    "public_figures.csv",
]
AGES = [str(age) for age in range(7, 19)]
PUBLIC_FIGURES_REQUIRED_COLUMNS = ["idNo", "이름", "슬러그", "출생연도", "지정근거", "언론보도URL", "지정일자", "상태"]
PUBLIC_FIGURES_ALLOWED_STATUS = {"active", "removed"}
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
K_ANONYMITY_MIN = 10


def as_int(value):
    text = str(value or "").strip()
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else None


def as_id(value):
    return str(value or "").strip()


def as_bool(value):
    return str(value or "").strip().lower() in {"true", "1", "y", "yes", "t"}


def rank_band_text(rank):
    if rank is None:
        return "-"
    if rank < 10:
        return "한 자리수"
    return f"{(rank // 10) * 10}등대"


def read_csv(name):
    path = DATA_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"[error] 파일이 없습니다: {path}")
    return pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_public_figures(frame):
    missing_columns = [column for column in PUBLIC_FIGURES_REQUIRED_COLUMNS if column not in frame.columns]
    if missing_columns:
        missing_text = ", ".join(missing_columns)
        raise ValueError(f"[error] data/public_figures.csv 필수 컬럼이 없습니다: {missing_text}")

    rows = []
    seen_ids = set()
    seen_slugs = set()
    for idx, row in frame.iterrows():
        row_no = idx + 2
        id_no = as_id(row.get("idNo", ""))
        name = str(row.get("이름", "")).strip()
        slug = str(row.get("슬러그", "")).strip().lower()
        birth = as_int(row.get("출생연도", ""))
        reason = str(row.get("지정근거", "")).strip()
        media_url = str(row.get("언론보도URL", "")).strip()
        designated_at = str(row.get("지정일자", "")).strip()
        status = str(row.get("상태", "")).strip().lower()

        if not id_no:
            raise ValueError(f"[error] data/public_figures.csv {row_no}행 idNo 값이 비어 있습니다.")
        if not name:
            raise ValueError(f"[error] data/public_figures.csv {row_no}행 이름 값이 비어 있습니다.")
        if not slug:
            raise ValueError(f"[error] data/public_figures.csv {row_no}행 슬러그 값이 비어 있습니다.")
        if not SLUG_RE.fullmatch(slug):
            raise ValueError(f"[error] data/public_figures.csv {row_no}행 슬러그 형식이 올바르지 않습니다: {slug}")
        if birth is None:
            raise ValueError(f"[error] data/public_figures.csv {row_no}행 출생연도 값이 올바르지 않습니다.")
        if not reason:
            raise ValueError(f"[error] data/public_figures.csv {row_no}행 지정근거 값이 비어 있습니다.")
        if not media_url or not media_url.startswith(("http://", "https://")):
            raise ValueError(f"[error] data/public_figures.csv {row_no}행 언론보도URL 값이 올바르지 않습니다.")
        if not designated_at:
            raise ValueError(f"[error] data/public_figures.csv {row_no}행 지정일자 값이 비어 있습니다.")
        if status not in PUBLIC_FIGURES_ALLOWED_STATUS:
            raise ValueError(f"[error] data/public_figures.csv {row_no}행 상태 값이 올바르지 않습니다: {status}")
        if id_no in seen_ids:
            raise ValueError(f"[error] data/public_figures.csv idNo 중복이 있습니다: {id_no}")
        if slug in seen_slugs:
            raise ValueError(f"[error] data/public_figures.csv 슬러그 중복이 있습니다: {slug}")

        seen_ids.add(id_no)
        seen_slugs.add(slug)
        rows.append(
            {
                "idNo": id_no,
                "name": name,
                "slug": slug,
                "birth": birth,
                "designationReason": reason,
                "mediaReportUrl": media_url,
                "designatedAt": designated_at,
                "status": status,
            }
        )

    if not rows:
        raise ValueError("[error] data/public_figures.csv에 명단 행이 없습니다.")
    return rows


def build_athletes_payload(frames):
    placements = frames["placements.csv"]
    summary = frames["youth_summary.csv"]
    matrix = frames["age_matrix.csv"]
    athlete_info = frames["athlete_info.csv"]
    coverage = frames["coverage.csv"]
    public_figures = parse_public_figures(frames["public_figures.csv"])
    active_figures = [item for item in public_figures if item["status"] == "active"]
    if not active_figures:
        raise ValueError("[error] data/public_figures.csv에 active 상태 선수가 없습니다.")
    active_ids = [item["idNo"] for item in active_figures]
    active_id_set = set(active_ids)
    public_by_id = {item["idNo"]: item for item in public_figures}

    required_id_frames = {
        "placements.csv": placements,
        "youth_summary.csv": summary,
        "age_matrix.csv": matrix,
        "athlete_info.csv": athlete_info,
    }
    for frame_name, frame in required_id_frames.items():
        if "idNo" not in frame.columns:
            raise ValueError(f"[error] idNo 컬럼이 없습니다: data/{frame_name}")
        frame["idNo"] = frame["idNo"].map(as_id)

    placements["순위_num"] = placements["순위"].map(as_int)
    placements["대회연도_num"] = placements["대회연도"].map(as_int)
    placements["나이_추정_num"] = placements["나이_추정"].map(as_int)
    placements["거리_num"] = placements["거리"].map(as_int)
    placements["sf_bool"] = placements["SF여부"].map(as_bool)
    placements_target = placements[placements["idNo"].isin(active_id_set)].copy()

    elem = placements_target[(placements_target["학령구간"] == "초등") & placements_target["순위_num"].notna()].copy()
    elem_median = elem.groupby("idNo")["순위_num"].median().to_dict()

    info_by_id = {}
    for id_no, group in athlete_info.groupby("idNo", sort=False):
        if not id_no:
            continue
        names = [v.strip() for v in group.get("이름", pd.Series(dtype=str)).tolist() if str(v).strip()]
        teams = [v.strip() for v in group.get("소속팀", pd.Series(dtype=str)).tolist() if str(v).strip()]
        genders = [v.strip() for v in group.get("성별", pd.Series(dtype=str)).tolist() if str(v).strip()]
        births = [as_int(v) for v in group.get("출생년도", pd.Series(dtype=str)).tolist() if as_int(v) is not None]
        info_by_id[id_no] = {
            "name": names[0] if names else id_no,
            "birth": births[0] if births else None,
            "team": teams[0] if teams else "-",
            "gender": genders[0] if genders else None,
        }

    summary_by_id = {}
    for _, row in summary.iterrows():
        id_no = as_id(row.get("idNo", ""))
        name = str(row.get("이름", "")).strip()
        if not id_no:
            continue
        summary_by_id[id_no] = {
            "name": name,
            "first": as_int(row.get("최초_출전나이")),
            "elemBest": as_int(row.get("초등부_최고순위")),
            "elemWorst": as_int(row.get("초등부_최저순위")),
            "elemCount": as_int(row.get("초등부_출전수")) or 0,
        }

    matrix_by_id = {}
    for _, row in matrix.iterrows():
        id_no = as_id(row.get("idNo", ""))
        name = str(row.get("이름", "")).strip()
        if not id_no:
            continue
        matrix_by_id[id_no] = {"name": name, "ages": {age: as_int(row.get(age, "")) for age in AGES}}

    history_by_id = {}
    for _, row in placements_target.iterrows():
        id_no = as_id(row.get("idNo", ""))
        rank = as_int(row.get("순위"))
        if not id_no or rank is None:
            continue
        history_by_id.setdefault(id_no, []).append(
            {
                "year": as_int(row.get("대회연도")),
                "age": as_int(row.get("나이_추정")),
                "meet": str(row.get("대회명", "")).strip() or "-",
                "distance": as_int(row.get("거리")),
                "sf": as_bool(row.get("SF여부", "")),
                "rank": rank,
                "round": str(row.get("결승구분", "")).strip() or str(row.get("라운드종류", "")).strip() or "-",
            }
        )

    athletes = []
    for id_no in active_ids:
        public = public_by_id[id_no]
        s = summary_by_id.get(id_no, {})
        info = info_by_id.get(id_no, {"name": id_no, "birth": None, "team": "-", "gender": None})
        m = matrix_by_id.get(id_no, {})
        has_profile = id_no in info_by_id or id_no in summary_by_id or id_no in matrix_by_id
        history = history_by_id.get(id_no, [])
        if not has_profile and not history:
            raise ValueError(f"[error] data/public_figures.csv의 idNo가 분석 데이터에 없습니다: {id_no}")

        name = public["name"] or info.get("name") or s.get("name") or m.get("name") or id_no
        birth = public["birth"] if public.get("birth") is not None else info.get("birth")
        median = elem_median.get(id_no)
        median_value = float(median) if median is not None else None
        history = sorted(history, key=lambda x: (x.get("year") is None, -(x.get("year") or 0), x.get("meet", ""), x.get("distance") or 0, x.get("rank") or 9999))
        athletes.append(
            {
                "idNo": id_no,
                "slug": public["slug"],
                "url": f"athlete/{public['slug']}/",
                "name": name,
                "birth": birth,
                "team": info["team"],
                "gender": info["gender"],
                "designationReason": public["designationReason"],
                "mediaReportUrl": public["mediaReportUrl"],
                "designatedAt": public["designatedAt"],
                "status": public["status"],
                "first": s.get("first"),
                "ages": m.get("ages", {age: None for age in AGES}),
                "elem": {
                    "best": s.get("elemBest"),
                    "median": median_value,
                    "worst": s.get("elemWorst"),
                    "count": s.get("elemCount", 0),
                },
                "history": history,
            }
        )

    years = [y for y in placements_target["대회연도_num"].tolist() if y is not None]
    if not years:
        years = [as_int(v) for v in coverage.get("대회연도", pd.Series(dtype=str)).tolist()]
        years = [y for y in years if y is not None]
    year_start, year_end = (min(years), max(years)) if years else (None, None)

    all_ages = [a for a in placements_target["나이_추정_num"].tolist() if isinstance(a, int)]
    ages_for_span = [a for a in all_ages if a <= 25] or all_ages
    age_min = min(ages_for_span) if ages_for_span else None
    age_max = max(ages_for_span) if ages_for_span else None

    elem_with_data = [a for a in athletes if (a["elem"].get("count") or 0) > 0]
    elem_top2_count = sum(1 for a in elem_with_data if (a["elem"].get("best") or 9999) <= 2)
    elem_worst_max = max((a["elem"].get("worst") or 0) for a in elem_with_data) if elem_with_data else None

    first_ages = [a.get("first") for a in athletes if a.get("first") is not None]
    first_age_min = min(first_ages) if first_ages else None
    first_age_max = max(first_ages) if first_ages else None

    missing_elem_names = [a["name"] for a in athletes if (a["elem"].get("count") or 0) == 0]
    payload = {
        "meta": {
            "athleteCount": len(athletes),
            "placementCount": int(len(placements_target)),
            "yearStart": year_start,
            "yearEnd": year_end,
            "yearSpan": (year_end - year_start) if year_start is not None and year_end is not None else None,
            "ageMin": age_min,
            "ageMax": age_max,
            "elemTop2Count": elem_top2_count,
            "elemWorstBand": rank_band_text(elem_worst_max),
            "firstAgeMin": first_age_min,
            "firstAgeMax": first_age_max,
            "missingElemNames": missing_elem_names,
        },
        "ages": [int(age) for age in AGES],
        "athletes": athletes,
    }
    return payload, placements_target, public_figures, active_id_set


def build_meets(placements_target):
    if placements_target.empty:
        return {"items": []}
    base = placements_target.copy()
    base["대회명_text"] = base["대회명"].astype(str).str.strip().replace("", "-")
    base = base[base["대회연도_num"].notna()].copy()
    if base.empty:
        return {"items": []}

    items = []
    grouped = base.groupby(["대회연도_num", "대회명_text"], dropna=False, sort=False)
    for (year, meet), group in grouped:
        distances = sorted({int(v) for v in group["거리_num"].dropna().tolist()})
        rounds = sorted({str(v).strip() for v in group["결승구분"].tolist() if str(v).strip()})
        items.append(
            {
                "year": int(year),
                "meet": meet,
                "raceCount": int(len(group)),
                "athleteCount": int(group["idNo"].astype(str).str.strip().replace("", pd.NA).dropna().nunique()),
                "distanceSet": distances,
                "roundTypes": rounds,
                "hasSemifinal": bool(group["sf_bool"].fillna(False).any()),
            }
        )
    items = sorted(items, key=lambda x: (-x["year"], x["meet"]))
    return {"items": items}


def _rank_summary(group):
    ranks = group["순위_num"].dropna().astype(int)
    if ranks.empty:
        return None
    return {
        "sampleSize": int(len(ranks)),
        "rankMin": int(ranks.min()),
        "rankMedian": round(float(ranks.median()), 1),
        "rankMax": int(ranks.max()),
        "top3Rate": round(float((ranks <= 3).mean()), 4),
    }


def _k_safe(group):
    athlete_count = int(group["idNo"].astype(str).str.strip().replace("", pd.NA).dropna().nunique())
    return athlete_count >= K_ANONYMITY_MIN, athlete_count


def build_distribution(placements_target):
    base = placements_target[placements_target["순위_num"].notna()].copy()
    by_age = []
    for age, group in base[base["나이_추정_num"].notna()].groupby("나이_추정_num", sort=True):
        ok, athlete_count = _k_safe(group)
        if not ok:
            continue
        stats = _rank_summary(group)
        if not stats:
            continue
        by_age.append({"age": int(age), "athleteCount": athlete_count, **stats})

    by_distance = []
    for distance, group in base[base["거리_num"].notna()].groupby("거리_num", sort=True):
        ok, athlete_count = _k_safe(group)
        if not ok:
            continue
        stats = _rank_summary(group)
        if not stats:
            continue
        by_distance.append({"distance": int(distance), "athleteCount": athlete_count, **stats})

    by_year = []
    for year, group in base[base["대회연도_num"].notna()].groupby("대회연도_num", sort=True):
        ok, athlete_count = _k_safe(group)
        if not ok:
            continue
        stats = _rank_summary(group)
        if not stats:
            continue
        by_year.append({"year": int(year), "athleteCount": athlete_count, **stats})

    return {"kAnonymityMin": K_ANONYMITY_MIN, "byAge": by_age, "byDistance": by_distance, "byYear": by_year}


def build_meta(payload, public_figures):
    meta = dict(payload["meta"])
    meta["generatedAt"] = date.today().isoformat()
    meta["publicFigureCount"] = len(public_figures)
    meta["activeFigureCount"] = int(meta.get("athleteCount") or 0)
    return meta


def assert_public_scope(athletes, active_id_set):
    exported_ids = {as_id(item.get("idNo")) for item in athletes if as_id(item.get("idNo"))}
    extra = sorted(v for v in exported_ids if v not in active_id_set)
    if extra:
        raise ValueError(f"[error] 공개 명단 외 idNo가 athletes.json에 포함되었습니다: {', '.join(extra[:5])}")


def main():
    try:
        frames = {name: read_csv(name) for name in INPUT_FILES}
        payload, placements_target, public_figures, active_id_set = build_athletes_payload(frames)
        meets = build_meets(placements_target)
        distribution = build_distribution(placements_target)
        meta = build_meta(payload, public_figures)
        athletes_doc = {"ages": payload["ages"], "athletes": payload["athletes"]}
        assert_public_scope(athletes_doc["athletes"], active_id_set)
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc))
        return

    write_json(ATHLETES_JSON, athletes_doc)
    write_json(MEETS_JSON, meets)
    write_json(DISTRIBUTION_JSON, distribution)
    write_json(META_JSON, meta)
    print(f"[ok] 생성 완료: {ATHLETES_JSON}")
    print(f"[ok] 생성 완료: {MEETS_JSON}")
    print(f"[ok] 생성 완료: {DISTRIBUTION_JSON}")
    print(f"[ok] 생성 완료: {META_JSON}")


if __name__ == "__main__":
    main()
