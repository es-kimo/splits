from __future__ import annotations

import argparse
import math
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import polars as pl

from .policies import ExtractionPolicy, POLICIES, get_policy

SHORTTRACK_CLASS_CD = "2"
SPEED_CLASS_CD = "1"
FIGURE_CLASS_CD = "3"
RELAY_RE = re.compile(r"(릴레이|relay|계주)", re.IGNORECASE)
GROUP_ONLY_ROUND_RE = re.compile(r"^\d+조$")
HEAT_NUMBER_RE = re.compile(r"(\d+)\s*조|heat\s*([0-9]+)", re.IGNORECASE)
GENDER_PREFIX_RE = re.compile(r"^(남자|여자|남|여)")

ALIASES = {
    "meet_id": ["meet_id", "toCd"],
    "race_id": ["race_id"],
    "race_seq": ["race_seq", "raceSeq", "경기순서", "경기순번"],
    "athlete_id": ["athlete_hash", "익명키", "idNo"],
    "event": ["event", "세부종목"],
    "round": ["round", "라운드"],
    "round_kind": ["round_kind", "라운드종류"],
    "place": ["place", "순위"],
    "time": ["time", "기록_초", "기록"],
    "status_raw": ["status", "사유"],
    "advanced_raw": ["advanced", "ADV", "AD"],
    "season_text": ["season", "season_year", "대회연도"],
    "grade_text": ["grade", "학년", "학령구간", "학년_계산"],
    "birth_year": ["birth_year", "출생연도", "출생년도"],
    "division_text": ["division_text", "학령구간"],
    "gender": ["gender", "성별"],
    "class_cd": ["class_cd", "classCd"],
    "meet_name": ["meet_name", "대회명"],
    "category": ["category", "종별"],
    "distance_text": ["distance", "거리"],
    "sf_flag": ["sf_flag", "SF여부"],
    "date": ["date", "일자", "일자_정규화"],
}

STATUS_FIN = "FIN"
STATUS_PEN = "PEN"
STATUS_DNF = "DNF"
STATUS_DNS = "DNS"
STATUS_ADV = "ADV"
STATUS_UNKNOWN = "UNKNOWN"

STATUS_HANDLING = {
    STATUS_FIN: "유효 착순으로 비교 생성",
    STATUS_PEN: "정책에 따라 제외 또는 꼴찌 재배치",
    STATUS_DNF: "정책에 따라 제외 또는 완주자에게만 패배",
    STATUS_DNS: "비교 생성에서 제외",
    STATUS_ADV: "정책에 따라 제외 또는 유지",
    STATUS_UNKNOWN: "예외 발생(조용한 통과 금지)",
}

DENY_PEN_TOKENS = ("pen", "dq", "disq", "disqualified", "실격", "부정출발")
DENY_DNS_TOKENS = ("dns", "출발전포기", "경기전포기", "미출전", "기권")
DENY_DNF_TOKENS = ("dnf", "no time", "ret", "withdraw", "경기중포기", "경기중 기권", "포기")
ALLOW_FINISH_TOKENS = {"", "ok", "finished", "finish", "완주", "정상완주", "v-sr"}


@dataclass(frozen=True)
class ExtractionRun:
    comparisons: pl.DataFrame
    prepared_rows: pl.DataFrame
    status_audit: pl.DataFrame
    diagnostics: dict[str, Any]


