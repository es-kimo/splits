"""선수 식별키(익명키) 신뢰도를 점검합니다.

익명화 직전 원천(records_full/records + athlete_info_full/athlete_info)에서만 동작합니다.
표본 100명 감사 + 전수 자동 탐지를 수행하고, 숫자 중심 요약 보고서를 생성합니다.

기본 사용:
    python3 scripts/audit_id_key_reliability.py
    python3 scripts/audit_id_key_reliability.py --data-dir /Users/kihyun/orgs/personal/splits/data
"""

import argparse
import os
import random
import re
import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analyze import build_clean_records
from build_data import ANON_SALT_ENV, anon_key_spec, build_anon_key
from local_env import load_local_env

DEFAULT_DATA_DIR = Path("data")
DEFAULT_SHARED_DATA_DIR = Path("/Users/kihyun/orgs/personal/splits/data")
DEFAULT_SUMMARY_OUT = DEFAULT_DATA_DIR / "merge_audit_summary.md"
DEFAULT_PRIVATE_SAMPLE_OUT = DEFAULT_DATA_DIR / "merge_audit_sample_private.csv"
DEFAULT_PRIVATE_SIGNAL_OUT = DEFAULT_DATA_DIR / "merge_audit_signals_private.csv"
GRADE_RE = re.compile(r"([1-6](?:\s*,\s*[1-6])?)\s*학년")


def _norm(value):
    if value is None:
        return ""
    if not isinstance(value, str) and pd.isna(value):
        return ""
    return str(value).strip()


def _norm_name(value):
    text = _norm(value)
    if not text:
        return ""
    return re.sub(r"[^0-9A-Za-z가-힣]+", "", text).lower()


def _read_csv(path):
    if not path.exists():
        raise FileNotFoundError(f"[error] 파일이 없습니다: {path}")
    return pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")


def _pick_data_source(preferred_dir):
    candidates = [preferred_dir]
    if DEFAULT_SHARED_DATA_DIR not in candidates:
        candidates.append(DEFAULT_SHARED_DATA_DIR)

    checked = []
    for root in candidates:
        full_pair = (root / "records_full.csv", root / "athlete_info_full.csv")
        if full_pair[0].exists() and full_pair[1].exists():
            return root, full_pair[0], full_pair[1], "records_full.csv+athlete_info_full.csv"
        checked.append(full_pair)

    for root in candidates:
        base_pair = (root / "records.csv", root / "athlete_info.csv")
        if base_pair[0].exists() and base_pair[1].exists():
            return root, base_pair[0], base_pair[1], "records.csv+athlete_info.csv"
        checked.append(base_pair)

    checked_text = ", ".join([f"{records.name}+{athlete.name}@{records.parent}" for records, athlete in checked])
    raise FileNotFoundError(f"[error] 감사 입력 파일을 찾지 못했습니다: {checked_text}")


def _extract_grade_token(value):
    text = _norm(value).replace(" ", "")
    if not text:
        return ""
    match = GRADE_RE.search(text)
    if not match:
        return ""
    return match.group(1).replace(" ", "")


def _build_profiles(records_df, clean_df):
    base = clean_df.copy()
    base["idNo"] = base["idNo"].map(_norm)
    base = base[base["idNo"] != ""].copy()
    if base.empty:
        return pd.DataFrame(columns=["idNo", "이름", "성별", "출생연도", "시즌수", "시즌목록", "소속수", "소속목록", "이름표기수", "이름표기목록"])

    record_aff = records_df.copy()
    if "idNo" in record_aff.columns:
        record_aff["idNo"] = record_aff["idNo"].map(_norm)
    if "소속" not in record_aff.columns:
        record_aff["소속"] = ""
    aff_by_id = (
        record_aff[record_aff["idNo"] != ""]
        .groupby("idNo", dropna=False)["소속"]
        .apply(lambda s: sorted({_norm(v) for v in s.tolist() if _norm(v)}))
        .to_dict()
    )

    rows = []
    for id_no, group in base.groupby("idNo", sort=False):
        names = sorted({_norm(v) for v in group["이름"].tolist() if _norm(v)})
        genders = sorted({_norm(v) for v in group["성별"].tolist() if _norm(v)})
        births = sorted({int(v) for v in pd.to_numeric(group["출생년도"], errors="coerce").dropna().tolist()})
        years = sorted({int(v) for v in pd.to_numeric(group["대회연도"], errors="coerce").dropna().tolist()})
        affiliations = aff_by_id.get(id_no, [])
        rows.append(
            {
                "idNo": id_no,
                "이름": names[0] if names else "",
                "성별": genders[0] if genders else "",
                "출생연도": births[0] if births else pd.NA,
                "시즌수": len(years),
                "시즌목록": "|".join(str(v) for v in years),
                "소속수": len(affiliations),
                "소속목록": "|".join(affiliations),
                "이름표기수": len(names),
                "이름표기목록": "|".join(names),
            }
        )
    profile = pd.DataFrame(rows)
    profile["출생연도"] = pd.to_numeric(profile["출생연도"], errors="coerce").astype("Int64")
    return profile


