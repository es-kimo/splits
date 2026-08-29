from __future__ import annotations

import argparse
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from itertools import combinations
from pathlib import Path
from typing import Any

import networkx as nx
import pandas as pd

SHORTTRACK_CLASS_CD = "2"
GO_GIANT_COMPONENT_MIN = 0.90
CONDITIONAL_GO_GIANT_COMPONENT_MIN = 0.70
ISOLATED_CELL_WARN_RATIO = 0.05
RELAY_RE = re.compile(r"(릴레이|relay|계주)", re.IGNORECASE)
HEAT_NUMBER_RE = re.compile(r"(\d+)\s*조|heat\s*([0-9]+)", re.IGNORECASE)
FINISHED_STATUS_ALLOW = {"", "ok", "finished", "finish", "완주", "정상완주"}
FINISHED_STATUS_DENY_TOKENS = [
    "dnf",
    "dns",
    "dq",
    "disq",
    "disqualified",
    "ret",
    "withdraw",
    "실격",
    "기권",
    "포기",
    "미출전",
    "실패",
    "부정출발",
]

ALIASES = {
    "meet_id": ["meet_id", "toCd"],
    "race_id": ["race_id"],
    "athlete_id": ["athlete_hash", "익명키", "idNo"],
    "event": ["event", "세부종목"],
    "round": ["round", "라운드"],
    "round_kind": ["round_kind", "라운드종류"],
    "place": ["place", "순위"],
    "time": ["time", "기록_초", "기록"],
    "status": ["status", "사유"],
    "season": ["season", "season_year", "대회연도"],
    "grade": ["grade", "학년", "학년_계산"],
    "gender": ["gender", "성별"],
    "class_cd": ["class_cd", "classCd"],
    "meet_name": ["meet_name", "대회명"],
    "category": ["category", "종별"],
    "distance": ["distance", "거리"],
    "date": ["date", "일자"],
}


@dataclass
class PreparedResults:
    rows: pd.DataFrame
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass
class ConnectivityReport:
    generated_at: str
    overall: dict[str, Any]
    season: dict[str, Any]
    grade: dict[str, Any]
    vertical: dict[str, Any]
    observation: dict[str, Any]
    decision: str
    decision_reason: str
    preparation: dict[str, Any] = field(default_factory=dict)


def _norm(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str) and pd.isna(value):
        return ""
    return str(value).strip()


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


def _parse_grade_text(value: Any) -> str:
    return _norm(value).replace(" ", "")


def _parse_grade_number(value: Any) -> int | None:
    text = _parse_grade_text(value)
    if not text:
        return None
    nums = re.findall(r"\d+", text)
    if not nums:
        return None
    uniq = sorted(set(nums))
    if len(uniq) == 1:
        try:
            return int(uniq[0])
        except ValueError:
            return None
    return None


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    series = pd.Series(values, dtype=float)
    return float(series.quantile(q))


def _safe_ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return float(numerator) / float(denominator)


def _is_finished_status(value: Any) -> bool:
    text = _norm(value).lower()
    if text in FINISHED_STATUS_ALLOW:
        return True
    if any(token in text for token in FINISHED_STATUS_DENY_TOKENS):
        return False
    return False


def _is_score_round(round_text: str, round_kind: str) -> bool:
    return "채점종합" in _norm(round_kind) or "채점종합" in _norm(round_text)


def _has_relay_token(*values: Any) -> bool:
    for value in values:
        if RELAY_RE.search(_norm(value)):
            return True
    return False


def _extract_heat_no(round_text: str) -> str:
    match = HEAT_NUMBER_RE.search(_norm(round_text))
    if not match:
        return ""
    return _norm(match.group(1) or match.group(2))


def _first_existing_column(frame: pd.DataFrame, candidates: list[str]) -> str | None:
    for name in candidates:
        if name in frame.columns:
            return name
    return None


def _read_alias_series(frame: pd.DataFrame, key: str) -> pd.Series:
    col = _first_existing_column(frame, ALIASES[key])
    if col is None:
        return pd.Series([""] * len(frame), index=frame.index, dtype=str)
    return frame[col].fillna("").astype(str).map(_norm)


def _clean_key_piece(value: Any) -> str:
    return _norm(value).replace("|", "/")


def _event_key(event: str, category: str, distance: str) -> str:
    event_text = _norm(event)
    if event_text:
        return event_text
    category_text = _norm(category)
    distance_text = _norm(distance)
    if category_text and distance_text:
        return f"{category_text}-{distance_text}m"
    return category_text or distance_text


def _build_reconstructed_race_id(row: pd.Series) -> str:
    meet_id = _clean_key_piece(row.get("meet_id"))
    if not meet_id:
        meet_name = _clean_key_piece(row.get("meet_name"))
        season = _clean_key_piece(row.get("season_text"))
        if meet_name or season:
            meet_id = f"{season}:{meet_name}"
    event = _event_key(row.get("event", ""), row.get("category", ""), row.get("distance_text", ""))
    round_text = _norm(row.get("round")) or _norm(row.get("round_kind"))
    heat_no = _extract_heat_no(round_text)
    date_text = _clean_key_piece(row.get("date")) or "-"
    if not (meet_id and event and round_text):
        return ""
    return "|".join(
        [
            _clean_key_piece(meet_id),
            _clean_key_piece(event),
            _clean_key_piece(round_text),
            _clean_key_piece(heat_no) or "-",
            _clean_key_piece(date_text),
        ]
    )


