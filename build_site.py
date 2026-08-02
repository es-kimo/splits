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


def build_payload():
    frames = {name: read_csv(name) for name in INPUT_FILES}
    placements = frames["placements.csv"]
    summary = frames["youth_summary.csv"]
    matrix = frames["age_matrix.csv"]
    athlete_info = frames["athlete_info.csv"]
    coverage = frames["coverage.csv"]

    placements["순위_num"] = placements["순위"].map(as_int)
    placements["대회연도_num"] = placements["대회연도"].map(as_int)
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
        info_by_name[name] = {"birthYear": births[0] if births else None, "team": teams[0] if teams else "-"}

    summary_by_name = {}
    for _, row in summary.iterrows():
        name = str(row.get("이름", "")).strip()
        if not name:
            continue
        summary_by_name[name] = {
            "firstAge": as_int(row.get("최초_출전나이")),
            "elemBest": as_int(row.get("초등부_최고순위")),
            "elemWorst": as_int(row.get("초등부_최저순위")),
            "elemCount": as_int(row.get("초등부_출전수")) or 0,
        }

    records_by_name = {name: [] for name in names}
    for _, row in placements.iterrows():
        name = str(row.get("이름", "")).strip()
        if not name:
            continue
        if name not in records_by_name:
            records_by_name[name] = []
        records_by_name[name].append(
            {
                "year": as_int(row.get("대회연도")),
                "meet": str(row.get("대회명", "")).strip(),
                "distance": as_int(row.get("거리")),
                "rank": as_int(row.get("순위")),
            }
        )
    for name in records_by_name:
        records_by_name[name].sort(
            key=lambda r: (
                r["year"] if r["year"] is not None else 9999,
                r["meet"],
                r["distance"] if r["distance"] is not None else 9999,
                r["rank"] if r["rank"] is not None else 9999,
            )
        )

    matrix_by_name = {}
    for _, row in matrix.iterrows():
        name = str(row.get("이름", "")).strip()
        if not name:
            continue
        matrix_by_name[name] = {age: as_int(row.get(age, "")) for age in AGES}

    athletes = []
    for name in names:
        s = summary_by_name.get(name, {})
        info = info_by_name.get(name, {"birthYear": None, "team": "-"})
        athletes.append(
            {
                "name": name,
                "birthYear": info["birthYear"],
                "team": info["team"],
                "firstAge": s.get("firstAge"),
                "elementary": {
                    "best": s.get("elemBest"),
                    "worst": s.get("elemWorst"),
                    "median": elem_median.get(name),
                    "count": s.get("elemCount", 0),
                },
                "records": records_by_name.get(name, []),
            }
        )

    age_rows = [{"name": name, "ages": matrix_by_name.get(name, {age: None for age in AGES})} for name in names]
    matrix_ranks = [v for row in age_rows for v in row["ages"].values() if isinstance(v, int)]
    years = [as_int(v) for v in coverage.get("대회연도", pd.Series(dtype=str)).tolist()]
    years = [y for y in years if y is not None]
    if not years:
        years = [y for y in placements["대회연도_num"].tolist() if y is not None]
    year_start, year_end = (min(years), max(years)) if years else (None, None)
    return {
        "meta": {
            "athleteCount": len(names),
            "placementCount": int(len(placements)),
            "yearStart": year_start,
            "yearEnd": year_end,
            "rankMin": min(matrix_ranks) if matrix_ranks else 1,
            "rankMax": max(matrix_ranks) if matrix_ranks else 1,
        },
        "ages": [int(age) for age in AGES],
        "ageMatrix": age_rows,
        "athletes": athletes,
    }