def _classify_split_group(group):
    raw_names = set()
    normalized_names = set()
    all_affiliations = set()
    season_sets = []

    for _, row in group.iterrows():
        for name in str(row.get("이름표기목록") or "").split("|"):
            name_text = _norm(name)
            if not name_text:
                continue
            raw_names.add(name_text)
            normalized_names.add(_norm_name(name_text))
        all_affiliations.update([_norm(v) for v in str(row.get("소속목록") or "").split("|") if _norm(v)])
        season_sets.append({int(v) for v in str(row.get("시즌목록") or "").split("|") if v.isdigit()})

    if len(normalized_names) == 1 and len(raw_names) > 1:
        return "표기차이"
    if len(normalized_names) > 1:
        return "개명"

    if len(all_affiliations) >= 2:
        disjoint_pair_found = False
        for i in range(len(season_sets)):
            for j in range(i + 1, len(season_sets)):
                if season_sets[i] and season_sets[j] and season_sets[i].isdisjoint(season_sets[j]):
                    disjoint_pair_found = True
                    break
            if disjoint_pair_found:
                break
        if disjoint_pair_found:
            return "소속변경"
    return "동명이인"


def _build_split_signals(profile_df):
    keyed = profile_df.copy()
    keyed["이름정규화"] = keyed["이름"].map(_norm_name)
    keyed["성별"] = keyed["성별"].map(_norm)
    keyed["출생연도"] = pd.to_numeric(keyed["출생연도"], errors="coerce").astype("Int64")
    keyed = keyed[(keyed["이름정규화"] != "") & (keyed["성별"] != "") & keyed["출생연도"].notna()]
    if keyed.empty:
        return {}, {}

    split_type_by_id = {}
    split_type_counts = {"개명": 0, "소속변경": 0, "표기차이": 0, "동명이인": 0}
    grouped = keyed.groupby(["이름정규화", "성별", "출생연도"], dropna=False, sort=False)
    for _, group in grouped:
        unique_ids = sorted(set(group["idNo"].tolist()))
        if len(unique_ids) < 2:
            continue
        split_type = _classify_split_group(group)
        split_type_counts[split_type] = split_type_counts.get(split_type, 0) + 1
        for id_no in unique_ids:
            split_type_by_id[id_no] = split_type
    return split_type_by_id, split_type_counts


