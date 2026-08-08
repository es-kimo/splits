import json
import html
from pathlib import Path

import pandas as pd

DATA_DIR = Path("data")
SITE_HTML = Path("index.html")
ATHLETE_DIR = Path("athlete")
SITEMAP_XML = Path("sitemap.xml")
ROBOTS_TXT = Path("robots.txt")
SITE_BASE_URL = "https://es-kimo.github.io/splits/"
INPUT_FILES = [
    "placements.csv",
    "youth_summary.csv",
    "age_matrix.csv",
    "athlete_info.csv",
    "coverage.csv",
]
AGES = [str(age) for age in range(7, 19)]


def as_int(value):
    text = str(value or "").strip()
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else None


def as_id(value):
    return str(value or "").strip()


def as_bool(value):
    return str(value or "").strip().lower() in {"true", "1", "y", "yes", "t"}


def site_url(path=""):
    return f"{SITE_BASE_URL.rstrip('/')}/{str(path or '').lstrip('/')}"


def read_csv(name):
    path = DATA_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"[error] 파일이 없습니다: {path}")
    return pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")


def rank_band_text(rank):
    if rank is None:
        return "-"
    if rank < 10:
        return "한 자리수"
    return f"{(rank // 10) * 10}등대"


def build_payload():
    frames = {name: read_csv(name) for name in INPUT_FILES}
    placements = frames["placements.csv"]
    summary = frames["youth_summary.csv"]
    matrix = frames["age_matrix.csv"]
    athlete_info = frames["athlete_info.csv"]
    coverage = frames["coverage.csv"]

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

    elem = placements[(placements["학령구간"] == "초등") & placements["순위_num"].notna()].copy()
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

    primary_ids = [v for v in athlete_info["idNo"].astype(str).map(as_id).tolist() if v]
    ids = []
    for candidate in primary_ids:
        if candidate not in ids:
            ids.append(candidate)
    if not ids:
        for candidate in summary["idNo"].astype(str).map(as_id).tolist():
            if candidate and candidate not in ids:
                ids.append(candidate)
        for candidate in matrix["idNo"].astype(str).map(as_id).tolist():
            if candidate and candidate not in ids:
                ids.append(candidate)
        for candidate in placements["idNo"].astype(str).map(as_id).tolist():
            if candidate and candidate not in ids:
                ids.append(candidate)

    history_by_id = {}
    for _, row in placements.iterrows():
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
    for id_no in ids:
        s = summary_by_id.get(id_no, {})
        info = info_by_id.get(id_no, {"name": id_no, "birth": None, "team": "-", "gender": None})
        m = matrix_by_id.get(id_no, {})
        name = info.get("name") or s.get("name") or m.get("name") or id_no
        median = elem_median.get(id_no)
        median_value = float(median) if median is not None else None
        history = history_by_id.get(id_no, [])
        history = sorted(history, key=lambda x: (x.get("year") is None, -(x.get("year") or 0), x.get("meet", ""), x.get("distance") or 0, x.get("rank") or 9999))
        athletes.append(
            {
                "idNo": id_no,
                "url": f"athlete/{id_no}/",
                "name": name,
                "birth": info["birth"],
                "team": info["team"],
                "gender": info["gender"],
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

    years = [as_int(v) for v in coverage.get("대회연도", pd.Series(dtype=str)).tolist()]
    years = [y for y in years if y is not None]
    if not years:
        years = [y for y in placements["대회연도_num"].tolist() if y is not None]
    year_start, year_end = (min(years), max(years)) if years else (None, None)

    all_ages = [a for a in placements["나이_추정_num"].tolist() if isinstance(a, int)]
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

    return {
        "meta": {
            "athleteCount": len(athletes),
            "placementCount": int(len(placements)),
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


def build_html(payload):
    meta = payload["meta"]
    data_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")

    athlete_count = f"{meta.get('athleteCount') or 0}명"
    placement_count = f"{format(meta.get('placementCount') or 0, ',')}개"
    if meta.get("ageMin") is not None and meta.get("ageMax") is not None:
        age_span = f"{meta['ageMin']}~{meta['ageMax']}살"
    else:
        age_span = "-"

    if meta.get("yearSpan") is not None and meta.get("yearStart") is not None and meta.get("yearEnd") is not None:
        year_span_head = f"{meta['yearSpan']}년치"
        year_span_tail = f"{meta['yearStart']}년 ~ {meta['yearEnd']}년"
    else:
        year_span_head = "-"
        year_span_tail = "기간 정보 없음"

    line1 = (
        "초등부 기록이 남아 있는 "
        f"<b style=\"font-weight:700;color:#17181C\">{meta.get('elemTop2Count') or 0}명 모두</b> "
        "초등학생 때 이미 최소 한 번은 1~2등을 했습니다."
    )
    first_age_min = meta.get("firstAgeMin")
    first_age_max = meta.get("firstAgeMax")
    first_age_text = "-" if first_age_min is None or first_age_max is None else f"{first_age_min}살부터 {first_age_max}살까지"
    line2 = (
        "그렇다고 늘 앞자리였던 건 아닙니다. 같은 선수들의 초등부 성적 중에는 "
        f"<b style=\"font-weight:700;color:#17181C\">{meta.get('elemWorstBand') or '-'}</b>도 섞여 있습니다."
    )
    line3 = (
        "처음 대회에 나온 나이는 "
        f"<b style=\"font-weight:700;color:#17181C\">{first_age_text}</b> 제각각이었습니다."
    )

    missing_names = []
    by_name = {a["name"]: a for a in payload["athletes"]}
    for name in meta.get("missingElemNames", []):
        birth = by_name.get(name, {}).get("birth")
        if birth is None:
            missing_names.append(name)
        else:
            missing_names.append(f"{name}({birth}년생)")
    if not missing_names:
        missing_elem_note = "초등부 기록이 남아 있지 않은 선수는 없습니다."
        missing_limit_note = "초등부 누락 데이터가 확인된 선수는 없습니다."
    elif len(missing_names) == 1:
        missing_elem_note = f"{missing_names[0]}은 초등부 기록이 남아 있지 않아 빠졌습니다."
        missing_limit_note = (
            f"{missing_names[0]}: 초등부 기록 0건. 출전하지 않은 것이 아니라 기록이 남아 있지 않은 것"
        )
    else:
        names_text = ", ".join(missing_names)
        missing_elem_note = f"{names_text}은 초등부 기록이 남아 있지 않아 빠졌습니다."
        missing_limit_note = f"{names_text}: 초등부 기록 누락 확인"

    template = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>국가대표 14명의 유년기 기록</title>
<meta name="description" content="쇼트트랙 국가대표 선수 14명의 유년기 순위 데이터를 정리한 페이지입니다. 선수별 상세 페이지로 이동해 나이별 성적과 전체 대회 이력을 볼 수 있습니다.">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css">
<style>
body{margin:0;background:#F3F5F8;-webkit-font-smoothing:antialiased;text-wrap:pretty}
a{color:#2E63F6;text-decoration:none}
a:hover{color:#1B47C4}
.page{font-family:'Pretendard Variable',Pretendard,-apple-system,BlinkMacSystemFont,'Apple SD Gothic Neo',sans-serif;background:#F3F5F8;color:#17181C;padding:0 0 72px;line-height:1.6}
.container{max-width:700px;margin:0 auto;padding:0 18px;display:flex;flex-direction:column;gap:14px}
header{padding:44px 4px 12px;display:flex;flex-direction:column;gap:16px}
.badge{align-self:flex-start;background:#E4EBFF;color:#2E63F6;font-size:13px;font-weight:700;padding:7px 13px;border-radius:999px}
h1{margin:0;font-size:34px;line-height:1.32;font-weight:800;letter-spacing:-0.03em}
.intro{margin:0;font-size:16px;color:#5B5F68}
.metrics{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.metric{background:#fff;border-radius:18px;padding:18px 18px 16px}
.metric-main{font-size:26px;font-weight:800;letter-spacing:-0.02em}
.metric-sub{font-size:13px;color:#8A8F99;margin-top:2px}
.section{background:#fff;border-radius:22px;padding:24px 20px}
h2{margin:0 0 6px;font-size:20px;font-weight:800;letter-spacing:-0.02em}
.section-note{margin:0 0 16px;font-size:14.5px;color:#6B6F78}
.summary-list{display:flex;flex-direction:column;gap:14px}
.summary-item{display:flex;gap:12px;align-items:flex-start}
.summary-index{flex:none;width:26px;height:26px;border-radius:9px;background:#E4EBFF;color:#2E63F6;font-size:13px;font-weight:800;display:flex;align-items:center;justify-content:center}
.summary-text{margin:0;font-size:15.5px;color:#3A3D45}
.read-box{background:#F5F7FA;border-radius:16px;padding:14px 16px;display:flex;flex-direction:column;gap:8px;margin-bottom:18px}
.read-title{font-size:13.5px;font-weight:700;color:#3A3D45}
.read-row{display:flex;align-items:center;gap:9px;font-size:13.5px;color:#6B6F78}
.dot-blue{width:11px;height:11px;border-radius:50%;background:#2E63F6;flex:none}
.dot-gray{width:11px;height:11px;border-radius:50%;background:#C6CBD4;flex:none}
.line-gray{width:11px;height:3px;border-radius:2px;background:#DFE3E9;flex:none}
.age-cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:10px}
.age-card{background:#FAFBFC;border-radius:16px;padding:14px 14px 10px}
.age-head{display:flex;align-items:baseline;justify-content:space-between;gap:8px;margin-bottom:2px}
.age-name{font-size:16px;font-weight:700;letter-spacing:-0.01em}
.athlete-link{color:inherit;text-decoration:none}
.athlete-link:hover{text-decoration:underline}
.age-birth{font-size:12.5px;color:#9BA0AA}
.age-summary{font-size:12.5px;color:#2E63F6;font-weight:600;margin-bottom:4px}
.age-axis{display:flex;justify-content:space-between;font-size:11.5px;color:#A9AEB8;padding:0 2px}
.section-footnote{margin:16px 0 0;font-size:13.5px;color:#8A8F99}
.elem-rows{display:flex;flex-direction:column;gap:2px}
.elem-row{padding:14px 2px;border-top:1px solid #F0F2F5;display:flex;flex-direction:column;gap:9px}
.elem-row-head{display:flex;align-items:center;gap:8px}
.elem-rank{font-size:12px;color:#B4B9C2;font-weight:700;width:18px}
.elem-name{font-size:16px;font-weight:700}
.elem-count{font-size:12px;color:#8A8F99;background:#F2F4F7;border-radius:999px;padding:3px 9px}
.elem-summary{margin-left:auto;font-size:13.5px;color:#6B6F78}
.elem-bar-wrap{position:relative;height:12px;border-radius:999px;background:#F0F2F5;margin-left:26px}
.elem-bar{position:absolute;top:0;height:12px;border-radius:999px}
.elem-mid{position:absolute;top:2px;height:8px;width:2px;border-radius:2px;background:#fff}
.sample-note{margin-top:18px;background:#F5F7FA;border-radius:16px;padding:14px 16px;font-size:13.5px;color:#6B6F78}
.detail-list{display:flex;flex-direction:column}
.detail-row{border-top:1px solid #F0F2F5}
.detail-toggle{cursor:pointer;padding:15px 2px;display:flex;align-items:center;gap:10px}
.detail-toggle:hover{background:#FAFBFC}
.detail-name{font-size:16px;font-weight:700}
.detail-meta{font-size:13px;color:#8A8F99}
.detail-actions{margin-left:auto;display:flex;align-items:center;gap:10px}
.detail-link{font-size:13px;color:#2E63F6;font-weight:600;text-decoration:none}
.detail-link:hover{text-decoration:underline}
.detail-state{font-size:13px;color:#2E63F6;font-weight:600}
.detail-body{padding:2px 0 18px;display:flex;flex-direction:column;gap:1px}
.detail-span{font-size:13px;color:#8A8F99;padding:0 2px 8px}
.detail-year{display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:12px;background:#FAFBFC}
.detail-year-text{font-size:14px;color:#3A3D45;width:64px}
.detail-age-text{font-size:13px;color:#9BA0AA}
.detail-rank-text{margin-left:auto;font-size:14.5px;font-weight:700}
.note-list{display:flex;flex-direction:column;gap:10px}
.note-card{background:#FAFBFC;border-radius:16px;padding:16px}
.note-q{font-size:15px;font-weight:700;margin-bottom:5px}
.note-a{font-size:14.5px;color:#5B5F68}
footer{padding:14px 6px 0;font-size:13px;color:#9BA0AA}
@media (max-width:640px){
  h1{font-size:31px}
  .container{padding:0 14px}
}
</style>
</head>
<body>
<div class="page">
  <div class="container">
    <header>
      <span class="badge">공개 경기 기록 정리</span>
      <h1>쇼트트랙 국가대표 14명은<br>어릴 때 몇 등이었을까요?</h1>
      <p class="intro">2026/27시즌 쇼트트랙 국가대표 14명이 <b style="font-weight:700;color:#17181C">7살 때부터</b> 국내 대회에서 받은 성적을 정리했어요.</p>
    </header>

    <div class="metrics">
      <div class="metric"><div class="metric-main">__ATHLETE_COUNT__</div><div class="metric-sub">국가대표 선수</div></div>
      <div class="metric"><div class="metric-main">__PLACEMENT_COUNT__</div><div class="metric-sub">모은 경기 성적</div></div>
      <div class="metric"><div class="metric-main">__AGE_SPAN__</div><div class="metric-sub">기록에 담긴 나이</div></div>
      <div class="metric"><div class="metric-main">__YEAR_SPAN_HEAD__</div><div class="metric-sub">__YEAR_SPAN_TAIL__</div></div>
    </div>

    <section class="section">
      <h2>먼저, 세 줄 요약</h2>
      <div class="summary-list">
        <div class="summary-item"><span class="summary-index">1</span><p class="summary-text">__SUMMARY_LINE_1__</p></div>
        <div class="summary-item"><span class="summary-index">2</span><p class="summary-text">__SUMMARY_LINE_2__</p></div>
        <div class="summary-item"><span class="summary-index">3</span><p class="summary-text">__SUMMARY_LINE_3__</p></div>
      </div>
    </section>

    <section class="section">
      <h2>나이별로 가장 잘했던 등수</h2>
      <p class="section-note">각 선수가 나이별로 <b style="font-weight:700;color:#17181C">가장 잘했던 등수</b>를 기록했어요. 그래프에서 왼쪽이 7살, 오른쪽이 18살이에요.</p>

      <div class="read-box">
        <div class="read-title">이렇게 보세요</div>
        <div class="read-row"><span class="dot-blue"></span>파란 점이 위에 붙을수록 1등에 가깝습니다</div>
        <div class="read-row"><span class="dot-gray"></span>회색 점은 등수가 뒤로 밀린 해예요 (옆에 등수 표시)</div>
        <div class="read-row"><span class="line-gray"></span>아래쪽 짧은 선은 그 나이의 기록이 아예 없다는 뜻입니다</div>
      </div>

      <div id="age-cards" class="age-cards"></div>
      <p class="section-footnote">비어 있는 구간은 해당 나이의 기록이 시스템에 없다는 뜻이에요. 2012년 이전 대회는 일부만 전산화돼 있어요.</p>
    </section>

    <section class="section">
      <h2>초등부 때 성적의 폭</h2>
      <p class="section-note">막대의 왼쪽 끝이 가장 좋았던 등수, 오른쪽 끝이 가장 나빴던 등수입니다. 하얀 선은 보통 받던 등수(중앙값)예요.</p>

      <div id="elem-rows" class="elem-rows"></div>
      <div class="sample-note">출전 횟수가 10번이 안 되는 선수는 회색으로 표시했어요. 몇 경기 안 되는 성적이라 '보통 등수'를 그대로 믿기는 어려워요. __MISSING_ELEM_NOTE__</div>
    </section>

    <section class="section">
      <h2>선수별로 자세히 보기</h2>
      <p class="section-note">이름을 누르면 연도별 최고 성적을 볼 수 있어요.</p>
      <div id="detail-list" class="detail-list"></div>
    </section>

    <section class="section">
      <h2>이 자료를 볼 때 알아두실 점</h2>
      <p class="section-note">숫자를 오해하지 않으시도록, 데이터의 한계를 알려드려요.</p>
      <div class="note-list">
        <div class="note-card"><div class="note-q">나이는 어떻게 계산했나요?</div><div class="note-a">대회가 열린 연도에서 태어난 해를 뺐습니다. 생일이 지나지 않았다면 만 나이보다 한 살 많습니다. 겨울 대회가 1~2월에 몰려 있어 대체로 한 살 높게 잡혀 있다고 보시면 됩니다.</div></div>
        <div class="note-card"><div class="note-q">왜 옛날 선수는 어릴 때 기록이 없나요?</div><div class="note-a">2012년 이전 대회는 일부만 전산화돼 있습니다. 1990년대 중반 이전에 태어난 선수는 유년기 기록이 통째로 비어 있습니다. __MISSING_LIMIT_NOTE__</div></div>
        <div class="note-card"><div class="note-q">어떤 경기의 등수인가요?</div><div class="note-a">결승과 채점종합 기준입니다. 예선이나 준결승에서 조 안에 매긴 등수는 전체 성적이 아니라 뺐습니다.</div></div>
        <div class="note-card"><div class="note-q">기록(시간)은 왜 없나요?</div><div class="note-a">쇼트트랙은 순위 경기입니다. 결승에서 일부러 천천히 타다 마지막에 붙는 경우가 많아, 예선보다 30초 넘게 느린데 1등인 기록도 있습니다. 시간은 실력을 그대로 보여주지 않아 싣지 않았습니다.</div></div>
        <div class="note-card"><div class="note-q">잘못된 기록은 없나요?</div><div class="note-a">계측 오류로 보이는 기록 35건을 확인했지만, 임의로 고치지 않고 원본 그대로 두었습니다.</div></div>
        <div class="note-card"><div class="note-q">이 자료로 무엇을 알 수 있나요?</div><div class="note-a">14명이 어릴 때 어떤 성적을 남겼는지 재미로 봐주세요. 특별한 분석을 제공하고 있지 않습니다.</div></div>
      </div>
    </section>

    <footer>
      공개된 경기 기록을 개인이 정리한 페이지입니다. 대한빙상경기연맹 및 대한체육회와 무관합니다.<br>
      출처: 대한체육회 경기결과 시스템(result.sports.or.kr)
    </footer>
  </div>
</div>

<script>
const DATA=__DATA_JSON__;
const AGES=DATA.ages;
const CAP=40;
const W=300;
const TOP=10;
const BOT=64;
let openName=null;

function esc(v){
  return String(v??"").replace(/[&<>"']/g,(ch)=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
}

function yPos(rank){
  const r=Math.min(rank,CAP);
  return TOP+Math.sqrt((r-1)/(CAP-1))*(BOT-TOP);
}

function xPos(age){
  const i=AGES.indexOf(age);
  return 12+(i/(AGES.length-1))*(W-26);
}

function formatMedian(value){
  return value===null||value===undefined?"-":Number(value).toFixed(1);
}

function presentAges(athlete){
  return AGES.filter((age)=>athlete.ages[String(age)]!==null&&athlete.ages[String(age)]!==undefined);
}

function renderAgeCards(){
  const root=document.getElementById("age-cards");
  root.textContent="";
  for(const a of DATA.athletes){
    const missing=[];
    const runs=[];
    const dots=[];
    const labels=[];
    let run=[];

    const flush=()=>{
      if(run.length>1){
        runs.push(run.join(" "));
      }
      run=[];
    };

    for(const age of AGES){
      const rank=a.ages[String(age)];
      if(rank===null||rank===undefined){
        missing.push({x:xPos(age)});
        flush();
        continue;
      }
      const x=xPos(age);
      const y=yPos(rank);
      run.push(`${x},${y}`);
      dots.push({x,y,r:rank===1?4.5:3.6,fill:rank<=2?"#2E63F6":"#C6CBD4"});
      if(rank>2){
        labels.push({x:x+6,y:y+4,text:rank});
      }
    }
    flush();

    const present=presentAges(a).map(Number).sort((x,y)=>x-y);
    const wins=present.filter((age)=>a.ages[String(age)]===1).length;
    const summary=wins>0?`1등 ${wins}번 · ${present.length}개 나이 기록`:`${present.length}개 나이 기록`;

    const card=document.createElement("div");
    card.className="age-card";
    card.innerHTML=`
      <div class="age-head">
        <b class="age-name"><a class="athlete-link" href="${esc(a.url)}">${esc(a.name)}</a></b>
        <span class="age-birth">${a.birth?`${esc(a.birth)}년생`:"출생년도 미상"}</span>
      </div>
      <div class="age-summary">${esc(summary)}</div>
      <svg viewBox="0 0 300 92" preserveAspectRatio="none" style="width:100%;height:92px;display:block;overflow:visible">
        <line x1="0" y1="10" x2="300" y2="10" stroke="#E3E7ED" stroke-width="1"></line>
        <text x="0" y="7" font-size="9" fill="#B4B9C2">1등</text>
        ${missing.map((m)=>`<line x1="${m.x}" y1="70" x2="${m.x}" y2="76" stroke="#DFE3E9" stroke-width="2" stroke-linecap="round"></line>`).join("")}
        ${runs.map((points)=>`<polyline points="${points}" fill="none" stroke="#B9CCFB" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"></polyline>`).join("")}
        ${dots.map((d)=>`<circle cx="${d.x}" cy="${d.y}" r="${d.r}" fill="${d.fill}"></circle>`).join("")}
        ${labels.map((l)=>`<text x="${l.x}" y="${l.y}" font-size="10" font-weight="600" fill="#8A8F99">${l.text}</text>`).join("")}
      </svg>
      <div class="age-axis"><span>7살</span><span>12살</span><span>18살</span></div>
    `;
    root.appendChild(card);
  }
}

function renderElemRows(){
  const rows=DATA.athletes
    .filter((a)=>(a.elem?.count??0)>0)
    .slice()
    .sort((p,q)=>{
      const pm=Number.isFinite(p.elem?.median)?p.elem.median:9999;
      const qm=Number.isFinite(q.elem?.median)?q.elem.median:9999;
      return pm-qm||p.name.localeCompare(q.name,"ko");
    });

  const root=document.getElementById("elem-rows");
  root.textContent="";

  rows.forEach((a,index)=>{
    const e=a.elem||{};
    const best=e.best??1;
    const worst=e.worst??best;
    const median=Number.isFinite(e.median)?e.median:best;
    const left=((best-1)/40)*100;
    const width=Math.max(((worst-best)/40)*100,2);
    const mid=Math.min(((median-1)/40)*100,98);
    const thin=(e.count??0)<10;

    const row=document.createElement("div");
    row.className="elem-row";
    row.innerHTML=`
      <div class="elem-row-head">
        <span class="elem-rank">${index+1}</span>
        <b class="elem-name"><a class="athlete-link" href="${esc(a.url)}">${esc(a.name)}</a></b>
        <span class="elem-count">${e.count??0}번 출전</span>
        <span class="elem-summary">최고 ${best}등 · 보통 ${formatMedian(e.median)}등 · 최저 ${worst}등</span>
      </div>
      <div class="elem-bar-wrap">
        <span class="elem-bar" style="left:${left}%;width:${width}%;background:${thin?"#C6CBD4":"#2E63F6"}"></span>
        <span class="elem-mid" style="left:${mid}%"></span>
      </div>
    `;
    root.appendChild(row);
  });
}

function renderDetailList(){
  const root=document.getElementById("detail-list");
  root.textContent="";

  for(const a of DATA.athletes){
    const present=presentAges(a).map(Number).sort((x,y)=>x-y);
    const isOpen=openName===a.name;
    const firstLabel=a.first?`${a.first}살`:"-";

    const row=document.createElement("div");
    row.className="detail-row";

    let bodyHtml="";
    if(isOpen){
      const spanLabel=present.length
        ?(a.birth
          ?`기록이 남아 있는 기간 ${a.birth+present[0]}년 ~ ${a.birth+present[present.length-1]}년`
          :"기록이 남아 있는 기간 정보 없음")
        :"기록 없음";
      const yearRows=present.map((age)=>{
        const rank=a.ages[String(age)];
        const color=rank<=2?"#2E63F6":"#3A3D45";
        const yearText=a.birth?`${a.birth+age}년`:"연도 미상";
        return `
          <div class="detail-year">
            <span class="detail-year-text">${yearText}</span>
            <span class="detail-age-text">${age}살</span>
            <span class="detail-rank-text" style="color:${color}">${rank}등</span>
          </div>
        `;
      }).join("");
      bodyHtml=`
        <div class="detail-body">
          <div class="detail-span">${esc(spanLabel)}</div>
          ${yearRows}
        </div>
      `;
    }

    row.innerHTML=`
      <div class="detail-toggle" data-name="${esc(a.name)}">
        <b class="detail-name">${esc(a.name)}</b>
        <span class="detail-meta">${esc(a.team)} · 첫 대회 ${firstLabel}</span>
        <span class="detail-actions">
          <a class="detail-link" href="${esc(a.url)}" onclick="event.stopPropagation()">개별 페이지</a>
          <span class="detail-state">${isOpen?"접기":"펼치기"}</span>
        </span>
      </div>
      ${bodyHtml}
    `;
    root.appendChild(row);
  }

  root.querySelectorAll(".detail-toggle").forEach((btn)=>{
    btn.addEventListener("click",()=>{
      const name=btn.getAttribute("data-name")||"";
      openName=openName===name?null:name;
      renderDetailList();
    });
  });
}

renderAgeCards();
renderElemRows();
renderDetailList();
</script>
</body>
</html>
"""

    return (
        template.replace("__ATHLETE_COUNT__", athlete_count)
        .replace("__PLACEMENT_COUNT__", placement_count)
        .replace("__AGE_SPAN__", age_span)
        .replace("__YEAR_SPAN_HEAD__", year_span_head)
        .replace("__YEAR_SPAN_TAIL__", year_span_tail)
        .replace("__SUMMARY_LINE_1__", line1)
        .replace("__SUMMARY_LINE_2__", line2)
        .replace("__SUMMARY_LINE_3__", line3)
        .replace("__MISSING_ELEM_NOTE__", missing_elem_note)
        .replace("__MISSING_LIMIT_NOTE__", missing_limit_note)
        .replace("__DATA_JSON__", data_json)
    )


def esc_html(value):
    return html.escape(str(value or ""), quote=True)


def normalize_group_label(text):
    value = str(text or "").strip()
    if "종합" in value:
        return "종합"
    if value == "B" or "결승B" in value or value.startswith("B"):
        return "B"
    return "A"


def build_athlete_raw(history):
    by_year = {}
    for item in history:
        year = item.get("year")
        rank = item.get("rank")
        dist = item.get("distance")
        if year is None or rank is None or dist is None:
            continue
        year = int(year)
        meet = str(item.get("meet", "")).strip() or "-"
        year_bucket = by_year.setdefault(year, {})
        results = year_bucket.setdefault(meet, [])
        row = [int(dist), int(rank), normalize_group_label(item.get("round"))]
        if item.get("sf"):
            row.append(1)
        results.append(row)

    raw = []
    for year in sorted(by_year.keys(), reverse=True):
        comps = []
        for meet, results in by_year[year].items():
            sorted_results = sorted(results, key=lambda r: (r[0], 1 if len(r) >= 4 and r[3] else 0, r[1]))
            comps.append([meet, sorted_results])
        raw.append([year, comps])
    return raw


def build_athlete_html(athlete):
    name = athlete.get("name") or athlete.get("idNo") or "선수"
    birth = athlete.get("birth")
    team = athlete.get("team") or "-"
    gender = str(athlete.get("gender", "") or "").strip()
    history = athlete.get("history", [])
    raw = build_athlete_raw(history)

    years = [v[0] for v in raw]
    if years:
        min_year = min(years)
        max_year = max(years)
        season_span = f"{(max_year - min_year) + 1}년"
        year_range = f"{min_year}~{max_year}년"
    else:
        min_year = None
        season_span = "-"
        year_range = "기간 정보 없음"

    if birth is not None and min_year is not None:
        earliest_age = min_year - int(birth)
        missing_note = (
            f"{earliest_age}살({min_year}년) 이전 기록은 시스템에 남아 있지 않습니다. "
            "대회에 나가지 않았다는 뜻은 아닙니다."
        )
    else:
        missing_note = "초기 시즌 기록은 시스템에 남아 있지 않습니다. 대회에 나가지 않았다는 뜻은 아닙니다."

    subtitle_parts = [f"{birth}년생" if birth is not None else "출생년도 미상", team]
    if gender:
        subtitle_parts.append(gender)
    subtitle = " · ".join([v for v in subtitle_parts if v])

    description = f"{name} 선수의 출생년도, 소속, 나이별 성적, 전체 대회 이력을 정리한 페이지입니다."
    raw_json = json.dumps(raw, ensure_ascii=False, separators=(",", ":"))
    birth_js = "null" if birth is None else str(int(birth))

    template = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<script src="../../support.js"></script>
</head>
<body>
<x-dc>
<helmet>
<title>__NAME__ 선수 기록</title>
<meta name="description" content="__DESCRIPTION__">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css">
<style>
  body{margin:0;background:#F3F5F8;-webkit-font-smoothing:antialiased;text-wrap:pretty}
  a{color:#2E63F6;text-decoration:none}
  a:hover{color:#1B47C4}
  *{box-sizing:border-box}
</style>
</helmet>

<div style="font-family:'Pretendard Variable',Pretendard,-apple-system,BlinkMacSystemFont,'Apple SD Gothic Neo',sans-serif;color:#17181C;line-height:1.55;background:#F3F5F8;padding-bottom:60px">
  <div style="max-width:560px;margin:0 auto;padding:0 16px;display:flex;flex-direction:column;gap:12px">

    <div style="padding:16px 2px 4px">
      <a href="../" onclick="if(window.history.length>1){window.history.back();return false;}" style="font-size:14px;font-weight:600;color:#6B6F78">← 전체 선수 목록</a>
    </div>

    <header style="background:#fff;border-radius:20px;padding:22px 20px 20px;display:flex;flex-direction:column;gap:18px">
      <div>
        <h1 style="margin:0;font-size:30px;font-weight:800;letter-spacing:-0.03em">__NAME__</h1>
        <p style="margin:5px 0 0;font-size:15px;color:#6B6F78">__SUBTITLE__</p>
      </div>
      <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px">
        <div style="background:#F5F7FA;border-radius:14px;padding:12px 12px 11px">
          <div style="font-size:22px;font-weight:800;letter-spacing:-0.02em">{{ totalRaces }}</div>
          <div style="font-size:12.5px;color:#8A8F99;margin-top:1px">전체 경기</div>
        </div>
        <div style="background:#E9F0FF;border-radius:14px;padding:12px 12px 11px">
          <div style="font-size:22px;font-weight:800;letter-spacing:-0.02em;color:#2E63F6">{{ goldCount }}</div>
          <div style="font-size:12.5px;color:#5B7BD4;margin-top:1px">1등</div>
        </div>
        <div style="background:#F5F7FA;border-radius:14px;padding:12px 12px 11px">
          <div style="font-size:22px;font-weight:800;letter-spacing:-0.02em">{{ seasonSpan }}</div>
          <div style="font-size:12.5px;color:#8A8F99;margin-top:1px">{{ yearRangeLabel }}</div>
        </div>
      </div>
    </header>

    <section style="background:#fff;border-radius:20px;padding:22px 20px">
      <h2 style="margin:0 0 4px;font-size:18px;font-weight:800;letter-spacing:-0.02em">해마다 가장 잘한 등수</h2>
      <p style="margin:0 0 18px;font-size:14px;color:#6B6F78">막대가 길수록 좋은 성적이에요. 진한 막대는 1등을 한 해예요.</p>
      <div style="display:flex;flex-direction:column;gap:5px">
        <sc-for list="{{ yearBest }}" as="y" hint-placeholder-count="10">
          <div style="display:flex;align-items:center;gap:10px">
            <span style="font-size:13px;color:#8A8F99;width:38px;flex:none;font-variant-numeric:tabular-nums">{{ y.yearShort }}</span>
            <span style="font-size:12px;color:#C6CBD4;width:30px;flex:none">{{ y.age }}</span>
            <div style="flex:1;height:20px;background:#F2F4F7;border-radius:6px;position:relative">
              <span style="{{ y.barStyle }}"></span>
            </div>
            <span style="font-size:13.5px;font-weight:700;width:34px;text-align:right;flex:none;color:{{ y.color }}">{{ y.label }}</span>
          </div>
        </sc-for>
      </div>
      <p style="margin:16px 0 0;font-size:13px;color:#9BA0AA">{{ missingNote }}</p>
    </section>

    <section style="background:#fff;border-radius:20px;padding:22px 16px 20px">
      <div style="padding:0 4px">
        <h2 style="margin:0 0 4px;font-size:18px;font-weight:800;letter-spacing:-0.02em">전체 대회 기록</h2>
        <p style="margin:0 0 14px;font-size:14px;color:#6B6F78">대회 하나가 카드 하나예요. 종목별 등수는 오른쪽에 나와요.</p>
      </div>

      <div style="display:flex;gap:6px;overflow-x:auto;padding:0 4px 12px;-webkit-overflow-scrolling:touch">
        <sc-for list="{{ distChips }}" as="c" hint-placeholder-count="5">
          <button type="button" onClick="{{ c.onClick }}" style="{{ c.style }}">{{ c.label }}</button>
        </sc-for>
      </div>
      <div style="display:flex;gap:6px;padding:0 4px 16px">
        <button type="button" onClick="{{ toggleGold }}" style="{{ goldChipStyle }}">1등만 보기</button>
        <button type="button" onClick="{{ toggleOrder }}" style="flex:none;min-height:44px;padding:0 16px;border:0;border-radius:12px;background:#F2F4F7;color:#5B5F68;font-size:14px;font-weight:600;font-family:inherit;cursor:pointer" style-hover="background:#E9ECF1">{{ orderLabel }}</button>
      </div>

      <sc-if value="{{ isEmpty }}" hint-placeholder-val="{{ false }}">
        <div style="padding:36px 12px;text-align:center;font-size:14.5px;color:#8A8F99">조건에 맞는 기록이 없습니다.</div>
      </sc-if>

      <div style="display:flex;flex-direction:column;gap:22px">
        <sc-for list="{{ groups }}" as="g" hint-placeholder-count="4">
          <div>
            <div style="position:sticky;top:0;z-index:2;background:#fff;padding:6px 4px 10px;display:flex;align-items:baseline;gap:8px">
              <b style="font-size:17px;font-weight:800;letter-spacing:-0.02em">{{ g.year }}년</b>
              <span style="font-size:13px;color:#9BA0AA">{{ g.meta }}</span>
            </div>
            <div style="display:flex;flex-direction:column;gap:8px">
              <sc-for list="{{ g.comps }}" as="c" hint-placeholder-count="3">
                <div style="background:#FAFBFC;border-radius:16px;padding:14px 14px 12px;display:flex;flex-direction:column;gap:10px">
                  <div style="display:flex;flex-direction:column;gap:3px">
                    <b style="font-size:15px;font-weight:700;letter-spacing:-0.01em;line-height:1.4">{{ c.short }}</b>
                  </div>
                  <div style="display:flex;flex-direction:column;gap:1px">
                    <sc-for list="{{ c.results }}" as="r" hint-placeholder-count="2">
                      <div style="display:flex;align-items:center;gap:10px;padding:7px 2px;border-top:1px solid #F0F2F5">
                        <span style="font-size:14.5px;font-weight:600;color:#3A3D45;width:62px;flex:none;font-variant-numeric:tabular-nums">{{ r.dist }}</span>
                        <span style="font-size:12.5px;color:#A9AEB8">{{ r.note }}</span>
                        <span style="{{ r.badgeStyle }}">{{ r.rankLabel }}</span>
                      </div>
                    </sc-for>
                  </div>
                </div>
              </sc-for>
            </div>
          </div>
        </sc-for>
      </div>
    </section>

    <section style="background:#fff;border-radius:20px;padding:22px 20px">
      <h2 style="margin:0 0 14px;font-size:18px;font-weight:800;letter-spacing:-0.02em">용어 안내</h2>
      <div style="display:flex;flex-direction:column;gap:12px">
        <div style="display:flex;gap:10px;align-items:flex-start">
          <span style="flex:none;min-width:46px;text-align:center;font-size:12px;font-weight:700;color:#5B5F68;background:#F2F4F7;border-radius:8px;padding:4px 8px">A그룹</span>
          <p style="margin:0;font-size:14px;color:#5B5F68">상위 선수들이 겨루는 결승입니다. 같은 등수라도 A그룹이 더 높은 순위입니다.</p>
        </div>
        <div style="display:flex;gap:10px;align-items:flex-start">
          <span style="flex:none;min-width:46px;text-align:center;font-size:12px;font-weight:700;color:#5B5F68;background:#F2F4F7;border-radius:8px;padding:4px 8px">B그룹</span>
          <p style="margin:0;font-size:14px;color:#5B5F68">A그룹에 들지 못한 선수들의 결승입니다.</p>
        </div>
        <div style="display:flex;gap:10px;align-items:flex-start">
          <span style="flex:none;min-width:46px;text-align:center;font-size:12px;font-weight:700;color:#5B5F68;background:#F2F4F7;border-radius:8px;padding:4px 8px">종합</span>
          <p style="margin:0;font-size:14px;color:#5B5F68">전국동계체육대회처럼 그룹을 나누지 않고 매긴 순위입니다.</p>
        </div>
        <div style="display:flex;gap:10px;align-items:flex-start">
          <span style="flex:none;min-width:46px;text-align:center;font-size:12px;font-weight:700;color:#5B5F68;background:#F2F4F7;border-radius:8px;padding:4px 8px">준결승</span>
          <p style="margin:0;font-size:14px;color:#5B5F68">결승 전 단계입니다. 조 안에서 매긴 등수라 전체 순위와 다릅니다.</p>
        </div>
      </div>
    </section>

    <footer style="padding:8px 6px 0;font-size:13px;color:#9BA0AA">
      공개된 경기 결과를 정리한 페이지입니다. 출처: 대한체육회 경기결과 시스템
    </footer>
  </div>
</div>
</x-dc>
<script type="text/x-dc" data-dc-script>
const BIRTH = __BIRTH_JS__;
const RAW = __RAW_JSON__;
const SEASON_SPAN = __SEASON_SPAN_JSON__;
const YEAR_RANGE = __YEAR_RANGE_JSON__;
const MISSING_NOTE = __MISSING_NOTE_JSON__;

function badge(rank, semi){
  const base = "margin-left:auto;flex:none;min-width:46px;text-align:center;font-size:14px;font-weight:700;border-radius:10px;padding:5px 10px;font-variant-numeric:tabular-nums;";
  if (semi) return base + "background:#F2F4F7;color:#9BA0AA";
  if (rank === 1) return base + "background:#2E63F6;color:#fff";
  if (rank <= 3) return base + "background:#E9F0FF;color:#2E63F6";
  return base + "background:#F2F4F7;color:#5B5F68";
}

class Component extends DCLogic {
  state = { dist: 0, goldOnly: false, newestFirst: true };

  renderVals(){
    const { dist, goldOnly, newestFirst } = this.state;

    let total = 0, gold = 0;
    for (const [, comps] of RAW) for (const [, rs] of comps) for (const r of rs){ total++; if (r[1] === 1 && !r[3]) gold++; }

    const yearBest = RAW.map(([year, comps]) => {
      let best = 99;
      for (const [, rs] of comps) for (const r of rs) if (!r[3] && r[1] < best) best = r[1];
      if (best === 99) return null;
      const w = Math.max((11 - Math.min(best, 10)) / 10 * 100, 6);
      const isGold = best === 1;
      const ageText = BIRTH === null ? "-" : (year - BIRTH) + "살";
      return {
        yearShort: year,
        age: ageText,
        label: best + "등",
        color: isGold ? "#2E63F6" : "#5B5F68",
        barStyle: "position:absolute;left:0;top:0;height:20px;border-radius:6px;width:" + w + "%;background:" + (isGold ? "#2E63F6" : best <= 3 ? "#A9C3FA" : "#D3D8E0")
      };
    }).filter(Boolean);

    const years = newestFirst ? RAW : RAW.slice().reverse();
    const groups = [];
    for (const [year, comps] of years){
      const outComps = [];
      let count = 0, golds = 0;
      for (const [name, rs] of comps){
        const kept = rs.filter(r => (dist === 0 || r[0] === dist) && (!goldOnly || (r[1] === 1 && !r[3])));
        if (!kept.length) continue;
        count += kept.length;
        golds += kept.filter(r => r[1] === 1 && !r[3]).length;
        outComps.push({
          short: name,
          results: kept.map(r => ({
            dist: r[0] + "m",
            note: r[3] ? "준결승" : (r[2] === "종합" ? "종합 순위" : r[2] + "그룹 결승"),
            rankLabel: r[1] + "등",
            badgeStyle: badge(r[1], r[3])
          }))
        });
      }
      if (outComps.length) groups.push({
        year,
        meta: (BIRTH === null ? "" : (year - BIRTH) + "살 · ") + count + "경기" + (golds ? " · 1등 " + golds : ""),
        comps: outComps
      });
    }

    const chip = (on) => "flex:none;min-height:44px;padding:0 16px;border:0;border-radius:12px;font-size:14px;font-weight:600;font-family:inherit;cursor:pointer;white-space:nowrap;"
      + (on ? "background:#17181C;color:#fff" : "background:#F2F4F7;color:#5B5F68");

    const distChips = [0,500,1000,1500,3000].map(d => ({
      label: d === 0 ? "전체 종목" : d + "m",
      style: chip(dist === d),
      onClick: () => this.setState({dist: d})
    }));

    return {
      totalRaces: total + "회",
      goldCount: gold + "회",
      seasonSpan: SEASON_SPAN,
      yearRangeLabel: YEAR_RANGE,
      missingNote: MISSING_NOTE,
      yearBest, groups,
      isEmpty: groups.length === 0,
      distChips,
      goldChipStyle: chip(goldOnly),
      toggleGold: () => this.setState(s => ({goldOnly: !s.goldOnly})),
      orderLabel: newestFirst ? "최신순" : "오래된순",
      toggleOrder: () => this.setState(s => ({newestFirst: !s.newestFirst}))
    };
  }
}
</script>
</body>
</html>
"""

    return (
        template.replace("__NAME__", esc_html(name))
        .replace("__DESCRIPTION__", esc_html(description))
        .replace("__SUBTITLE__", esc_html(subtitle))
        .replace("__BIRTH_JS__", birth_js)
        .replace("__RAW_JSON__", raw_json)
        .replace("__SEASON_SPAN_JSON__", json.dumps(season_span, ensure_ascii=False))
        .replace("__YEAR_RANGE_JSON__", json.dumps(year_range, ensure_ascii=False))
        .replace("__MISSING_NOTE_JSON__", json.dumps(missing_note, ensure_ascii=False))
    )


def build_athlete_list_html(payload):
    athletes = payload.get("athletes", [])
    cards = []
    for athlete in athletes:
        id_no = as_id(athlete.get("idNo"))
        if not id_no:
            continue
        name = str(athlete.get("name", "") or id_no).strip()
        birth = athlete.get("birth")
        team = str(athlete.get("team", "") or "-").strip()
        gender = str(athlete.get("gender", "") or "").strip()
        history = athlete.get("history", [])
        race_count = len(history)
        gold_count = sum(1 for item in history if item.get("rank") == 1 and not item.get("sf"))
        meta_parts = [f"{birth}년생" if birth is not None else "출생년도 미상", team]
        if gender:
            meta_parts.append(gender)
        meta_text = " · ".join(meta_parts)
        cards.append(
            "<a href=\"./{id_no}/\" style=\"display:block;text-decoration:none;color:inherit;background:#FAFBFC;border-radius:16px;padding:14px 14px 12px\">"
            "<div style=\"display:flex;align-items:center;justify-content:space-between;gap:8px\">"
            "<b style=\"font-size:16px;font-weight:800;letter-spacing:-0.01em\">{name}</b>"
            "<span style=\"font-size:12.5px;font-weight:700;color:#2E63F6\">자세히 보기</span>"
            "</div>"
            "<div style=\"margin-top:5px;font-size:13.5px;color:#6B6F78\">{meta}</div>"
            "<div style=\"margin-top:10px;display:flex;gap:8px\">"
            "<span style=\"font-size:12.5px;color:#8A8F99;background:#F2F4F7;border-radius:999px;padding:4px 9px\">전체 {races}경기</span>"
            "<span style=\"font-size:12.5px;color:#5B7BD4;background:#E9F0FF;border-radius:999px;padding:4px 9px\">1등 {golds}회</span>"
            "</div>"
            "</a>".format(
                id_no=esc_html(id_no),
                name=esc_html(name),
                meta=esc_html(meta_text),
                races=race_count,
                golds=gold_count,
            )
        )

    cards_html = "\n".join(cards) if cards else '<div style="font-size:14px;color:#8A8F99">선수 데이터가 없습니다.</div>'
    return """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>쇼트트랙 선수 목록</title>
<meta name="description" content="선수 개별 기록 페이지로 이동할 수 있는 쇼트트랙 선수 목록입니다.">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css">
<style>
body{margin:0;background:#F3F5F8;-webkit-font-smoothing:antialiased;text-wrap:pretty}
a{color:#2E63F6;text-decoration:none}
a:hover{color:#1B47C4}
</style>
</head>
<body>
<div style="font-family:'Pretendard Variable',Pretendard,-apple-system,BlinkMacSystemFont,'Apple SD Gothic Neo',sans-serif;color:#17181C;line-height:1.55;background:#F3F5F8;padding-bottom:60px">
  <div style="max-width:560px;margin:0 auto;padding:0 16px;display:flex;flex-direction:column;gap:12px">
    <div style="padding:16px 2px 4px">
      <a href="../" style="font-size:14px;font-weight:600;color:#6B6F78">← 메인으로</a>
    </div>
    <header style="background:#fff;border-radius:20px;padding:22px 20px 20px;display:flex;flex-direction:column;gap:8px">
      <h1 style="margin:0;font-size:29px;font-weight:800;letter-spacing:-0.03em">전체 선수 목록</h1>
      <p style="margin:0;font-size:14px;color:#6B6F78">선수를 선택하면 개별 기록 페이지로 이동할 수 있어요.</p>
    </header>
    <section style="background:#fff;border-radius:20px;padding:16px;display:flex;flex-direction:column;gap:8px">
      __CARDS_HTML__
    </section>
  </div>
</div>
</body>
</html>
""".replace("__CARDS_HTML__", cards_html)


def write_athlete_index(payload):
    ATHLETE_DIR.mkdir(parents=True, exist_ok=True)
    path = ATHLETE_DIR / "index.html"
    path.write_text(build_athlete_list_html(payload), encoding="utf-8")
    return path


def write_athlete_pages(payload):
    count = 0
    for athlete in payload.get("athletes", []):
        id_no = as_id(athlete.get("idNo"))
        if not id_no:
            continue
        path = ATHLETE_DIR / id_no / "index.html"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(build_athlete_html(athlete), encoding="utf-8")
        count += 1
    return count


def sitemap_urls(payload):
    urls = [site_url(""), site_url("athlete/")]
    seen = set(urls)
    for athlete in payload.get("athletes", []):
        id_no = as_id(athlete.get("idNo"))
        if not id_no:
            continue
        url = site_url(f"athlete/{id_no}/")
        if url in seen:
            continue
        urls.append(url)
        seen.add(url)
    return urls


def write_sitemap(payload):
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for url in sitemap_urls(payload):
        lines.append(f"  <url><loc>{html.escape(url, quote=True)}</loc></url>")
    lines.append("</urlset>")
    SITEMAP_XML.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return SITEMAP_XML


def write_robots():
    lines = [
        "User-agent: *",
        "Allow: /",
        "",
        f"Sitemap: {site_url('sitemap.xml')}",
        "",
    ]
    ROBOTS_TXT.write_text("\n".join(lines), encoding="utf-8")
    return ROBOTS_TXT


def main():
    try:
        payload = build_payload()
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc))
        return

    SITE_HTML.parent.mkdir(parents=True, exist_ok=True)
    SITE_HTML.write_text(build_html(payload), encoding="utf-8")
    athlete_index_path = write_athlete_index(payload)
    athlete_page_count = write_athlete_pages(payload)
    sitemap_path = write_sitemap(payload)
    robots_path = write_robots()
    print(f"[ok] 생성 완료: {SITE_HTML}")
    print(f"[ok] 생성 완료: {athlete_index_path}")
    print(f"[ok] 생성 완료: {ATHLETE_DIR}/{{idNo}}/index.html ({athlete_page_count}개)")
    print(f"[ok] 생성 완료: {sitemap_path}")
    print(f"[ok] 생성 완료: {robots_path}")


if __name__ == "__main__":
    main()