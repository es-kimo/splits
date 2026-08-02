import json
from pathlib import Path

import pandas as pd

DATA_DIR = Path("data")
SITE_HTML = Path("site/index.html")
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

    placements["순위_num"] = placements["순위"].map(as_int)
    placements["대회연도_num"] = placements["대회연도"].map(as_int)
    placements["나이_추정_num"] = placements["나이_추정"].map(as_int)

    elem = placements[(placements["학령구간"] == "초등") & placements["순위_num"].notna()].copy()
    elem_median = elem.groupby("이름")["순위_num"].median().to_dict()

    names = [n for n in matrix["이름"].astype(str).tolist() if n.strip()]
    for candidate in summary["이름"].astype(str).tolist() + athlete_info["이름"].astype(str).tolist():
        candidate = candidate.strip()
        if candidate and candidate not in names:
            names.append(candidate)

    info_by_name = {}
    for name, group in athlete_info.groupby("이름", sort=False):
        teams = [v.strip() for v in group.get("소속팀", pd.Series(dtype=str)).tolist() if str(v).strip()]
        births = [as_int(v) for v in group.get("출생년도", pd.Series(dtype=str)).tolist() if as_int(v) is not None]
        info_by_name[name] = {"birth": births[0] if births else None, "team": teams[0] if teams else "-"}

    summary_by_name = {}
    for _, row in summary.iterrows():
        name = str(row.get("이름", "")).strip()
        if not name:
            continue
        summary_by_name[name] = {
            "first": as_int(row.get("최초_출전나이")),
            "elemBest": as_int(row.get("초등부_최고순위")),
            "elemWorst": as_int(row.get("초등부_최저순위")),
            "elemCount": as_int(row.get("초등부_출전수")) or 0,
        }

    matrix_by_name = {}
    for _, row in matrix.iterrows():
        name = str(row.get("이름", "")).strip()
        if not name:
            continue
        matrix_by_name[name] = {age: as_int(row.get(age, "")) for age in AGES}

    athletes = []
    for name in names:
        s = summary_by_name.get(name, {})
        info = info_by_name.get(name, {"birth": None, "team": "-"})
        median = elem_median.get(name)
        median_value = float(median) if median is not None else None
        athletes.append(
            {
                "name": name,
                "birth": info["birth"],
                "team": info["team"],
                "first": s.get("first"),
                "ages": matrix_by_name.get(name, {age: None for age in AGES}),
                "elem": {
                    "best": s.get("elemBest"),
                    "median": median_value,
                    "worst": s.get("elemWorst"),
                    "count": s.get("elemCount", 0),
                },
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
.detail-state{margin-left:auto;font-size:13px;color:#2E63F6;font-weight:600}
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
        <b class="age-name">${esc(a.name)}</b>
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
        <b class="elem-name">${esc(a.name)}</b>
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
        <span class="detail-state">${isOpen?"접기":"펼치기"}</span>
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


def main():
    try:
        payload = build_payload()
    except FileNotFoundError as exc:
        print(str(exc))
        return

    SITE_HTML.parent.mkdir(parents=True, exist_ok=True)
    SITE_HTML.write_text(build_html(payload), encoding="utf-8")
    print(f"[ok] 생성 완료: {SITE_HTML}")


if __name__ == "__main__":
    main()