def build_html(payload):
    count = format(payload["meta"]["placementCount"], ",")
    years = f'{payload["meta"]["yearStart"]}~{payload["meta"]["yearEnd"]}년' if payload["meta"]["yearStart"] else "-"
    data_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    template = """<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>국가대표 14명의 유년기 기록</title><style>
:root{--bg:#fff;--fg:#171717;--muted:#666;--line:#ddd;--panel:#f7f7f7;--empty:#ececec;--heat:48,85,130}*{box-sizing:border-box}body{margin:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Apple SD Gothic Neo','Noto Sans KR',sans-serif;background:var(--bg);color:var(--fg);line-height:1.5}main{max-width:1080px;margin:0 auto;padding:16px}h1,h2{margin:0 0 8px}h1{font-size:1.6rem}h2{font-size:1.2rem}.subtitle,.hint{color:var(--muted);margin:0 0 12px}.metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin:12px 0 18px}.metric{background:var(--panel);border:1px solid var(--line);padding:10px;text-align:center;font-weight:700}section{margin:0 0 18px}table{width:100%;border-collapse:collapse;table-layout:fixed}th,td{border:1px solid var(--line);padding:6px;text-align:center;font-size:.82rem}th:first-child,td:first-child{text-align:left;font-weight:700}.rank{font-weight:600}.rank1{font-weight:800}.missing{background:repeating-linear-gradient(-45deg,var(--empty),var(--empty) 6px,transparent 6px,transparent 12px);color:var(--muted);font-size:.72rem}#age-stack{display:none}.age-row{border:1px solid var(--line);margin:0 0 8px;padding:8px}.age-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px}.age-cell{border:1px solid var(--line);padding:6px;text-align:center;font-size:.8rem}.age-label{display:block;color:var(--muted);font-size:.72rem}.low-sample{opacity:.58}.small-note{font-size:.85rem;color:var(--muted);margin:6px 0 0}.sort{margin:0 0 10px;font-size:.9rem}select{border:1px solid var(--line);background:var(--bg);color:var(--fg);padding:4px 6px}#cards{display:grid;gap:8px}details{border:1px solid var(--line);background:var(--panel)}summary{cursor:pointer;padding:10px;font-weight:700}.card-body{padding:0 10px 10px}.meta-grid{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin:8px 0}.meta-grid div{background:var(--bg);border:1px solid var(--line);padding:6px;font-size:.84rem}.year-block{margin:8px 0}.year-title{font-weight:700;margin:0 0 4px}.list{font-size:.82rem;border:1px solid var(--line)}.list-row{display:grid;grid-template-columns:1fr 72px 58px;border-top:1px solid var(--line)}.list-row:first-child{border-top:0}.list-row span{padding:6px}.limits{background:var(--panel);border:1px solid var(--line);padding:10px}footer{padding:8px 0 16px;color:var(--muted);font-size:.88rem}@media (max-width:860px){#age-table{display:none}#age-stack{display:block}.metrics{grid-template-columns:1fr}main{padding:12px}}@media (prefers-color-scheme:dark){:root{--bg:#0f1115;--fg:#ededed;--muted:#a8adb5;--line:#31353d;--panel:#191c22;--empty:#252932;--heat:102,160,224}}</style></head><body><main>
<header><h1>국가대표 14명의 유년기 기록</h1><p class="subtitle">2026/27시즌 쇼트트랙 국가대표 선발 선수들이 7세부터 현재까지 남긴 공식 대회 성적 1,642건</p><div class="metrics"><div class="metric">선수 __ATHLETE_COUNT__명</div><div class="metric">성적 __PLACEMENT_COUNT__건</div><div class="metric">__YEARS__</div></div></header>
<section><h2>나이별 성적 표</h2><div id="age-table"></div><div id="age-stack"></div><p class="hint">빈 칸은 해당 나이에 기록이 없음을 뜻합니다. 성적이 나쁜 것과 다릅니다.</p></section>
<section><h2>초등부 성적 요약 표</h2><div id="elem-summary"></div><p class="small-note">출전수가 적은 선수의 중앙값은 표본이 부족합니다.</p><p class="small-note">노아름(1991년생)은 초등부 기록이 남아 있지 않습니다.</p></section>
<section><h2>선수별 카드</h2><p class="sort">정렬 <select id="sort-cards"><option value="name">이름순</option><option value="first-age">최초 출전 나이순</option></select></p><div id="cards"></div></section>
<section><h2>데이터 한계</h2><div class="limits"><p>출처: 대한체육회 경기결과 시스템 (result.sports.or.kr)</p><p>2012년 이전은 전산화가 부분적이다. 1990년대 중반 이전 출생 선수는 유년기 기록이 누락돼 있다. (노아름 1991년생: 초등부 기록 0건. 출전하지 않은 것이 아니라 기록이 남아 있지 않은 것)</p><p>나이는 대회연도 - 출생년도. 만 나이보다 최대 1살 높다.</p><p>순위는 채점종합/결승 기준. 예선·준결승의 조 내 순위는 제외했다.</p><p>기록(시간)은 표시하지 않는다. 쇼트트랙은 착순 경기라 결승에서 전술적으로 느리게 타는 경우가 많아 기록으로 실력을 비교하기 어렵다.</p><p>이상치 35건이 검출됐으나 원본 그대로 두었다.</p></div></section>
<footer>이 페이지는 공개된 경기 기록을 정리한 것입니다. 대한빙상경기연맹 및 대한체육회와 무관합니다.</footer></main>
<script>const DATA=__DATA_JSON__;const h=(tag,txt)=>{const e=document.createElement(tag);if(txt!==undefined)e.textContent=txt;return e};const fmt=v=>v===null||v===undefined?"-":(Number.isInteger(v)?String(v):v.toFixed(1));const tone=r=>{const min=DATA.meta.rankMin,max=DATA.meta.rankMax;if(max<=min)return .55;const k=(r-min)/(max-min);return .15+(1-k)*.55};function fillHeat(el,rank){if(rank===null||rank===undefined){el.className+=" missing";el.textContent="없음";return}el.className+=" rank";if(rank===1)el.className+=" rank1";el.textContent=rank;el.style.backgroundColor=`rgba(var(--heat),${tone(rank)})`}function renderAge(){const table=h("table"),head=h("tr");head.appendChild(h("th","선수"));for(const age of DATA.ages)head.appendChild(h("th",`${age}세`));table.appendChild(head);for(const row of DATA.ageMatrix){const tr=h("tr");tr.appendChild(h("td",row.name));for(const age of DATA.ages){const td=h("td");fillHeat(td,row.ages[String(age)]);tr.appendChild(td)}table.appendChild(tr)}document.getElementById("age-table").appendChild(table);const stackRoot=document.getElementById("age-stack");for(const row of DATA.ageMatrix){const box=h("div");box.className="age-row";box.appendChild(h("strong",row.name));const grid=h("div");grid.className="age-grid";for(const age of DATA.ages){const cell=h("div");cell.className="age-cell";const label=h("span",`${age}세`);label.className="age-label";const val=h("span");fillHeat(val,row.ages[String(age)]);cell.appendChild(label);cell.appendChild(val);grid.appendChild(cell)}box.appendChild(grid);stackRoot.appendChild(box)}}function renderElemSummary(){const normMed=v=>Number.isFinite(v)?v:9999;const rows=DATA.athletes.filter(a=>(a.elementary?.count??0)>0&&a.name!=="노아름").map(a=>({name:a.name,count:a.elementary.count,best:a.elementary.best,median:a.elementary.median,worst:a.elementary.worst})).sort((a,b)=>(normMed(a.median)-normMed(b.median))||a.name.localeCompare(b.name,"ko"));const table=h("table"),head=h("tr");["이름","최고순위","출전수","중앙값","최저순위"].forEach(c=>head.appendChild(h("th",c)));table.appendChild(head);for(const r of rows){const tr=h("tr");if((r.count??0)<10)tr.className="low-sample";tr.appendChild(h("td",(r.count??0)<10?`${r.name}*`:r.name));tr.appendChild(h("td",fmt(r.best)));tr.appendChild(h("td",fmt(r.count)));tr.appendChild(h("td",fmt(r.median)));tr.appendChild(h("td",fmt(r.worst)));table.appendChild(tr)}document.getElementById("elem-summary").appendChild(table)}const recordsByYear=records=>{const grouped=new Map();for(const r of records){const y=r.year??"연도 미상";if(!grouped.has(y))grouped.set(y,[]);grouped.get(y).push(r)}return [...grouped.entries()].sort((a,b)=>String(a[0]).localeCompare(String(b[0])))};function sortAthletes(mode){const list=[...DATA.athletes];if(mode==="first-age"){list.sort((a,b)=>{const ax=a.firstAge??999,bx=b.firstAge??999;return ax===bx?a.name.localeCompare(b.name,"ko"):ax-bx});return list}return list.sort((a,b)=>a.name.localeCompare(b.name,"ko"))}function renderCards(){const mode=document.getElementById("sort-cards").value,root=document.getElementById("cards");root.textContent="";for(const a of sortAthletes(mode)){const d=h("details"),s=h("summary",`${a.name} · ${a.birthYear??"-"}년생 · ${a.team||"-"}`),body=h("div"),m=h("div");body.className="card-body";m.className="meta-grid";m.appendChild(h("div",`최초 출전 나이: ${a.firstAge??"-"}`));m.appendChild(h("div",`초등부 최고순위: ${a.elementary.best??"-"}`));m.appendChild(h("div",`초등부 최저순위: ${a.elementary.worst??"-"}`));m.appendChild(h("div",`초등부 중앙값: ${fmt(a.elementary.median)}`));m.appendChild(h("div",`초등부 출전수: ${a.elementary.count??0}`));body.appendChild(m);for(const [year,rows] of recordsByYear(a.records)){const yb=h("div"),title=h("p",String(year)),list=h("div");yb.className="year-block";title.className="year-title";list.className="list";yb.appendChild(title);for(const r of rows){const line=h("div");line.className="list-row";line.appendChild(h("span",r.meet||"-"));line.appendChild(h("span",r.distance?`${r.distance}m`:"-"));line.appendChild(h("span",r.rank??"-"));list.appendChild(line)}yb.appendChild(list);body.appendChild(yb)}d.appendChild(s);d.appendChild(body);root.appendChild(d)}}renderAge();renderElemSummary();renderCards();document.getElementById("sort-cards").addEventListener("change",renderCards);</script></body></html>"""
    return (
        template.replace("__ATHLETE_COUNT__", str(payload["meta"]["athleteCount"]))
        .replace("__PLACEMENT_COUNT__", count)
        .replace("__YEARS__", years)
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