def _canonicalize_results(frame: pd.DataFrame) -> pd.DataFrame:
    base = pd.DataFrame(
        {
            "meet_id": _read_alias_series(frame, "meet_id"),
            "race_id": _read_alias_series(frame, "race_id"),
            "athlete_id": _read_alias_series(frame, "athlete_id"),
            "event": _read_alias_series(frame, "event"),
            "round": _read_alias_series(frame, "round"),
            "round_kind": _read_alias_series(frame, "round_kind"),
            "place": _read_alias_series(frame, "place"),
            "time": _read_alias_series(frame, "time"),
            "status": _read_alias_series(frame, "status"),
            "season_text": _read_alias_series(frame, "season"),
            "grade_text": _read_alias_series(frame, "grade").map(_parse_grade_text),
            "gender": _read_alias_series(frame, "gender"),
            "class_cd": _read_alias_series(frame, "class_cd"),
            "meet_name": _read_alias_series(frame, "meet_name"),
            "category": _read_alias_series(frame, "category"),
            "distance_text": _read_alias_series(frame, "distance"),
            "date": _read_alias_series(frame, "date"),
        }
    )
    base["event"] = [
        _event_key(event, category, distance)
        for event, category, distance in zip(base["event"], base["category"], base["distance_text"])
    ]
    base["season_year"] = pd.to_numeric(base["season_text"].map(_parse_int), errors="coerce").astype("Int64")
    base["grade_num"] = pd.to_numeric(base["grade_text"].map(_parse_grade_number), errors="coerce").astype("Int64")
    base["place_num"] = pd.to_numeric(base["place"].map(_parse_int), errors="coerce").astype("Int64")
    base["time_sec"] = pd.to_numeric(base["time"].map(_parse_time_seconds), errors="coerce")
    return base


def _race_size_stats(values: list[int]) -> dict[str, Any]:
    if not values:
        return {
            "race_count": 0,
            "race_size_min": 0,
            "race_size_p10": 0.0,
            "race_size_p50": 0.0,
            "race_size_p90": 0.0,
            "race_size_max": 0,
            "race_size_4_to_6_ratio": 0.0,
        }
    as_float = [float(v) for v in values]
    in_range = sum(1 for v in values if 4 <= v <= 6)
    return {
        "race_count": len(values),
        "race_size_min": int(min(values)),
        "race_size_p10": _percentile(as_float, 0.10) or 0.0,
        "race_size_p50": _percentile(as_float, 0.50) or 0.0,
        "race_size_p90": _percentile(as_float, 0.90) or 0.0,
        "race_size_max": int(max(values)),
        "race_size_4_to_6_ratio": _safe_ratio(in_range, len(values)),
    }


def prepare_results(results: pd.DataFrame) -> PreparedResults:
    frame = _canonicalize_results(results)
    diagnostics: dict[str, Any] = {"total_rows": int(len(frame))}

    provided_race_mask = frame["race_id"].map(_norm) != ""
    provided_race_rows = int(provided_race_mask.sum())
    diagnostics["race_id_provided_rows"] = provided_race_rows
    diagnostics["race_id_source"] = "provided" if provided_race_rows == len(frame) else "reconstructed"

    reconstructed_ids = frame.apply(_build_reconstructed_race_id, axis=1)
    missing_race_mask = ~provided_race_mask
    frame.loc[missing_race_mask, "race_id"] = reconstructed_ids[missing_race_mask]
    diagnostics["race_id_reconstructed_rows"] = int(missing_race_mask.sum())
    diagnostics["race_id_missing_rows_after_reconstruction"] = int((frame["race_id"] == "").sum())

    work = frame.copy()

    athlete_missing = work["athlete_id"] == ""
    diagnostics["excluded_missing_athlete_rows"] = int(athlete_missing.sum())
    work = work[~athlete_missing].copy()

    race_missing = work["race_id"] == ""
    diagnostics["excluded_missing_race_rows"] = int(race_missing.sum())
    work = work[~race_missing].copy()

    has_class_cd = bool((work["class_cd"] != "").any())
    if has_class_cd:
        non_shorttrack = work["class_cd"] != SHORTTRACK_CLASS_CD
        diagnostics["excluded_non_shorttrack_rows"] = int(non_shorttrack.sum())
        work = work[~non_shorttrack].copy()
    else:
        diagnostics["excluded_non_shorttrack_rows"] = 0

    score_round_mask = [
        _is_score_round(round_text, round_kind)
        for round_text, round_kind in zip(work["round"].tolist(), work["round_kind"].tolist())
    ]
    diagnostics["excluded_score_round_rows"] = int(sum(score_round_mask))
    work = work[[not flag for flag in score_round_mask]].copy()

    relay_mask = [
        _has_relay_token(event, round_text, round_kind, meet_name, category)
        for event, round_text, round_kind, meet_name, category in zip(
            work["event"].tolist(),
            work["round"].tolist(),
            work["round_kind"].tolist(),
            work["meet_name"].tolist(),
            work["category"].tolist(),
        )
    ]
    diagnostics["excluded_relay_rows"] = int(sum(relay_mask))
    work = work[[not flag for flag in relay_mask]].copy()

    finished_status_mask = work["status"].map(_is_finished_status)
    finisher_mask = work["place_num"].notna() & work["time_sec"].notna() & finished_status_mask
    diagnostics["excluded_non_finisher_rows"] = int((~finisher_mask).sum())
    work = work[finisher_mask].copy()

    before_dedup = int(len(work))
    work = work.sort_values(["race_id", "athlete_id", "place_num", "time_sec"], na_position="last").drop_duplicates(
        subset=["race_id", "athlete_id"], keep="first"
    )
    diagnostics["deduplicated_athlete_race_rows"] = before_dedup - int(len(work))

    race_sizes = work.groupby("race_id", dropna=False)["athlete_id"].nunique().astype(int).tolist() if not work.empty else []
    diagnostics.update(_race_size_stats(race_sizes))

    diagnostics["rows_after_filter"] = int(len(work))
    diagnostics["athlete_count_after_filter"] = int(work["athlete_id"].nunique()) if not work.empty else 0
    diagnostics["race_count_after_filter"] = int(work["race_id"].nunique()) if not work.empty else 0

    out_cols = [
        "race_id",
        "athlete_id",
        "meet_id",
        "event",
        "round",
        "round_kind",
        "place_num",
        "time_sec",
        "status",
        "season_text",
        "season_year",
        "grade_text",
        "grade_num",
        "gender",
        "class_cd",
        "meet_name",
        "category",
        "distance_text",
        "date",
    ]
    out = work[out_cols].reset_index(drop=True)
    out.attrs["preparation_diagnostics"] = diagnostics
    return PreparedResults(rows=out, diagnostics=diagnostics)