def _norm(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none"}:
        return ""
    return text


def _parse_int(value: Any) -> int | None:
    text = _norm(value)
    if not text:
        return None
    match = re.search(r"\d+", text)
    if not match:
        return None
    try:
        return int(match.group(0))
    except ValueError:
        return None


def _parse_year(season_text: Any, date_text: Any) -> int | None:
    season = _parse_int(season_text)
    if season is not None and 1900 <= season <= 2099:
        return season
    date = _norm(date_text)
    match = re.search(r"(19|20)\d{2}", date)
    if not match:
        return None
    try:
        return int(match.group(0))
    except ValueError:
        return None


def _parse_birth_year(value: Any) -> int | None:
    year = _parse_int(value)
    if year is None:
        return None
    if year < 1900 or year > 2099:
        return None
    return year


def _parse_time_seconds(value: Any) -> float | None:
    text = _norm(value)
    if not text:
        return None
    parts = text.split(":")
    try:
        if len(parts) == 1:
            return float(parts[0])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    except ValueError:
        return None
    return None


def _coalesce_alias(results: pl.DataFrame, alias_key: str) -> pl.Expr:
    existing = [name for name in ALIASES[alias_key] if name in results.columns]
    if not existing:
        return pl.lit("")
    return pl.coalesce([pl.col(name).cast(pl.Utf8, strict=False).fill_null("") for name in existing]).str.strip_chars()


def _event_key(event: str, category: str, distance_text: str) -> str:
    event_text = _norm(event)
    if event_text:
        return event_text
    category_text = _norm(category)
    distance = _norm(distance_text)
    if category_text and distance:
        return f"{category_text}-{distance}m"
    return category_text or distance


def split_division(category: Any, gender: Any) -> tuple[str, str]:
    """부문 라벨을 (성별, 연령/급 구간)으로 분리합니다.

    원천에 따라 성별이 별도 컬럼(`성별`)에 있기도 하고 종별 문자열 접두사
    (`남자중학부`)에 녹아 있기도 합니다. 두 소스가 같은 부문 키를 만들도록
    양쪽을 동일한 모양으로 정규화합니다.
    """
    category_text = _norm(category)
    gender_text = _norm(gender)
    match = GENDER_PREFIX_RE.match(category_text)
    if match:
        band = category_text[match.end() :].strip()
        if not gender_text:
            gender_text = match.group(1)[0]
    else:
        band = category_text
    if gender_text:
        gender_text = gender_text[0]
    return gender_text, band


def resolve_division_text(division_text: Any, category: Any, gender: Any) -> str:
    text = _norm(division_text)
    if text:
        return text
    _, band = split_division(category, gender)
    return _norm(band)


def division_key(category: Any, gender: Any) -> str:
    """레이스를 가르는 최소 단위(성별 + 연령/급 구간)의 정규 키."""
    gender_text, band = split_division(category, gender)
    return f"{gender_text or '-'}:{band or '-'}"


def resolve_gender(category: Any, gender: Any) -> str:
    gender_text, _band = split_division(category, gender)
    return gender_text


def _extract_heat_no(round_text: str) -> str:
    match = HEAT_NUMBER_RE.search(_norm(round_text))
    if not match:
        return ""
    return _norm(match.group(1) or match.group(2))


def _clean_piece(value: Any) -> str:
    return _norm(value).replace("|", "/")


def _build_reconstructed_race_id(row: dict[str, Any]) -> str:
    meet_id = _clean_piece(row.get("meet_id"))
    if not meet_id:
        meet_name = _clean_piece(row.get("meet_name"))
        season = _clean_piece(row.get("season_text"))
        if meet_name or season:
            meet_id = f"{season}:{meet_name}"
    event = _event_key(_norm(row.get("event")), _norm(row.get("category")), _norm(row.get("distance_text")))
    round_text = _norm(row.get("round")) or _norm(row.get("round_kind"))
    heat_no = _extract_heat_no(round_text)
    sf_flag = _clean_piece(row.get("sf_flag")).upper() or "-"
    date_text = _clean_piece(row.get("date")) or "-"
    # 부문(성별 + 연령/급 구간)이 빠지면 같은 대회/종목/라운드의 서로 다른 부문이
    # 하나의 레이스로 병합되어, 붙은 적 없는 선수 쌍이 비교로 생성됩니다.
    division = division_key(row.get("category"), row.get("gender"))
    if not (meet_id and event and round_text and division != "-:-"):
        return ""
    return "|".join(
        [
            _clean_piece(meet_id),
            _clean_piece(division),
            _clean_piece(event),
            _clean_piece(round_text),
            _clean_piece(heat_no) or "-",
            sf_flag,
            _clean_piece(date_text),
        ]
    )


def _classify_round(round_text: str, round_kind: str) -> str:
    merged = (_norm(round_kind) or _norm(round_text)).replace(" ", "")
    if "채점종합" in merged:
        return "score"
    if merged.startswith("결승B") or merged == "결승B":
        return "final_b"
    if merged.startswith("결승"):
        return "final"
    if "준준결승" in merged:
        return "quarterfinal"
    if "준결승" in merged:
        return "semifinal"
    if "예선" in merged:
        return "heat"
    return "other"


def _is_speed_meet_name(meet_name: str) -> bool:
    text = _norm(meet_name)
    if not text:
        return False
    return "스피드" in text and "쇼트트랙" not in text


def _classify_class_cd(class_cd: str, meet_name: str, round_text: str, round_kind: str) -> str:
    mapped = _norm(class_cd)
    if mapped in {SPEED_CLASS_CD, FIGURE_CLASS_CD}:
        return mapped
    kind = _classify_round(round_text, round_kind)
    compact_round = _norm(round_text).replace(" ", "")
    if kind == "other" and GROUP_ONLY_ROUND_RE.match(compact_round):
        return SPEED_CLASS_CD
    if _is_speed_meet_name(meet_name):
        return SPEED_CLASS_CD
    return SHORTTRACK_CLASS_CD


def _is_relay(event: str, round_text: str, round_kind: str, meet_name: str, category: str) -> bool:
    merged = " ".join([_norm(event), _norm(round_text), _norm(round_kind), _norm(meet_name), _norm(category)])
    return bool(RELAY_RE.search(merged))


def _is_hobby_division(category: str) -> bool:
    return "동호인" in _norm(category)


def _normalize_status(status_raw: str, advanced_raw: str, place_num: int | None, time_sec: float | None) -> str:
    status = _norm(status_raw)
    advanced = _norm(advanced_raw)
    status_lower = status.lower()
    advanced_lower = advanced.lower()

    if "adv" in advanced_lower or "adv" in status_lower:
        return STATUS_ADV
    if status_lower in ALLOW_FINISH_TOKENS:
        if place_num is None and time_sec is None:
            return STATUS_DNS
        return STATUS_FIN
    if any(token in status_lower for token in DENY_PEN_TOKENS):
        return STATUS_PEN
    if any(token in status_lower for token in DENY_DNS_TOKENS):
        return STATUS_DNS
    if any(token in status_lower for token in DENY_DNF_TOKENS):
        return STATUS_DNF
    if place_num is not None:
        return STATUS_FIN
    if time_sec is not None:
        return STATUS_FIN
    return STATUS_UNKNOWN


def _build_status_audit(rows: pl.DataFrame) -> pl.DataFrame:
    if rows.is_empty():
        return pl.DataFrame(
            schema={
                "status_raw": pl.Utf8,
                "status_norm": pl.Utf8,
                "row_count": pl.Int64,
                "athlete_count": pl.Int64,
                "ratio_pct": pl.Float64,
                "rare_under_1pct": pl.Utf8,
                "handling": pl.Utf8,
            }
        )
    grouped = (
        rows.group_by(["status_raw", "status_norm"])
        .agg(pl.len().alias("row_count"), pl.col("athlete_id").n_unique().alias("athlete_count"))
        .sort(["row_count", "status_raw"], descending=[True, False], nulls_last=True)
    )
    total = int(grouped["row_count"].sum())
    if total <= 0:
        total = 1
    out = grouped.with_columns(
        (pl.col("row_count") * 100.0 / float(total)).alias("ratio_pct"),
        pl.when(pl.col("row_count") * 100.0 / float(total) < 1.0).then(pl.lit("Y")).otherwise(pl.lit("N")).alias(
            "rare_under_1pct"
        ),
        pl.col("status_norm").map_elements(lambda value: STATUS_HANDLING.get(_norm(value), STATUS_HANDLING[STATUS_UNKNOWN]), return_dtype=pl.Utf8).alias("handling"),
    )
    return out.select(
        ["status_raw", "status_norm", "row_count", "athlete_count", "ratio_pct", "rare_under_1pct", "handling"]
    )


def _ensure_no_unknown_status(rows: pl.DataFrame) -> None:
    unknown = rows.filter(pl.col("status_norm") == STATUS_UNKNOWN).select("status_raw").unique().sort("status_raw")
    if unknown.is_empty():
        return
    values = []
    for value in unknown["status_raw"].to_list()[:20]:
        values.append(_norm(value) or "<blank>")
    joined = ", ".join(values)
    raise ValueError(f"[error] 미분류 status 코드가 있습니다: {joined}")


def _canonicalize_results(results: pl.DataFrame) -> pl.DataFrame:
    base = results.with_columns(
        [
            _coalesce_alias(results, "meet_id").alias("meet_id"),
            _coalesce_alias(results, "race_id").alias("race_id"),
            _coalesce_alias(results, "race_seq").alias("race_seq"),
            _coalesce_alias(results, "athlete_id").alias("athlete_id"),
            _coalesce_alias(results, "event").alias("event"),
            _coalesce_alias(results, "round").alias("round"),
            _coalesce_alias(results, "round_kind").alias("round_kind"),
            _coalesce_alias(results, "place").alias("place"),
            _coalesce_alias(results, "time").alias("time"),
            _coalesce_alias(results, "status_raw").alias("status_raw"),
            _coalesce_alias(results, "advanced_raw").alias("advanced_raw"),
            _coalesce_alias(results, "season_text").alias("season_text"),
            _coalesce_alias(results, "grade_text").alias("grade_text"),
            _coalesce_alias(results, "birth_year").alias("birth_year"),
            _coalesce_alias(results, "division_text").alias("division_text"),
            _coalesce_alias(results, "gender").alias("gender"),
            _coalesce_alias(results, "class_cd").alias("class_cd"),
            _coalesce_alias(results, "meet_name").alias("meet_name"),
            _coalesce_alias(results, "category").alias("category"),
            _coalesce_alias(results, "distance_text").alias("distance_text"),
            _coalesce_alias(results, "sf_flag").alias("sf_flag"),
            _coalesce_alias(results, "date").alias("date"),
        ]
    ).select(
        [
            "meet_id",
            "race_id",
            "race_seq",
            "athlete_id",
            "event",
            "round",
            "round_kind",
            "place",
            "time",
            "status_raw",
            "advanced_raw",
            "season_text",
            "grade_text",
            "birth_year",
            "division_text",
            "gender",
            "class_cd",
            "meet_name",
            "category",
            "distance_text",
            "sf_flag",
            "date",
        ]
    )
    base = base.with_columns(
        [
            pl.struct(["event", "category", "distance_text"])
            .map_elements(
                lambda row: _event_key(_norm(row["event"]), _norm(row["category"]), _norm(row["distance_text"])),
                return_dtype=pl.Utf8,
            )
            .alias("event"),
            pl.col("place").map_elements(_parse_int, return_dtype=pl.Int64).alias("place_num"),
            pl.col("race_seq").map_elements(_parse_int, return_dtype=pl.Int64).alias("race_seq_num"),
            pl.col("time").map_elements(_parse_time_seconds, return_dtype=pl.Float64).alias("time_sec"),
            pl.struct(["season_text", "date"])
            .map_elements(
                lambda row: _parse_year(row.get("season_text"), row.get("date")),
                return_dtype=pl.Int64,
            )
            .alias("season_year"),
            pl.struct(["round", "round_kind"])
            .map_elements(lambda row: _classify_round(_norm(row["round"]), _norm(row["round_kind"])), return_dtype=pl.Utf8)
            .alias("round_class"),
            pl.struct(["event", "round", "round_kind", "meet_name", "category"])
            .map_elements(
                lambda row: _is_relay(
                    _norm(row["event"]),
                    _norm(row["round"]),
                    _norm(row["round_kind"]),
                    _norm(row["meet_name"]),
                    _norm(row["category"]),
                ),
                return_dtype=pl.Boolean,
            )
            .alias("is_relay"),
            pl.col("category").map_elements(_is_hobby_division, return_dtype=pl.Boolean).alias("is_hobby"),
            # 원천에 성별 컬럼이 없으면(records_full.csv) 종별 접두사에서 복원합니다.
            pl.struct(["category", "gender"])
            .map_elements(lambda row: resolve_gender(row["category"], row["gender"]), return_dtype=pl.Utf8)
            .alias("gender"),
            pl.struct(["category", "gender"])
            .map_elements(lambda row: division_key(row["category"], row["gender"]), return_dtype=pl.Utf8)
            .alias("division"),
            pl.struct(["division_text", "category", "gender"])
            .map_elements(
                lambda row: resolve_division_text(row.get("division_text"), row.get("category"), row.get("gender")),
                return_dtype=pl.Utf8,
            )
            .alias("division_text"),
            pl.col("birth_year").map_elements(_parse_birth_year, return_dtype=pl.Int64).alias("birth_year"),
            pl.struct(["class_cd", "meet_name", "round", "round_kind"])
            .map_elements(
                lambda row: _classify_class_cd(
                    _norm(row["class_cd"]),
                    _norm(row["meet_name"]),
                    _norm(row["round"]),
                    _norm(row["round_kind"]),
                ),
                return_dtype=pl.Utf8,
            )
            .alias("class_cd_resolved"),
        ]
    )
    reconstructed = pl.struct(
        [
            "meet_id",
            "meet_name",
            "season_text",
            "event",
            "category",
            "gender",
            "distance_text",
            "round",
            "round_kind",
            "sf_flag",
            "date",
        ]
    ).map_elements(
        _build_reconstructed_race_id,
        return_dtype=pl.Utf8,
    )
    return base.with_columns(
        pl.when(pl.col("race_id") == "").then(reconstructed).otherwise(pl.col("race_id")).alias("race_id")
    )


def _prepare_rows_for_policy(results: pl.DataFrame, policy: ExtractionPolicy) -> tuple[pl.DataFrame, pl.DataFrame, dict[str, Any]]:
    canonical = _canonicalize_results(results)
    work = canonical.filter(pl.col("athlete_id") != "").filter(pl.col("race_id") != "")
    work = work.filter(pl.col("class_cd_resolved") == SHORTTRACK_CLASS_CD)
    work = work.filter(~pl.col("is_relay"))
    work = work.filter(pl.col("round_class") != "score")
    work = work.filter(pl.col("season_year").is_not_null() & (pl.col("season_year") >= int(policy.min_season)))
    if policy.exclude_hobby_divisions:
        work = work.filter(~pl.col("is_hobby"))
    work = work.with_columns(
        pl.struct(["status_raw", "advanced_raw", "place_num", "time_sec"])
        .map_elements(
            lambda row: _normalize_status(
                _norm(row["status_raw"]),
                _norm(row["advanced_raw"]),
                row.get("place_num"),
                row.get("time_sec"),
            ),
            return_dtype=pl.Utf8,
        )
        .alias("status_norm")
    )
    _ensure_no_unknown_status(work)

    rounds = list(sorted(policy.include_rounds))
    policy_rows = work.filter(pl.col("round_class").is_in(rounds))
    policy_rows = policy_rows.with_columns(
        pl.col("round_class")
        .map_elements(lambda value: float(policy.round_weights.get(_norm(value), 1.0)), return_dtype=pl.Float64)
        .alias("round_weight")
    )
    policy_rows = policy_rows.sort(["race_id", "athlete_id", "place_num", "time_sec"], nulls_last=True).unique(
        subset=["race_id", "athlete_id"],
        keep="first",
        maintain_order=True,
    )
    diagnostics = {
        "input_rows": int(results.height),
        "rows_after_structural_filters": int(work.height),
        "rows_after_policy_round_filter": int(policy_rows.height),
        "race_count_after_policy_round_filter": int(policy_rows["race_id"].n_unique()) if not policy_rows.is_empty() else 0,
    }
    return work, policy_rows, diagnostics


def _add_comparison_row(out_rows: list[dict[str, Any]], winner: dict[str, Any], loser: dict[str, Any], loser_place: int | None) -> None:
    winner_place = winner.get("effective_place")
    out_rows.append(
        {
            "race_id": _norm(winner.get("race_id")),
            "winner_id": _norm(winner.get("athlete_id")),
            "loser_id": _norm(loser.get("athlete_id")),
            "winner_place": int(winner_place) if winner_place is not None else None,
            "loser_place": int(loser_place) if loser_place is not None else None,
            "winner_status": _norm(winner.get("status_norm")),
            "loser_status": _norm(loser.get("status_norm")),
            "source_status": f"{_norm(winner.get('status_norm'))}-{_norm(loser.get('status_norm'))}",
            "round": _norm(winner.get("round")),
            "round_kind": _norm(winner.get("round_kind")),
            "round_class": _norm(winner.get("round_class")),
            "season_year": int(winner.get("season_year")) if winner.get("season_year") is not None else None,
            "weight": float(winner.get("round_weight") or 1.0),
        }
    )


def _status_filtered_participants(rows: list[dict[str, Any]], policy: ExtractionPolicy) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    active_rows: list[dict[str, Any]] = []
    dnf_rows: list[dict[str, Any]] = []

    base_max_place = max((int(row["place_num"]) for row in rows if row.get("place_num") is not None), default=0)
    penalty_place = base_max_place + 1

    for row in rows:
        status = _norm(row.get("status_norm"))
        if status == STATUS_DNS:
            continue
        if status == STATUS_ADV and policy.advanced == "exclude":
            continue
        if status == STATUS_PEN:
            if policy.penalty == "exclude":
                continue
            copied = dict(row)
            copied["effective_place"] = penalty_place
            penalty_place += 1
            active_rows.append(copied)
            continue
        if status == STATUS_DNF:
            if policy.dnf == "exclude":
                continue
            copied = dict(row)
            copied["effective_place"] = None
            dnf_rows.append(copied)
            active_rows.append(copied)
            continue
        copied = dict(row)
        place = copied.get("place_num")
        copied["effective_place"] = int(place) if place is not None and int(place) > 0 else None
        active_rows.append(copied)

    ranked = [
        row
        for row in active_rows
        if row.get("effective_place") is not None and _norm(row.get("status_norm")) in {STATUS_FIN, STATUS_ADV, STATUS_PEN}
    ]
    ranked.sort(
        key=lambda row: (
            int(row.get("effective_place")),
            math.inf if row.get("time_sec") is None else float(row.get("time_sec")),
            _norm(row.get("athlete_id")),
        )
    )
    finishers = [row for row in ranked if _norm(row.get("status_norm")) in {STATUS_FIN, STATUS_ADV}]
    return ranked, dnf_rows, finishers


def _build_comparisons(rows: pl.DataFrame, policy: ExtractionPolicy) -> pl.DataFrame:
    if rows.is_empty():
        return pl.DataFrame(
            schema={
                "race_id": pl.Utf8,
                "winner_id": pl.Utf8,
                "loser_id": pl.Utf8,
                "winner_place": pl.Int64,
                "loser_place": pl.Int64,
                "winner_status": pl.Utf8,
                "loser_status": pl.Utf8,
                "source_status": pl.Utf8,
                "round": pl.Utf8,
                "round_kind": pl.Utf8,
                "round_class": pl.Utf8,
                "season_year": pl.Int64,
                "weight": pl.Float64,
            }
        )

    out_rows: list[dict[str, Any]] = []
    for race in rows.partition_by("race_id", maintain_order=True):
        race_rows = race.to_dicts()
        if len(race_rows) < 2:
            continue
        ranked, dnf_rows, finishers = _status_filtered_participants(race_rows, policy)

        for left_index in range(len(ranked)):
            winner = ranked[left_index]
            for right_index in range(left_index + 1, len(ranked)):
                loser = ranked[right_index]
                winner_place = winner.get("effective_place")
                loser_place = loser.get("effective_place")
                if winner_place is None or loser_place is None:
                    continue
                if int(winner_place) == int(loser_place):
                    continue
                _add_comparison_row(out_rows, winner, loser, int(loser_place))

        if policy.dnf == "loss_to_finishers":
            for loser in dnf_rows:
                for winner in finishers:
                    _add_comparison_row(out_rows, winner, loser, None)

    if not out_rows:
        return pl.DataFrame(
            schema={
                "race_id": pl.Utf8,
                "winner_id": pl.Utf8,
                "loser_id": pl.Utf8,
                "winner_place": pl.Int64,
                "loser_place": pl.Int64,
                "winner_status": pl.Utf8,
                "loser_status": pl.Utf8,
                "source_status": pl.Utf8,
                "round": pl.Utf8,
                "round_kind": pl.Utf8,
                "round_class": pl.Utf8,
                "season_year": pl.Int64,
                "weight": pl.Float64,
            }
        )

    comparison_df = pl.DataFrame(out_rows)
    return comparison_df.sort(
        ["race_id", "winner_place", "loser_place", "winner_id", "loser_id", "source_status"],
        nulls_last=True,
    )


def extract_comparisons(results: pl.DataFrame, policy: ExtractionPolicy) -> pl.DataFrame:
    """Convert race result rows into pairwise comparisons under a policy."""
    _, prepared_rows, _ = _prepare_rows_for_policy(results, policy)
    return _build_comparisons(prepared_rows, policy)


def run_extraction(results: pl.DataFrame, policy: ExtractionPolicy) -> ExtractionRun:
    audited_rows, prepared_rows, diagnostics = _prepare_rows_for_policy(results, policy)
    comparisons = _build_comparisons(prepared_rows, policy)
    diagnostics["comparison_row_count"] = int(comparisons.height)
    diagnostics["comparison_race_count"] = int(comparisons["race_id"].n_unique()) if not comparisons.is_empty() else 0
    status_audit = _build_status_audit(audited_rows)
    return ExtractionRun(
        comparisons=comparisons,
        prepared_rows=prepared_rows,
        status_audit=status_audit,
        diagnostics=diagnostics,
    )


def render_status_audit_markdown(audit: pl.DataFrame, diagnostics: dict[str, Any], input_path: Path) -> str:
    lines = [
        "# R-02 status 코드 감사",
        "",
        f"- 생성시각: {datetime.now().isoformat(timespec='seconds')}",
        f"- 입력 파일: `{input_path}`",
        f"- 구조 필터 후 행수: **{int(diagnostics.get('rows_after_structural_filters') or 0):,}**",
        "",
        "| 원천 status | 정규화 | 행수 | 선수수 | 비율(%) | 희귀(<1%) | 처리 방침 |",
        "| --- | --- | ---: | ---: | ---: | --- | --- |",
    ]
    for row in audit.to_dicts():
        raw = _norm(row.get("status_raw")) or "(blank)"
        lines.append(
            "| "
            + " | ".join(
                [
                    raw,
                    _norm(row.get("status_norm")),
                    f"{int(row.get('row_count') or 0):,}",
                    f"{int(row.get('athlete_count') or 0):,}",
                    f"{float(row.get('ratio_pct') or 0.0):.3f}",
                    _norm(row.get("rare_under_1pct")),
                    _norm(row.get("handling")),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 메모",
            "",
            "- `UNKNOWN` 정규화 코드는 허용하지 않으며, 발견 시 즉시 예외를 발생시킵니다.",
            "- `ADV`는 `DNF` 묶음으로 합치지 않고 독립 코드로 처리합니다.",
            "- `records_full.csv`를 기본 입력으로 사용합니다 (`records_anon.csv`의 `사유`는 공백).",
        ]
    )
    return "\n".join(lines) + "\n"


def load_results_csv(path: Path) -> pl.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"[error] 입력 파일이 없습니다: {path}")
    return pl.read_csv(path, encoding="utf8-lossy", infer_schema_length=0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="라운드/실격 정책 기반 pairwise 비교를 생성합니다.")
    parser.add_argument("--results", required=True, help="입력 CSV 경로")
    parser.add_argument("--policy", default="conservative", choices=sorted(POLICIES.keys()), help="정책 프리셋")
    parser.add_argument("--out", required=True, help="비교 parquet 출력 경로")
    parser.add_argument("--status-audit-out", default="out/status_audit.md", help="status 감사 Markdown 출력 경로")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    results_path = Path(args.results).expanduser()
    out_path = Path(args.out).expanduser()
    audit_path = Path(args.status_audit_out).expanduser()
    policy = get_policy(args.policy)

    results = load_results_csv(results_path)
    run = run_extraction(results, policy)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    run.comparisons.write_parquet(out_path)

    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(render_status_audit_markdown(run.status_audit, run.diagnostics, results_path), encoding="utf-8")

    print(f"[ok] policy={args.policy}")
    print(f"[ok] prepared_rows={run.prepared_rows.height:,}")
    print(f"[ok] comparisons={run.comparisons.height:,}")
    print(f"[ok] out={out_path}")
    print(f"[ok] status_audit={audit_path}")


if __name__ == "__main__":
    main()
