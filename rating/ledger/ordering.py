from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Mapping

import polars as pl

from .policies import ROUND_FINAL, ROUND_FINAL_B, ROUND_HEAT, ROUND_OTHER, ROUND_QUARTERFINAL, ROUND_SEMIFINAL
from .season import race_date_token

_HEAT_NUMBER_RE = re.compile(r"(\d+)\s*조|heat\s*([0-9]+)", re.IGNORECASE)
_ROUND_ORDER = {
    ROUND_HEAT: 1,
    ROUND_QUARTERFINAL: 2,
    ROUND_SEMIFINAL: 3,
    ROUND_FINAL_B: 4,
    ROUND_FINAL: 5,
    ROUND_OTHER: 9,
}


def _norm(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"", "none", "nan"}:
        return ""
    return text


def _clean_piece(value: Any) -> str:
    return _norm(value).replace("|", "/")


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


def _extract_heat_no(round_text: Any) -> int:
    match = _HEAT_NUMBER_RE.search(_norm(round_text))
    if not match:
        return 0
    parsed = _parse_int(match.group(1) or match.group(2))
    return int(parsed or 0)


def _race_sort_seed(race_row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        _clean_piece(race_row.get("event")),
        int(_ROUND_ORDER.get(_norm(race_row.get("round_class")), 99)),
        _extract_heat_no(race_row.get("round")),
        _clean_piece(race_row.get("round_kind")),
        _clean_piece(race_row.get("distance_text")),
        _clean_piece(race_row.get("race_id")),
    )


def _format_race_seq(value: Any) -> str:
    parsed = _parse_int(value)
    if parsed is None or parsed <= 0:
        return "0000"
    return f"{int(parsed):04d}"


def _format_rank(value: Any) -> str:
    parsed = _parse_int(value)
    if parsed is None or parsed <= 0:
        return "0000"
    return f"{int(parsed):04d}"


def build_race_sequence_map(rows: pl.DataFrame) -> dict[str, int]:
    if rows.is_empty():
        return {}

    race_meta = (
        rows.select(
            [
                "race_id",
                "race_seq_num",
                "date",
                "season_year",
                "meet_id",
                "event",
                "round",
                "round_kind",
                "round_class",
                "distance_text",
            ]
        )
        .sort(["race_id", "race_seq_num", "event", "round", "round_kind"], nulls_last=True)
        .unique(subset=["race_id"], keep="first", maintain_order=True)
    )

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in race_meta.to_dicts():
        season_fallback = row.get("season_year")
        if season_fallback is not None:
            season_fallback = int(season_fallback)
        date_key = race_date_token(row.get("date"), fallback_year=season_fallback)
        meet_key = _clean_piece(row.get("meet_id")) or "-"
        grouped[(date_key, meet_key)].append(row)

    race_seq_map: dict[str, int] = {}
    for group_rows in grouped.values():
        sorted_rows = sorted(group_rows, key=_race_sort_seed)
        used: set[int] = set()

        for row in sorted_rows:
            race_id = _clean_piece(row.get("race_id"))
            if not race_id:
                continue
            explicit = row.get("race_seq_num")
            if explicit is None:
                continue
            seq = int(explicit)
            if seq <= 0 or seq in used:
                continue
            race_seq_map[race_id] = seq
            used.add(seq)

        next_seq = 1
        for row in sorted_rows:
            race_id = _clean_piece(row.get("race_id"))
            if not race_id or race_id in race_seq_map:
                continue
            while next_seq in used:
                next_seq += 1
            race_seq_map[race_id] = next_seq
            used.add(next_seq)

    return race_seq_map


def make_race_ordering_key(row: Mapping[str, Any]) -> str:
    date_key = _clean_piece(row.get("race_date"))
    if not re.fullmatch(r"\d{8}", date_key):
        season_fallback = row.get("season_year")
        if season_fallback is not None:
            season_fallback = int(season_fallback)
        date_key = race_date_token(row.get("date"), fallback_year=season_fallback)
    meet_key = _clean_piece(row.get("meet_id")) or "-"
    race_key = _clean_piece(row.get("race_id")) or "-"
    race_seq = _format_race_seq(row.get("race_seq"))
    return f"{date_key}|{meet_key}|{race_seq}|{race_key}"


def make_ordering_key(row: Mapping[str, Any]) -> str:
    race_prefix = make_race_ordering_key(row)
    rank = _format_rank(row.get("rank"))
    athlete_key = _clean_piece(row.get("athlete_id")) or "-"
    return f"{race_prefix}|{rank}|{athlete_key}"


def make_pairwise_ordering_key(row: Mapping[str, Any]) -> str:
    race_prefix = make_race_ordering_key(row)
    winner_key = _clean_piece(row.get("winner_id")) or "-"
    loser_key = _clean_piece(row.get("loser_id")) or "-"
    return f"{race_prefix}|{winner_key}|{loser_key}"