def _build_graph_from_rows(rows: pd.DataFrame) -> nx.Graph:
    graph = nx.Graph()
    if rows.empty:
        return graph
    grouped = rows.groupby("race_id", dropna=False, sort=False)
    for _, group in grouped:
        athletes = sorted({_norm(value) for value in group["athlete_id"].tolist() if _norm(value)})
        if not athletes:
            continue
        graph.add_nodes_from(athletes)
        if len(athletes) < 2:
            continue
        for left, right in combinations(athletes, 2):
            if graph.has_edge(left, right):
                graph[left][right]["weight"] += 1
            else:
                graph.add_edge(left, right, weight=1)
    return graph


def build_graph(results: pd.DataFrame) -> nx.Graph:
    if "race_id" not in results.columns or "athlete_id" not in results.columns:
        prepared = prepare_results(results)
        return _build_graph_from_rows(prepared.rows)
    return _build_graph_from_rows(results)


def _distribution_summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "mean": 0.0, "p10": 0.0, "p50": 0.0, "p90": 0.0}
    return {
        "count": len(values),
        "mean": float(sum(values) / len(values)),
        "p10": _percentile(values, 0.10) or 0.0,
        "p50": _percentile(values, 0.50) or 0.0,
        "p90": _percentile(values, 0.90) or 0.0,
    }


def _component_metrics(graph: nx.Graph) -> dict[str, Any]:
    node_count = graph.number_of_nodes()
    edge_count = graph.number_of_edges()
    if node_count == 0:
        return {
            "node_count": 0,
            "edge_count": 0,
            "component_count": 0,
            "largest_component_size": 0,
            "largest_component_ratio": 0.0,
            "degree_mean": 0.0,
            "degree_p10": 0.0,
            "degree_p50": 0.0,
        }
    components = [len(component) for component in nx.connected_components(graph)]
    largest = max(components) if components else 0
    degrees = [float(deg) for _, deg in graph.degree()]
    dist = _distribution_summary(degrees)
    return {
        "node_count": int(node_count),
        "edge_count": int(edge_count),
        "component_count": int(len(components)),
        "largest_component_size": int(largest),
        "largest_component_ratio": _safe_ratio(int(largest), int(node_count)),
        "degree_mean": dist["mean"],
        "degree_p10": dist["p10"],
        "degree_p50": dist["p50"],
    }


def _build_season_metrics(meta: pd.DataFrame) -> dict[str, Any]:
    base = meta[meta["season_year"].notna()].copy()
    if base.empty:
        return {"per_season": [], "bridge_athlete_count": 0, "bridge_athlete_ratio": 0.0}

    season_rows = []
    for season, group in base.groupby("season_year", sort=True):
        season_graph = _build_graph_from_rows(group)
        metrics = _component_metrics(season_graph)
        metrics["season"] = int(season)
        season_rows.append(metrics)

    athlete_per_season = base[["athlete_id", "season_year"]].drop_duplicates()
    season_counts = athlete_per_season.groupby("athlete_id", sort=False)["season_year"].nunique()
    bridge_count = int((season_counts >= 2).sum()) if not season_counts.empty else 0
    athlete_total = int(len(season_counts))
    return {
        "per_season": season_rows,
        "bridge_athlete_count": bridge_count,
        "bridge_athlete_ratio": _safe_ratio(bridge_count, athlete_total),
        "athlete_with_season_count": athlete_total,
    }


