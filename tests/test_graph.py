import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rating.ledger.graph import DecisionUnavailableError, _build_vertical_metrics, analyze_connectivity, build_graph, prepare_results


def test_analyze_connectivity_detects_disconnected_fixture():
    fixture_path = Path("tests/fixtures/connectivity_disconnected.csv")
    raw = pd.read_csv(fixture_path, dtype=str).fillna("")
    prepared = prepare_results(raw)
    graph = build_graph(prepared.rows)
    report = analyze_connectivity(graph, prepared.rows)

    assert report.overall["node_count"] == 6
    assert report.overall["component_count"] == 2
    assert report.overall["largest_component_size"] == 3
    assert report.overall["largest_component_ratio"] == pytest.approx(0.5, rel=1e-6)
    assert report.decision == "STOP"


def test_prepare_results_reconstructs_race_and_applies_filters():
    raw = pd.DataFrame(
        [
            {
                "toCd": "2024001",
                "classCd": "2",
                "대회명": "테스트 대회",
                "일자": "2024-01-01",
                "종별": "남자초등부",
                "거리": "500",
                "라운드": "예선1조Heat 1",
                "라운드종류": "예선",
                "순위": "1",
                "기록_초": "45.100",
                "사유": "",
                "성별": "남",
                "대회연도": "2024",
                "학년": "5",
                "익명키": "athlete_x",
            },
            {
                "toCd": "2024001",
                "classCd": "2",
                "대회명": "테스트 대회",
                "일자": "2024-01-01",
                "종별": "남자초등부",
                "거리": "500",
                "라운드": "예선1조Heat 1",
                "라운드종류": "예선",
                "순위": "1",
                "기록_초": "45.100",
                "사유": "",
                "성별": "남",
                "대회연도": "2024",
                "학년": "5",
                "익명키": "athlete_x",
            },
            {
                "toCd": "2024001",
                "classCd": "2",
                "대회명": "테스트 대회",
                "일자": "2024-01-01",
                "종별": "남자초등부",
                "거리": "500",
                "라운드": "결승",
                "라운드종류": "채점종합",
                "순위": "2",
                "기록_초": "46.000",
                "사유": "",
                "성별": "남",
                "대회연도": "2024",
                "학년": "5",
                "익명키": "athlete_y",
            },
            {
                "toCd": "2024002",
                "classCd": "2",
                "대회명": "테스트 계주 대회",
                "일자": "2024-01-02",
                "종별": "남자초등부 계주",
                "거리": "3000",
                "라운드": "계주결승",
                "라운드종류": "결승",
                "순위": "1",
                "기록_초": "260.000",
                "사유": "",
                "성별": "남",
                "대회연도": "2024",
                "학년": "5",
                "익명키": "athlete_z",
            },
            {
                "toCd": "2024003",
                "classCd": "2",
                "대회명": "테스트 대회",
                "일자": "2024-01-03",
                "종별": "남자초등부",
                "거리": "500",
                "라운드": "예선2조Heat 2",
                "라운드종류": "예선",
                "순위": "4",
                "기록_초": "47.200",
                "사유": "DQ",
                "성별": "남",
                "대회연도": "2024",
                "학년": "5",
                "익명키": "athlete_w",
            },
        ]
    )

    prepared = prepare_results(raw)
    diagnostics = prepared.diagnostics

    assert diagnostics["race_id_source"] == "reconstructed"
    assert diagnostics["excluded_score_round_rows"] == 1
    assert diagnostics["excluded_relay_rows"] == 1
    assert diagnostics["excluded_non_finisher_rows"] == 1
    assert diagnostics["deduplicated_athlete_race_rows"] == 1
    assert diagnostics["rows_after_filter"] == 1
    assert prepared.rows["race_id"].iloc[0] != ""


def test_decision_unavailable_when_comparable_cells_absent():
    raw = pd.DataFrame(
        [
            {
                "meet_id": "m1",
                "race_id": "r1",
                "athlete_hash": "a1",
                "event": "500m",
                "round": "예선1조",
                "place": "1",
                "time": "45.1",
                "status": "",
                "season": "2024",
                "grade": "5,6",
                "gender": "남",
                "class_cd": "2",
            },
            {
                "meet_id": "m1",
                "race_id": "r1",
                "athlete_hash": "a2",
                "event": "500m",
                "round": "예선1조",
                "place": "2",
                "time": "45.4",
                "status": "",
                "season": "2024",
                "grade": "5,6",
                "gender": "남",
                "class_cd": "2",
            },
        ]
    )
    prepared = prepare_results(raw)
    graph = build_graph(prepared.rows)
    with pytest.raises(DecisionUnavailableError):
        analyze_connectivity(graph, prepared.rows)


def test_isolated_cells_use_bidirectional_definition():
    raw = pd.DataFrame(
        [
            {"meet_id": "m1", "race_id": "r1", "athlete_hash": "m_prev_1", "event": "500m", "round": "예선1조", "place": "1", "time": "45.1", "status": "", "season": "2023", "grade": "1,2", "gender": "남", "class_cd": "2"},
            {"meet_id": "m1", "race_id": "r1", "athlete_hash": "m_prev_2", "event": "500m", "round": "예선1조", "place": "2", "time": "45.2", "status": "", "season": "2023", "grade": "1,2", "gender": "남", "class_cd": "2"},
            {"meet_id": "m2", "race_id": "r2", "athlete_hash": "m_mid_1", "event": "500m", "round": "예선1조", "place": "1", "time": "45.3", "status": "", "season": "2024", "grade": "1,2", "gender": "남", "class_cd": "2"},
            {"meet_id": "m2", "race_id": "r2", "athlete_hash": "m_mid_2", "event": "500m", "round": "예선1조", "place": "2", "time": "45.4", "status": "", "season": "2024", "grade": "1,2", "gender": "남", "class_cd": "2"},
            {"meet_id": "m3", "race_id": "r3", "athlete_hash": "m_next_1", "event": "500m", "round": "예선1조", "place": "1", "time": "45.5", "status": "", "season": "2025", "grade": "1,2", "gender": "남", "class_cd": "2"},
            {"meet_id": "m3", "race_id": "r3", "athlete_hash": "m_next_2", "event": "500m", "round": "예선1조", "place": "2", "time": "45.6", "status": "", "season": "2025", "grade": "1,2", "gender": "남", "class_cd": "2"},
        ]
    )
    prepared = prepare_results(raw)
    vertical = _build_vertical_metrics(prepared.rows)

    assert vertical["comparable_cell_count"] == 2
    assert vertical["bidirectional_comparable_cell_count"] == 1
    assert vertical["isolated_cell_count"] == 1
    assert vertical["isolated_cells"] == [{"season": 2024, "grade": "1,2", "gender": "남", "athlete_count": 2}]