def _build_merge_signals(clean_df, salt_text):
    base = clean_df.copy()
    base["idNo"] = base["idNo"].map(_norm)
    base = base[base["idNo"] != ""].copy()
    if base.empty:
        empty = pd.DataFrame(columns=["idNo", "mergeSignals", "duplicateEventCount", "gradeConflictCount", "ageReversalCount"])
        return empty, {"duplicate_event_keys": 0, "grade_conflict_keys": 0, "age_reversal_keys": 0}

    base["익명키"] = base["idNo"].map(lambda value: build_anon_key(value, salt_text))
    base["대회연도_num"] = pd.to_numeric(base["대회연도"], errors="coerce").astype("Int64")
    base["나이_추정_num"] = pd.to_numeric(base["나이_추정"], errors="coerce").astype("Int64")
    if "종별" not in base.columns:
        base["종별"] = ""
    if "세부종목" not in base.columns:
        base["세부종목"] = ""
    if "라운드" not in base.columns:
        base["라운드"] = ""
    base["학년토큰"] = base["종별"].map(_extract_grade_token)

    event_cols = ["익명키", "대회명", "종별", "세부종목", "라운드"]
    event_dup = (
        base.groupby(event_cols, dropna=False)
        .size()
        .reset_index(name="행수")
    )
    event_dup = event_dup[event_dup["행수"] >= 2].copy()
    duplicate_event_count_by_id = base.merge(event_dup[event_cols], on=event_cols, how="inner").groupby("idNo", dropna=False).size().to_dict()

    grade_rows = base[(base["대회연도_num"].notna()) & (base["학년토큰"] != "")].copy()
    grade_conflict = (
        grade_rows.groupby(["idNo", "대회연도_num"], dropna=False)["학년토큰"]
        .nunique()
        .reset_index(name="학년종류수")
    )
    grade_conflict = grade_conflict[grade_conflict["학년종류수"] >= 2]
    grade_conflict_count_by_id = grade_conflict.groupby("idNo", dropna=False).size().to_dict()

    age_rows = base[(base["대회연도_num"].notna()) & (base["나이_추정_num"].notna())][["idNo", "대회연도_num", "나이_추정_num"]].copy()
    age_by_year = (
        age_rows.groupby(["idNo", "대회연도_num"], dropna=False)["나이_추정_num"]
        .median()
        .reset_index()
        .sort_values(["idNo", "대회연도_num"])
    )
    age_reversal_count_by_id = {}
    for id_no, group in age_by_year.groupby("idNo", sort=False):
        ages = [float(v) for v in group["나이_추정_num"].tolist()]
        reversals = 0
        for prev, cur in zip(ages, ages[1:]):
            if cur < prev:
                reversals += 1
        if reversals:
            age_reversal_count_by_id[id_no] = reversals

    id_list = sorted(set(base["idNo"].tolist()))
    rows = []
    for id_no in id_list:
        signals = []
        dup_count = int(duplicate_event_count_by_id.get(id_no, 0))
        grade_count = int(grade_conflict_count_by_id.get(id_no, 0))
        age_rev_count = int(age_reversal_count_by_id.get(id_no, 0))
        if dup_count:
            signals.append("동일경기중복")
        if grade_count:
            signals.append("학년충돌")
        if age_rev_count:
            signals.append("시즌연령역행")
        rows.append(
            {
                "idNo": id_no,
                "mergeSignals": "|".join(signals),
                "duplicateEventCount": dup_count,
                "gradeConflictCount": grade_count,
                "ageReversalCount": age_rev_count,
            }
        )

    signal_df = pd.DataFrame(rows)
    stats = {
        "duplicate_event_keys": int(len(event_dup)),
        "grade_conflict_keys": int(len(grade_conflict["idNo"].unique())),
        "age_reversal_keys": int(len(age_reversal_count_by_id)),
    }
    return signal_df, stats


def _rate_text(numerator, denominator):
    if denominator <= 0:
        return "0/0 (0.0%)"
    ratio = numerator / denominator * 100.0
    return f"{numerator}/{denominator} ({ratio:.1f}%)"


def _assess_feasibility(split_rate_pct, merge_confirmed_count, merge_suspect_rate_pct):
    if split_rate_pct > 5.0 or merge_confirmed_count > 0:
        return "낮음", "식별 안정성 리스크가 커서 매칭 기반 본인 확인은 보류가 필요합니다."
    if split_rate_pct > 2.0 or merge_suspect_rate_pct > 2.0:
        return "보통", "기능 도입 전 추가 검증/보정(병합 룰 보완)이 필요합니다."
    return "높음", "현재 기준에서는 매칭 기반 본인 확인을 시도할 수 있는 수준입니다."