def _build_grade_meta_graph(base: pd.DataFrame) -> nx.Graph:
    graph = nx.Graph()
    for _, race in base.groupby("race_id", sort=False):
        grades = sorted({value for value in race["grade_text"].tolist() if value})
        for grade in grades:
            graph.add_node(grade)
        if len(grades) < 2:
            continue
        for left, right in combinations(grades, 2):
            if graph.has_edge(left, right):
                graph[left][right]["weight"] += 1
            else:
                graph.add_edge(left, right, weight=1)
    return graph


def _build_grade_metrics(meta: pd.DataFrame) -> dict[str, Any]:
    base = meta[(meta["season_year"].notna()) & (meta["grade_text"] != "") & (meta["gender"] != "")].copy()
    if base.empty:
        return {
            "cell_count": 0,
            "cell_athlete_p10": 0.0,
            "cell_athlete_p50": 0.0,
            "mixed_grade_race_count": 0,
            "grade_meta_node_count": 0,
            "grade_meta_edge_count": 0,
            "grade_meta_component_count": 0,
            "grade_meta_edges": [],
            "grade_meta_nodes": [],
            "top_cells": [],
        }

    cell_table = (
        base.groupby(["season_year", "grade_text", "gender"], dropna=False)["athlete_id"]
        .nunique()
        .reset_index(name="athlete_count")
        .sort_values(["season_year", "grade_text", "gender"], ascending=[True, True, True])
    )
    cell_sizes = [float(value) for value in cell_table["athlete_count"].tolist()]
    mixed_grade_count = 0
    for _, race in base.groupby("race_id", sort=False):
        grades = {value for value in race["grade_text"].tolist() if value}
        if len(grades) >= 2:
            mixed_grade_count += 1

    grade_graph = _build_grade_meta_graph(base)
    edge_rows = sorted(
        [{"left": left, "right": right, "shared_race_count": int(data.get("weight", 0))} for left, right, data in grade_graph.edges(data=True)],
        key=lambda item: (-item["shared_race_count"], item["left"], item["right"]),
    )
    component_count = nx.number_connected_components(grade_graph) if grade_graph.number_of_nodes() else 0

    top_cells = []
    for _, row in cell_table.sort_values("athlete_count", ascending=False).head(20).iterrows():
        top_cells.append(
            {
                "season": int(row["season_year"]),
                "grade": _norm(row["grade_text"]),
                "gender": _norm(row["gender"]),
                "athlete_count": int(row["athlete_count"]),
            }
        )

    return {
        "cell_count": int(len(cell_table)),
        "cell_athlete_p10": _percentile(cell_sizes, 0.10) or 0.0,
        "cell_athlete_p50": _percentile(cell_sizes, 0.50) or 0.0,
        "mixed_grade_race_count": int(mixed_grade_count),
        "grade_meta_node_count": int(grade_graph.number_of_nodes()),
        "grade_meta_edge_count": int(grade_graph.number_of_edges()),
        "grade_meta_component_count": int(component_count),
        "grade_meta_edges": edge_rows,
        "grade_meta_nodes": sorted(_norm(node) for node in grade_graph.nodes()),
        "top_cells": top_cells,
    }


def _build_vertical_metrics(meta: pd.DataFrame) -> dict[str, Any]:
    base = meta[(meta["season_year"].notna()) & (meta["grade_num"].notna())].copy()
    if base.empty:
        return {
            "longitudinal_athlete_count": 0,
            "longitudinal_athlete_ratio": 0.0,
            "comparable_cell_count": 0,
            "isolated_cell_count": 0,
            "shared_athlete_min": 0,
            "shared_athlete_p10": 0.0,
            "shared_athlete_p50": 0.0,
            "isolated_athlete_ratio": 0.0,
            "cell_bridge_rows": [],
            "isolated_cells": [],
        }

    base["season_year"] = pd.to_numeric(base["season_year"], errors="coerce").astype("Int64")
    base["grade_num"] = pd.to_numeric(base["grade_num"], errors="coerce").astype("Int64")
    unique_entries = base[["athlete_id", "season_year", "grade_num"]].drop_duplicates()

    cell_map: dict[tuple[int, int], set[str]] = defaultdict(set)
    for _, row in unique_entries.iterrows():
        season = int(row["season_year"])
        grade = int(row["grade_num"])
        athlete = _norm(row["athlete_id"])
        if athlete:
            cell_map[(season, grade)].add(athlete)

    bridge_rows = []
    isolated_cells = []
    isolated_athletes: set[str] = set()
    shared_values = []

    for season, grade in sorted(cell_map.keys()):
        current = cell_map[(season, grade)]
        prev = cell_map.get((season - 1, grade - 1), set())
        shared = len(current.intersection(prev))
        comparable = len(prev) > 0
        if comparable:
            shared_values.append(float(shared))
        is_isolated = comparable and shared == 0
        if is_isolated:
            isolated_cells.append({"season": season, "grade": grade, "athlete_count": len(current)})
            isolated_athletes.update(current)
        bridge_rows.append(
            {
                "season": season,
                "grade": grade,
                "athlete_count": len(current),
                "prev_cell_athlete_count": len(prev),
                "shared_athlete_count": shared,
                "comparable_prev_cell": "Y" if comparable else "N",
                "isolated": "Y" if is_isolated else "N",
            }
        )

    long_bridge_athletes = 0
    athlete_groups = unique_entries.groupby("athlete_id", sort=False)
    for _, group in athlete_groups:
        pairs = sorted({(int(s), int(g)) for s, g in zip(group["season_year"], group["grade_num"])})
        has_bridge = any(next_s == prev_s + 1 and next_g == prev_g + 1 for (prev_s, prev_g), (next_s, next_g) in zip(pairs, pairs[1:]))
        if has_bridge:
            long_bridge_athletes += 1

    athlete_total = int(unique_entries["athlete_id"].nunique())
    return {
        "longitudinal_athlete_count": int(long_bridge_athletes),
        "longitudinal_athlete_ratio": _safe_ratio(int(long_bridge_athletes), athlete_total),
        "comparable_cell_count": int(sum(1 for row in bridge_rows if row["comparable_prev_cell"] == "Y")),
        "isolated_cell_count": int(len(isolated_cells)),
        "shared_athlete_min": int(min(shared_values)) if shared_values else 0,
        "shared_athlete_p10": _percentile(shared_values, 0.10) or 0.0,
        "shared_athlete_p50": _percentile(shared_values, 0.50) or 0.0,
        "isolated_athlete_ratio": _safe_ratio(len(isolated_athletes), athlete_total),
        "cell_bridge_rows": bridge_rows,
        "isolated_cells": isolated_cells,
    }


def _build_observation_metrics(meta: pd.DataFrame) -> dict[str, Any]:
    if meta.empty:
        return {
            "pairwise_total": 0,
            "race_count": 0,
            "race_size_p10": 0.0,
            "race_size_p50": 0.0,
            "race_size_p90": 0.0,
            "athlete_pairwise_p10": 0.0,
            "athlete_pairwise_p50": 0.0,
            "athlete_pairwise_p90": 0.0,
        }

    pairwise_total = 0
    race_sizes: list[int] = []
    pairwise_by_athlete: dict[str, int] = defaultdict(int)

    for _, group in meta.groupby("race_id", sort=False):
        athletes = sorted({_norm(value) for value in group["athlete_id"].tolist() if _norm(value)})
        size = len(athletes)
        if size == 0:
            continue
        race_sizes.append(size)
        if size < 2:
            continue
        pair_count = math.comb(size, 2)
        pairwise_total += pair_count
        for athlete in athletes:
            pairwise_by_athlete[athlete] += size - 1

    athlete_pair_counts = [float(value) for value in pairwise_by_athlete.values()]
    race_sizes_float = [float(value) for value in race_sizes]
    return {
        "pairwise_total": int(pairwise_total),
        "race_count": int(len(race_sizes)),
        "race_size_p10": _percentile(race_sizes_float, 0.10) or 0.0,
        "race_size_p50": _percentile(race_sizes_float, 0.50) or 0.0,
        "race_size_p90": _percentile(race_sizes_float, 0.90) or 0.0,
        "athlete_pairwise_p10": _percentile(athlete_pair_counts, 0.10) or 0.0,
        "athlete_pairwise_p50": _percentile(athlete_pair_counts, 0.50) or 0.0,
        "athlete_pairwise_p90": _percentile(athlete_pair_counts, 0.90) or 0.0,
    }


def _decide(overall: dict[str, Any], vertical: dict[str, Any]) -> tuple[str, str]:
    giant_ratio = float(overall.get("largest_component_ratio") or 0.0)
    isolated_cell_count = int(vertical.get("isolated_cell_count") or 0)
    comparable_cell_count = int(vertical.get("comparable_cell_count") or 0)
    if giant_ratio >= GO_GIANT_COMPONENT_MIN and isolated_cell_count == 0 and comparable_cell_count > 0:
        return "GO", "거대 성분 비율이 90% 이상이고, 이전 시즌 대비 공유선수 0명인 (시즌,학년) 고립 셀이 없습니다."
    if giant_ratio >= GO_GIANT_COMPONENT_MIN and comparable_cell_count == 0:
        return "조건부 GO", "거대 성분 비율은 90% 이상이지만, 학년 연속성 비교 가능한 셀이 없어 종적 다리 강도를 추가 확인해야 합니다."
    if giant_ratio >= CONDITIONAL_GO_GIANT_COMPONENT_MIN:
        return "조건부 GO", "거대 성분 비율이 70~90% 구간이라 거대 성분 밖 선수/셀은 레이팅 미제공으로 분리 운영해야 합니다."
    return "STOP", "거대 성분 비율이 70% 미만이라 레이팅 비교 그래프의 전역 연결성이 부족합니다."