def _write_summary(path, payload):
    lines = []
    lines.append("# merge_audit_summary")
    lines.append("")
    lines.append(f"- 생성일: {payload['today']}")
    lines.append(f"- 입력 경로: `{payload['source_dir']}`")
    lines.append(f"- 입력 파일: `{payload['source_pair']}`")
    lines.append("")
    lines.append("## 1) 익명키 생성 입력 확인")
    lines.append("")
    lines.append(f"- 생성식: `{payload['key_formula']}`")
    lines.append(f"- 입력 식별 필드: `{payload['key_source_field']}`")
    lines.append(f"- SALT 환경변수: `{payload['key_salt_env']}`")
    lines.append(f"- 길이: `{payload['key_hex_length']} hex`")
    lines.append(f"- 입력 제외 필드: `{payload['key_excluded_fields']}`")
    lines.append(f"- 소속 포함 여부: `{payload['affiliation_in_key']}`")
    lines.append("")
    lines.append("## 2) 표본(2시즌+ 선수 무작위) 감사 결과")
    lines.append("")
    lines.append(f"- 표본 조건 모수: {payload['cohort_count']}명")
    lines.append(f"- 표본 크기: {payload['sample_size']}명 (seed={payload['seed']})")
    lines.append(f"- 쪼개짐 추정 비율: {_rate_text(payload['sample_split_count'], payload['sample_size'])}")
    lines.append(f"- 합쳐짐 추정 비율: {_rate_text(payload['sample_merge_count'], payload['sample_size'])}")
    lines.append("")
    lines.append("## 3) 전수 자동 탐지")
    lines.append("")
    lines.append(f"- 동일 대회·동일 경기·동일 익명키 2행 이상: {payload['full_duplicate_event_keys']}건")
    lines.append(f"- 동일 익명키 학년 충돌(동일 시즌): {payload['full_grade_conflict_keys']}건")
    lines.append(f"- 동일 익명키 시즌-연령 역행: {payload['full_age_reversal_keys']}건")
    lines.append("")
    lines.append("## 4) 오류 유형별 건수 (쪼개짐 분류)")
    lines.append("")
    lines.append(f"- 개명: {payload['split_type_rename']}건")
    lines.append(f"- 소속변경: {payload['split_type_affiliation']}건")
    lines.append(f"- 표기차이: {payload['split_type_typo']}건")
    lines.append(f"- 동명이인: {payload['split_type_homonym']}건")
    lines.append("")
    lines.append("## 5) 매칭 기반 본인 확인 실현 가능성")
    lines.append("")
    lines.append(f"- 판정: **{payload['feasibility_level']}**")
    lines.append(f"- 근거: {payload['feasibility_reason']}")
    lines.append(f"- 쪼개짐 5% 초과 여부: `{payload['split_over_five_percent']}`")
    lines.append("")
    lines.append("## 6) 운영 메모")
    lines.append("")
    lines.append("- 본 보고서는 숫자/유형 통계만 포함하며 실명·원천 식별자는 포함하지 않았습니다.")
    lines.append("- 상세 표본/신호 파일은 로컬 전용(private) 산출물로만 저장해야 하며 Git에 커밋하면 안 됩니다.")
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="선수 식별키(익명키) 신뢰도 감사")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR), help="입력 데이터 디렉터리 (기본: data)")
    parser.add_argument("--sample-size", type=int, default=100, help="표본 선수 수 (기본: 100)")
    parser.add_argument("--seed", type=int, default=77, help="표본 추출 시드 (기본: 77)")
    parser.add_argument("--summary-out", default=str(DEFAULT_SUMMARY_OUT), help="요약 보고서 출력 경로")
    parser.add_argument("--private-sample-out", default=str(DEFAULT_PRIVATE_SAMPLE_OUT), help="로컬 전용 표본 상세 CSV")
    parser.add_argument("--private-signal-out", default=str(DEFAULT_PRIVATE_SIGNAL_OUT), help="로컬 전용 이상신호 CSV")
    parser.add_argument("--no-private-exports", action="store_true", help="private 상세 CSV 생성을 건너뜁니다")
    args = parser.parse_args()

    if args.sample_size <= 0:
        raise ValueError("[error] --sample-size는 1 이상이어야 합니다.")

    load_local_env()

    data_dir = Path(args.data_dir).expanduser()
    source_dir, records_path, athlete_path, source_pair = _pick_data_source(data_dir)
    records_df = _read_csv(records_path)
    athlete_df = _read_csv(athlete_path)
    clean_df = build_clean_records(records_df, athlete_df)

    profile_df = _build_profiles(records_df, clean_df)
    split_type_by_id, split_type_counts = _build_split_signals(profile_df)

    salt_text = _norm(os.environ.get(ANON_SALT_ENV, ""))
    if not salt_text:
        # SALT가 없어도 동등성 검사는 가능하다(동일 idNo -> 동일 익명키).
        salt_text = "__SALT_MISSING_FOR_AUDIT__"

    merge_signal_df, merge_stats = _build_merge_signals(clean_df, salt_text)

    cohort = profile_df[profile_df["시즌수"] >= 2].copy()
    cohort_ids = sorted(set(cohort["idNo"].tolist()))
    sample_size = min(args.sample_size, len(cohort_ids))
    rng = random.Random(args.seed)
    sampled_ids = rng.sample(cohort_ids, sample_size) if sample_size else []

    sample_split_count = 0
    sample_merge_count = 0
    sample_rows = []
    profile_by_id = profile_df.set_index("idNo").to_dict(orient="index") if not profile_df.empty else {}
    signal_by_id = merge_signal_df.set_index("idNo").to_dict(orient="index") if not merge_signal_df.empty else {}
    for id_no in sampled_ids:
        split_type = split_type_by_id.get(id_no, "")
        merge_info = signal_by_id.get(id_no, {})
        merge_signals = _norm(merge_info.get("mergeSignals"))
        split_flag = "Y" if split_type else "N"
        merge_flag = "Y" if merge_signals else "N"
        if split_flag == "Y":
            sample_split_count += 1
        if merge_flag == "Y":
            sample_merge_count += 1
        profile = profile_by_id.get(id_no, {})
        sample_rows.append(
            {
                "idNo": id_no,
                "이름": _norm(profile.get("이름")),
                "성별": _norm(profile.get("성별")),
                "출생연도": _norm(profile.get("출생연도")),
                "시즌수": _norm(profile.get("시즌수")),
                "시즌목록": _norm(profile.get("시즌목록")),
                "소속수": _norm(profile.get("소속수")),
                "소속목록": _norm(profile.get("소속목록")),
                "쪼개짐의심": split_flag,
                "쪼개짐유형": split_type,
                "합쳐짐의심": merge_flag,
                "합쳐짐신호": merge_signals,
                "동일경기중복건수": _norm(merge_info.get("duplicateEventCount")),
                "학년충돌건수": _norm(merge_info.get("gradeConflictCount")),
                "시즌연령역행건수": _norm(merge_info.get("ageReversalCount")),
            }
        )

    split_rate_pct = (sample_split_count / sample_size * 100.0) if sample_size else 0.0
    merge_suspect_rate_pct = (sample_merge_count / sample_size * 100.0) if sample_size else 0.0
    feasibility_level, feasibility_reason = _assess_feasibility(
        split_rate_pct=split_rate_pct,
        merge_confirmed_count=merge_stats["duplicate_event_keys"],
        merge_suspect_rate_pct=merge_suspect_rate_pct,
    )

    key_spec = anon_key_spec()
    excluded_fields = set(key_spec.get("excluded_fields", []))
    payload = {
        "today": date.today().isoformat(),
        "source_dir": str(source_dir),
        "source_pair": source_pair,
        "key_formula": _norm(key_spec.get("formula")),
        "key_source_field": _norm(key_spec.get("source_field")),
        "key_salt_env": _norm(key_spec.get("salt_env")),
        "key_hex_length": int(key_spec.get("hex_length") or 0),
        "key_excluded_fields": ", ".join(sorted(excluded_fields)),
        "affiliation_in_key": "N" if "소속" in excluded_fields else "Y",
        "cohort_count": int(len(cohort_ids)),
        "sample_size": int(sample_size),
        "seed": int(args.seed),
        "sample_split_count": int(sample_split_count),
        "sample_merge_count": int(sample_merge_count),
        "full_duplicate_event_keys": int(merge_stats["duplicate_event_keys"]),
        "full_grade_conflict_keys": int(merge_stats["grade_conflict_keys"]),
        "full_age_reversal_keys": int(merge_stats["age_reversal_keys"]),
        "split_type_rename": int(split_type_counts.get("개명", 0)),
        "split_type_affiliation": int(split_type_counts.get("소속변경", 0)),
        "split_type_typo": int(split_type_counts.get("표기차이", 0)),
        "split_type_homonym": int(split_type_counts.get("동명이인", 0)),
        "feasibility_level": feasibility_level,
        "feasibility_reason": feasibility_reason,
        "split_over_five_percent": "Y" if split_rate_pct > 5.0 else "N",
    }

    summary_out = Path(args.summary_out).expanduser()
    _write_summary(summary_out, payload)
    print(f"[ok] 요약 보고서 생성: {summary_out}")

    if not args.no_private_exports:
        sample_out = Path(args.private_sample_out).expanduser()
        signal_out = Path(args.private_signal_out).expanduser()
        sample_out.parent.mkdir(parents=True, exist_ok=True)
        signal_out.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(sample_rows).to_csv(sample_out, index=False, encoding="utf-8-sig")
        merge_signal_df.to_csv(signal_out, index=False, encoding="utf-8-sig")
        print(f"[ok] private 표본 상세 CSV: {sample_out}")
        print(f"[ok] private 이상신호 CSV: {signal_out}")
        print("[warn] private 산출물에는 원천 식별자가 포함될 수 있습니다. Git 커밋 금지")

    print(f"[ok] 표본 쪼개짐 비율: {_rate_text(sample_split_count, sample_size)}")
    print(f"[ok] 표본 합쳐짐 비율: {_rate_text(sample_merge_count, sample_size)}")
    print(
        "[ok] 전수 신호: 동일경기중복 {0}건 / 학년충돌 {1}건 / 시즌연령역행 {2}건".format(
            merge_stats["duplicate_event_keys"],
            merge_stats["grade_conflict_keys"],
            merge_stats["age_reversal_keys"],
        )
    )
    if split_rate_pct > 5.0:
        print("[warn] 쪼개짐 비율이 5%를 초과했습니다. 후속 개선 이슈 생성 후 5~8번 진행 보류를 권장합니다.")


if __name__ == "__main__":
    main()