def analyze_connectivity(g: nx.Graph, meta: pd.DataFrame) -> ConnectivityReport:
    if "race_id" not in meta.columns or "athlete_id" not in meta.columns:
        prepared = prepare_results(meta)
        base = prepared.rows
        preparation = prepared.diagnostics
    else:
        base = meta.copy()
        preparation = dict(base.attrs.get("preparation_diagnostics") or {})

    overall = _component_metrics(g)
    season = _build_season_metrics(base)
    grade = _build_grade_metrics(base)
    vertical = _build_vertical_metrics(base)
    observation = _build_observation_metrics(base)
    decision, reason = _decide(overall, vertical)
    return ConnectivityReport(
        generated_at=datetime.now().isoformat(timespec="seconds"),
        overall=overall,
        season=season,
        grade=grade,
        vertical=vertical,
        observation=observation,
        decision=decision,
        decision_reason=reason,
        preparation=preparation,
    )


def _fmt_int(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "0"


def _fmt_plain_int(value: Any) -> str:
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return "0"


def _fmt_float(value: Any, digits: int = 2) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return f"{0.0:.{digits}f}"


def _fmt_pct_ratio(value: Any, digits: int = 2) -> str:
    try:
        return f"{float(value) * 100.0:.{digits}f}%"
    except (TypeError, ValueError):
        return f"{0.0:.{digits}f}%"


def _table(headers: list[str], rows: list[list[str]]) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return lines


def _render_grade_meta_mermaid(nodes: list[str], edges: list[dict[str, Any]]) -> str:
    if not nodes:
        return "_학년 메타 그래프를 그릴 데이터가 없습니다._"

    node_ids = {label: f"G{index + 1}" for index, label in enumerate(sorted(nodes))}
    lines = ["```mermaid", "graph LR"]
    for label in sorted(nodes):
        lines.append(f'  {node_ids[label]}["{label}"]')

    if edges:
        for item in edges[:40]:
            left = item["left"]
            right = item["right"]
            if left not in node_ids or right not in node_ids:
                continue
            weight = item["shared_race_count"]
            lines.append(f'  {node_ids[left]} -- "{weight}" --> {node_ids[right]}')
    lines.append("```")
    return "\n".join(lines)


def render_connectivity_report(report: ConnectivityReport, input_path: Path) -> str:
    prep = report.preparation
    lines = [
        "# R-01 연결성 분석 리포트",
        "",
        f"- 생성시각: {report.generated_at}",
        f"- 입력 파일: `{input_path}`",
        f"- 판정: **{report.decision}**",
        f"- 판정 근거: {report.decision_reason}",
        "",
        "## 입력/전처리 진단",
        "",
        f"- race_id 소스: `{prep.get('race_id_source', 'unknown')}`",
        f"- 전체 입력 행수: **{_fmt_int(prep.get('total_rows'))}**",
        f"- 필터 후 사용 행수: **{_fmt_int(prep.get('rows_after_filter'))}**",
        f"- 필터 후 선수수: **{_fmt_int(prep.get('athlete_count_after_filter'))}**",
        f"- 필터 후 race 수: **{_fmt_int(prep.get('race_count_after_filter'))}**",
        f"- race_id 복원 후 결측 행수: **{_fmt_int(prep.get('race_id_missing_rows_after_reconstruction'))}**",
        "",
    ]

    exclusion_rows = [
        ["선수 식별자 결측", _fmt_int(prep.get("excluded_missing_athlete_rows"))],
        ["race_id 결측", _fmt_int(prep.get("excluded_missing_race_rows"))],
        ["쇼트트랙 외 행", _fmt_int(prep.get("excluded_non_shorttrack_rows"))],
        ["채점종합 행", _fmt_int(prep.get("excluded_score_round_rows"))],
        ["릴레이/계주 행", _fmt_int(prep.get("excluded_relay_rows"))],
        ["비완주 행", _fmt_int(prep.get("excluded_non_finisher_rows"))],
        ["중복 athlete-race 행", _fmt_int(prep.get("deduplicated_athlete_race_rows"))],
    ]
    lines.extend(_table(["제외 사유", "행수"], exclusion_rows))
    lines.extend(
        [
            "",
            "## 1) 전체 그래프",
            "",
            f"- 노드(선수) 수: **{_fmt_int(report.overall['node_count'])}**",
            f"- 엣지(대결 관계) 수: **{_fmt_int(report.overall['edge_count'])}**",
            f"- 연결 성분 수: **{_fmt_int(report.overall['component_count'])}**",
            f"- 거대 성분 비율: **{_fmt_pct_ratio(report.overall['largest_component_ratio'])}**",
            f"- 차수 평균: **{_fmt_float(report.overall['degree_mean'])}**",
            f"- 차수 p50: **{_fmt_float(report.overall['degree_p50'])}**",
            f"- 차수 p10: **{_fmt_float(report.overall['degree_p10'])}**",
            "",
            "## 2) 시즌 단절 검사",
            "",
            f"- 2개 이상 시즌 등장 선수 수: **{_fmt_int(report.season.get('bridge_athlete_count'))}**",
            f"- 2개 이상 시즌 등장 선수 비율: **{_fmt_pct_ratio(report.season.get('bridge_athlete_ratio'))}**",
            "",
        ]
    )

    season_rows = []
    for item in report.season.get("per_season", []):
        season_rows.append(
            [
                _fmt_plain_int(item["season"]),
                _fmt_int(item["node_count"]),
                _fmt_int(item["edge_count"]),
                _fmt_int(item["component_count"]),
                _fmt_pct_ratio(item["largest_component_ratio"]),
            ]
        )
    if season_rows:
        lines.extend(_table(["시즌", "노드수", "엣지수", "성분수", "거대성분비율"], season_rows))
    else:
        lines.append("_시즌 지표를 계산할 데이터가 없습니다._")

    lines.extend(
        [
            "",
            "## 3) 학령 단절 검사",
            "",
            f"- (시즌,학년,성별) 셀 수: **{_fmt_int(report.grade.get('cell_count'))}**",
            f"- 셀 선수수 p50: **{_fmt_float(report.grade.get('cell_athlete_p50'))}**",
            f"- 셀 선수수 p10: **{_fmt_float(report.grade.get('cell_athlete_p10'))}**",
            f"- 혼합학년 race 수: **{_fmt_int(report.grade.get('mixed_grade_race_count'))}**",
            f"- 학년 메타그래프 노드 수: **{_fmt_int(report.grade.get('grade_meta_node_count'))}**",
            f"- 학년 메타그래프 엣지 수: **{_fmt_int(report.grade.get('grade_meta_edge_count'))}**",
            f"- 학년 메타그래프 연결 성분 수: **{_fmt_int(report.grade.get('grade_meta_component_count'))}**",
            "",
            "### 학년 메타 그래프",
            "",
            _render_grade_meta_mermaid(report.grade.get("grade_meta_nodes", []), report.grade.get("grade_meta_edges", [])),
            "",
            "### 셀 규모 상위 20개",
            "",
        ]
    )

    cell_rows = []
    for item in report.grade.get("top_cells", []):
        cell_rows.append(
            [
                _fmt_plain_int(item["season"]),
                item["grade"],
                item["gender"],
                _fmt_int(item["athlete_count"]),
            ]
        )
    if cell_rows:
        lines.extend(_table(["시즌", "학년", "성별", "선수수"], cell_rows))
    else:
        lines.append("_학년 셀 데이터가 없습니다._")

    lines.extend(
        [
            "",
            "## 4) 종적 다리 강도",
            "",
            f"- 학년 상승(시즌+1, 학년+1) 지속 선수 수: **{_fmt_int(report.vertical.get('longitudinal_athlete_count'))}**",
            f"- 학년 상승 지속 선수 비율: **{_fmt_pct_ratio(report.vertical.get('longitudinal_athlete_ratio'))}**",
            f"- 비교 가능한 셀 수(이전 시즌·이전 학년 존재): **{_fmt_int(report.vertical.get('comparable_cell_count'))}**",
            f"- 고립 셀 수(공유선수 0): **{_fmt_int(report.vertical.get('isolated_cell_count'))}**",
            f"- 셀 간 공유선수 최소값: **{_fmt_int(report.vertical.get('shared_athlete_min'))}**",
            f"- 셀 간 공유선수 p50: **{_fmt_float(report.vertical.get('shared_athlete_p50'))}**",
            f"- 셀 간 공유선수 p10: **{_fmt_float(report.vertical.get('shared_athlete_p10'))}**",
            f"- 고립 셀 소속 선수 비율: **{_fmt_pct_ratio(report.vertical.get('isolated_athlete_ratio'))}**",
            "",
        ]
    )
    if int(report.vertical.get("comparable_cell_count") or 0) == 0:
        lines.extend(
            [
                "- 참고: 현재 입력에서 단일 학년값으로 이전 시즌-이전 학년 비교가 가능한 셀이 없어, 종적 다리 강도는 하한치로 해석해야 합니다.",
                "",
            ]
        )

    isolated_rows = []
    for item in report.vertical.get("isolated_cells", [])[:30]:
        isolated_rows.append(
            [
                _fmt_plain_int(item["season"]),
                _fmt_plain_int(item["grade"]),
                _fmt_int(item["athlete_count"]),
            ]
        )
    if isolated_rows:
        lines.append("### 고립 셀(최대 30개)")
        lines.append("")
        lines.extend(_table(["시즌", "학년", "선수수"], isolated_rows))

    lines.extend(
        [
            "",
            "## 5) 관측치 규모",
            "",
            f"- 완주자 pairwise 총 개수: **{_fmt_int(report.observation.get('pairwise_total'))}**",
            f"- race 수: **{_fmt_int(report.observation.get('race_count'))}**",
            f"- race 인원수 p50: **{_fmt_float(report.observation.get('race_size_p50'))}**",
            f"- race 인원수 p10: **{_fmt_float(report.observation.get('race_size_p10'))}**",
            f"- 선수당 pairwise p50: **{_fmt_float(report.observation.get('athlete_pairwise_p50'))}**",
            f"- 선수당 pairwise p10: **{_fmt_float(report.observation.get('athlete_pairwise_p10'))}**",
            "",
            "## 판정 규칙(사전 고정)",
            "",
        ]
    )
    lines.extend(
        _table(
            ["조건", "판정"],
            [
                ["거대 성분 ≥ 90% AND 고립 (시즌,학년) 셀 없음", "GO"],
                ["거대 성분 70~90%", "조건부 GO"],
                ["거대 성분 < 70%", "STOP"],
            ],
        )
    )

    isolated_ratio = float(report.vertical.get("isolated_athlete_ratio") or 0.0)
    lines.extend(
        [
            "",
            "## 판정 메모",
            "",
            f"- 최종 결론: **{report.decision}**",
            f"- 근거: {report.decision_reason}",
            "- 운영 기준: 고립 셀 소속 선수 비율이 5% 미만이면 해당 셀만 레이팅 미제공으로 분리 운영하고, 5% 이상이면 설계를 재검토합니다.",
            f"- 고립 셀 소속 선수 비율 관측값: **{_fmt_pct_ratio(isolated_ratio)}**",
            f"- 5% 기준 충족 여부: **{'Y' if isolated_ratio < ISOLATED_CELL_WARN_RATIO else 'N'}**",
            "",
        ]
    )
    return "\n".join(lines)


def render_adr(report: ConnectivityReport, input_path: Path) -> str:
    giant_ratio = float(report.overall.get("largest_component_ratio") or 0.0)
    isolated_cells = int(report.vertical.get("isolated_cell_count") or 0)
    isolated_athlete_ratio = float(report.vertical.get("isolated_athlete_ratio") or 0.0)
    lines = [
        "# ADR 0001 — 레이팅 성립 가능성 판정 (R-01)",
        "",
        f"- 상태: Accepted",
        f"- 작성시각: {report.generated_at}",
        f"- 입력: `{input_path}`",
        "",
        "## 문맥",
        "",
        "- 선수 레이팅은 비교 그래프가 연결되어 있어야만 의미를 가집니다.",
        "- 본 ADR은 완주자 대결 하한 그래프를 기준으로, 현재 데이터에서 레이팅을 진행할지 중단할지 판정합니다.",
        "",
        "## 판정 규칙",
        "",
        "| 조건 | 판정 |",
        "| --- | --- |",
        "| 거대 성분 ≥ 90% AND 고립 (시즌,학년) 셀 없음 | GO |",
        "| 거대 성분 70~90% | 조건부 GO |",
        "| 거대 성분 < 70% | STOP |",
        "",
        "## 관측값",
        "",
        f"- 거대 성분 비율: **{_fmt_pct_ratio(giant_ratio)}**",
        f"- 비교 가능한 (시즌,학년) 셀 수: **{_fmt_int(report.vertical.get('comparable_cell_count'))}**",
        f"- 고립 (시즌,학년) 셀 수: **{_fmt_int(isolated_cells)}**",
        f"- 고립 셀 소속 선수 비율: **{_fmt_pct_ratio(isolated_athlete_ratio)}**",
        "",
        "## 결정",
        "",
        f"- 최종 결론: **{report.decision}**",
        f"- 근거: {report.decision_reason}",
    ]
    if report.decision == "조건부 GO":
        lines.extend(
            [
                "- 운영 지침: 거대 성분 밖 선수/셀은 레이팅 미제공으로 표기하고 분리 운영합니다.",
                "- 추가 기준: 고립 셀 소속 선수 비율이 5% 이상이면 설계 재검토 이슈를 즉시 생성합니다.",
            ]
        )
    elif report.decision == "STOP":
        lines.extend(
            [
                "- 후속 지침: 전역 레이팅 도입을 중단하고, 코호트/셀 내부 상대지표 중심 대안 설계로 전환합니다.",
            ]
        )
    else:
        lines.extend(
            [
                "- 후속 지침: 전역 레이팅 계산 구현(R-02+)로 진행합니다.",
            ]
        )
    lines.append("")
    return "\n".join(lines)


def load_results_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"[error] 입력 파일이 없습니다: {path}")
    return pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")


def _run(results_path: Path, out_path: Path, adr_path: Path) -> ConnectivityReport:
    raw = load_results_csv(results_path)
    prepared = prepare_results(raw)
    graph = build_graph(prepared.rows)
    report = analyze_connectivity(graph, prepared.rows)
    report.preparation = prepared.diagnostics

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_connectivity_report(report, results_path) + "\n", encoding="utf-8")

    adr_path.parent.mkdir(parents=True, exist_ok=True)
    adr_path.write_text(render_adr(report, results_path) + "\n", encoding="utf-8")
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="완주자 대결 그래프를 구축하고 연결성 기반 레이팅 가능성을 판정합니다.")
    parser.add_argument("--results", required=True, help="입력 CSV 경로")
    parser.add_argument("--out", default="out/connectivity_report.md", help="리포트 출력 경로")
    parser.add_argument("--adr-out", default="docs/adr/0001-rating-feasibility.md", help="ADR 출력 경로")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    results_path = Path(args.results).expanduser()
    out_path = Path(args.out).expanduser()
    adr_path = Path(args.adr_out).expanduser()

    report = _run(results_path, out_path, adr_path)
    print(f"[ok] 판정: {report.decision}")
    print(f"[ok] 리포트: {out_path}")
    print(f"[ok] ADR: {adr_path}")


if __name__ == "__main__":
    main()
