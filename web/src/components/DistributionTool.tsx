import { useEffect, useMemo, useState } from "react";

import type { DistributionDoc, PeerDistributionRow } from "../lib/types";

type InputMode = "time" | "rank";
type CompareScope = "same-birth-year" | "all-birth-years";

interface Props extends DistributionDoc {
  homeUrl?: string;
}

interface ThinAction {
  label: string;
  onClick: () => void;
}

const NOTES = [
  {
    q: "어떤 경기의 기록인가요?",
    a: "기록은 예선 기준입니다. 결승은 경기 운영 영향이 커서 실력 비교에는 예선 기록이 더 안정적입니다.",
  },
  {
    q: "출생연도 포함/통합 비교는 무엇이 다른가요?",
    a: "출생연도 포함 비교는 동년생 안에서 현재 위치를 봅니다. 통합 비교는 표본이 커서 변동이 줄어들지만 연도별 환경 차이가 함께 섞입니다.",
  },
  {
    q: "어떤 종목의 기록인가요?",
    a: "쇼트트랙 기록만 집계합니다. 함께 열리는 스피드스케이팅 경기 기록은 제외했습니다.",
  },
  {
    q: "기록과 등수의 비교 인원이 다른 이유는 무엇인가요?",
    a: "기록은 예선 기록을 모두 사용하고, 등수는 학령 경기의 결승·채점종합만 사용합니다. 두 통계의 대상 경기가 달라 비교 인원도 다릅니다.",
  },
  {
    q: "위치가 낮으면 진로 판단에 써도 되나요?",
    a: "아닙니다. 이 결과는 현재 분포에서의 상대 위치만 보여줍니다. 성장 속도와 환경 요인은 이 데이터에 포함되지 않습니다.",
  },
  {
    q: "이 데이터로 알 수 없는 것은 무엇인가요?",
    a: "훈련량, 부상, 성장 시기, 지도 환경처럼 실제 경기력에 큰 영향을 주는 요소는 포함하지 않습니다.",
  },
];

export default function DistributionTool(props: Props) {
  const allRows = props.rows;
  const aggregatedRows = useMemo(() => aggregateRows(allRows), [allRows]);
  const initialRow = allRows.find((row) => !row.timeInsufficient || !row.rankInsufficient) ?? allRows[0];

  const [scope, setScope] = useState<CompareScope>("same-birth-year");
  const [gender, setGender] = useState(initialRow?.gender ?? "");
  const [distance, setDistance] = useState<number | null>(initialRow?.distance ?? null);
  const [birthYear, setBirthYear] = useState<number | null>(initialRow?.birthYear ?? null);
  const [mode, setMode] = useState<InputMode>("time");
  const [input, setInput] = useState("");

  const activeRows = scope === "same-birth-year" ? allRows : aggregatedRows;
  const sufficientRows = useMemo(
    () => activeRows.filter((row) => !isInsufficient(row, mode)),
    [activeRows, mode],
  );

  const availableGenders = useMemo(
    () => props.filters.genders.filter((item) => activeRows.some((row) => row.gender === item)),
    [activeRows, props.filters.genders],
  );
  const availableDistances = useMemo(
    () =>
      props.filters.distances.filter((item) =>
        activeRows.some((row) => row.gender === gender && row.distance === item),
      ),
    [activeRows, gender, props.filters.distances],
  );
  const availableBirthYears = useMemo(() => {
    if (scope !== "same-birth-year" || distance === null) return [];
    return props.filters.birthYears
      .filter((item) =>
        allRows.some((row) => row.gender === gender && row.distance === distance && row.birthYear === item),
      )
      .sort((a, b) => b - a);
  }, [allRows, distance, gender, props.filters.birthYears, scope]);

  useEffect(() => {
    if (availableGenders.length && !availableGenders.includes(gender)) {
      setGender(availableGenders[0]);
    }
  }, [availableGenders, gender]);
  useEffect(() => {
    if (availableDistances.length && (distance === null || !availableDistances.includes(distance))) {
      setDistance(availableDistances[0]);
    }
  }, [availableDistances, distance]);
  useEffect(() => {
    if (scope !== "same-birth-year") return;
    if (availableBirthYears.length && (birthYear === null || !availableBirthYears.includes(birthYear))) {
      setBirthYear(availableBirthYears[0]);
    }
  }, [availableBirthYears, birthYear, scope]);

  useEffect(() => {
    if (distance === null) return;
    if (scope === "same-birth-year") {
      if (allRows.some((row) => row.gender === gender && row.distance === distance && row.birthYear === birthYear)) {
        return;
      }
      const fallback =
        allRows.find((row) => row.gender === gender && row.distance === distance && !isInsufficient(row, mode)) ??
        allRows.find((row) => row.gender === gender && row.distance === distance);
      if (!fallback) return;
      setBirthYear(fallback.birthYear);
      return;
    }
    if (aggregatedRows.some((row) => row.gender === gender && row.distance === distance)) {
      return;
    }
    const fallback =
      aggregatedRows.find((row) => row.gender === gender && !isInsufficient(row, mode)) ?? aggregatedRows[0];
    if (!fallback) return;
    setGender(fallback.gender);
    setDistance(fallback.distance);
  }, [aggregatedRows, allRows, birthYear, distance, gender, mode, scope]);

  const selectedRow = useMemo(() => {
    if (!gender || distance === null) return undefined;
    if (scope === "same-birth-year") {
      if (birthYear === null) return undefined;
      return allRows.find(
        (row) => row.gender === gender && row.distance === distance && row.birthYear === birthYear,
      );
    }
    return aggregatedRows.find((row) => row.gender === gender && row.distance === distance);
  }, [aggregatedRows, allRows, birthYear, distance, gender, scope]);

  const edges = useMemo(() => buildEdges(selectedRow, mode), [mode, selectedRow]);
  const raw = input.trim();
  const parsed = useMemo(() => {
    if (!raw) return null;
    if (mode === "time") return parseTime(raw);
    if (!/^\d{1,3}$/.test(raw)) return Number.NaN;
    return Number.parseInt(raw, 10);
  }, [mode, raw]);
  const hasError = raw.length > 0 && (parsed === null || Number.isNaN(parsed));

  const selectedCount = selectedRow ? countOf(selectedRow, mode) : null;
  const groupCountText = selectedCount ? `${selectedCount}명` : `${props.kAnonymityMin}명 미만`;
  const scopeLabel =
    scope === "same-birth-year" ? `${birthYear ?? "-"}년생 기준` : "출생연도 통합 기준";
  const groupLabel = `${scopeLabel} · ${gender}자 · ${distance ?? "-"}m · 같은 조건 선수 ${groupCountText}`;

  const calc = useMemo(() => {
    const enough = Boolean(selectedRow && !isInsufficient(selectedRow, mode) && edges);
    if (!enough || !edges || !selectedRow) {
      return {
        showResult: false,
        showThin: true,
        verdict: "",
        verdictDetail: "",
        markerPos: null as number | null,
      };
    }
    const hasParsed = typeof parsed === "number" && Number.isFinite(parsed);
    if (!hasParsed) {
      const verdict =
        mode === "time"
          ? `또래 ${countOf(selectedRow, mode) ?? 0}명의 기록 분포예요`
          : `또래 ${countOf(selectedRow, mode) ?? 0}명의 등수 분포예요`;
      const verdictDetail =
        mode === "time"
          ? `빠른 쪽 10%는 ${formatSeconds(edges[0])} 안쪽, 중간은 ${formatSeconds(edges[2])} 정도예요.`
          : `앞선 쪽 10%는 ${formatRank(edges[0])}등 안쪽, 중간은 ${formatRank(edges[2])}등 정도예요.`;
      return { showResult: true, showThin: false, verdict, verdictDetail, markerPos: null };
    }
    const percentile = Math.round(percentOf(edges, parsed, mode));
    const markerPos = bandPos(edges, parsed);
    const verdict =
      percentile <= 10
        ? "상위 10% 안쪽이에요"
        : percentile >= 90
          ? "아직 뒤쪽 구간이에요"
          : `또래 중 상위 ${percentile}% 정도예요`;

    let verdictDetail = "";
    const mid = edges[2];
    if (mode === "time") {
      const gap = mid - parsed;
      verdictDetail = `${formatSeconds(parsed)} · 또래 중간 기록(${formatSeconds(mid)})보다 ${Math.abs(gap).toFixed(2)}초 ${gap >= 0 ? "빨라요" : "느려요"}`;
    } else {
      const gap = mid - parsed;
      const gapText = Number.isInteger(gap) ? `${Math.abs(gap)}` : `${Math.abs(gap).toFixed(1)}`;
      verdictDetail =
        gap === 0
          ? `${parsed}등 · 또래가 보통 받는 등수(${formatRank(mid)}등)와 비슷해요`
          : `${parsed}등 · 또래가 보통 받는 등수(${formatRank(mid)}등)보다 ${gapText}계단 ${gap > 0 ? "앞서요" : "뒤에 있어요"}`;
    }
    return { showResult: true, showThin: false, verdict, verdictDetail, markerPos };
  }, [edges, mode, parsed, selectedRow]);

  const readingGuide =
    mode === "time"
      ? "왼쪽으로 갈수록 빠른 기록이에요. 아래 숫자는 구간 경계 기록이에요."
      : "왼쪽으로 갈수록 앞선 등수예요. 아래 숫자는 구간 경계 등수예요.";
  const leftLabel = mode === "time" ? "빠른 기록" : "앞선 등수";
  const rightLabel = mode === "time" ? "느린 기록" : "뒤쪽 등수";
  const edgeLabels = edges?.map((value) => (mode === "time" ? formatSeconds(value) : `${formatRank(value)}등`)) ?? [];

  const thinActions = useMemo<ThinAction[]>(() => {
    if (!selectedRow) return [];
    const actions: ThinAction[] = [];
    if (scope === "same-birth-year") {
      actions.push({
        label: "출생연도 통합으로 보기",
        onClick: () => setScope("all-birth-years"),
      });
      const altDistance = allRows.find(
        (row) =>
          !isInsufficient(row, mode) &&
          row.gender === selectedRow.gender &&
          row.birthYear === selectedRow.birthYear &&
          row.distance !== selectedRow.distance,
      );
      if (altDistance) {
        actions.push({
          label: `${altDistance.distance}m로 바꿔서 보기`,
          onClick: () => setDistance(altDistance.distance),
        });
      }
      const altBirthYear = allRows.find(
        (row) =>
          !isInsufficient(row, mode) &&
          row.gender === selectedRow.gender &&
          row.distance === selectedRow.distance &&
          row.birthYear !== selectedRow.birthYear,
      );
      if (altBirthYear) {
        actions.push({
          label: `${altBirthYear.birthYear}년생 기준으로 보기`,
          onClick: () => setBirthYear(altBirthYear.birthYear),
        });
      }
      return actions.slice(0, 3);
    }
    const altDistance = sufficientRows.find(
      (row) => row.gender === selectedRow.gender && row.distance !== selectedRow.distance,
    );
    if (altDistance) {
      actions.push({
        label: `${altDistance.distance}m로 바꿔서 보기`,
        onClick: () => setDistance(altDistance.distance),
      });
    }
    return actions.slice(0, 2);
  }, [allRows, mode, scope, selectedRow, sufficientRows]);

  return (
    <div className="dist-tool">
      <div className="dist-top-link">
        <a href={props.homeUrl ?? "../"}>← 메인으로</a>
      </div>

      <header className="dist-hero">
        <h1>우리 아이 기록, 또래 중에 어디쯤일까요?</h1>
        <p>출생연도를 포함해서 볼지, 연도를 통합해서 볼지 먼저 고르고 위치를 확인해 보세요.</p>
      </header>

      <section className="dist-card dist-scope-card">
        <div className="dist-stage-title">
          <span className="dist-stage-badge">비교 방식</span>
          <b>어떤 기준으로 비교할까요</b>
        </div>
        <div className="dist-seg-wrap" role="tablist" aria-label="비교 방식">
          <button
            type="button"
            className={`dist-seg-button${scope === "same-birth-year" ? " is-active" : ""}`}
            onClick={() => setScope("same-birth-year")}
          >
            출생연도 포함
          </button>
          <button
            type="button"
            className={`dist-seg-button${scope === "all-birth-years" ? " is-active" : ""}`}
            onClick={() => setScope("all-birth-years")}
          >
            출생연도 통합
          </button>
        </div>
        {scope === "same-birth-year" ? (
          <div className="dist-scope-note">
            출생연도까지 맞춰서 비교해요. 지금 내 아이와 가장 가까운 또래 위치를 보기에 좋아요.
          </div>
        ) : (
          <div className="dist-scope-note">
            출생연도는 묶어서 비교해요. 표본이 커져서 값이 더 안정적이라 큰 흐름을 보기 좋아요.
          </div>
        )}
      </section>

      <section className="dist-card">
        <div>
          <div className="dist-stage-title">
            <span className="dist-stage-badge">1단계</span>
            <b>누구와 비교할까요</b>
          </div>
          <div className="dist-seg-wrap" role="tablist" aria-label="성별">
            {availableGenders.map((item) => (
              <button
                key={item}
                type="button"
                className={`dist-seg-button${item === gender ? " is-active" : ""}`}
                onClick={() => setGender(item)}
              >
                {item}자
              </button>
            ))}
          </div>
          <div className="dist-chip-row">
            {availableDistances.map((item) => (
              <button
                key={item}
                type="button"
                className={`dist-chip${item === distance ? " is-active" : ""}`}
                onClick={() => setDistance(item)}
              >
                {item}m
              </button>
            ))}
          </div>
          {scope === "same-birth-year" && (
            <label className="dist-year-select">
              <span>출생연도</span>
              <select
                value={birthYear ?? ""}
                onChange={(event) => setBirthYear(Number(event.target.value) || null)}
              >
                {availableBirthYears.map((year) => (
                  <option key={year} value={year}>
                    {year}년생
                  </option>
                ))}
              </select>
            </label>
          )}
          {scope === "all-birth-years" && (
            <p className="dist-year-merged-note">출생연도는 통합해서 계산해요. 그래서 연도 선택은 생략해요.</p>
          )}
        </div>

        <div className="dist-step-divider">
          <div className="dist-stage-title">
            <span className="dist-stage-badge">2단계</span>
            <b>기록을 넣어보세요</b>
          </div>
          <p className="dist-input-guide">
            {mode === "time"
              ? "예선 기록을 적어주세요. 2분 29초 15는 2:29.15, 45초 8은 45.8로 쓰면 돼요."
              : "결승에서 받은 등수를 숫자로 적어주세요."}
          </p>

          <div className="dist-seg-wrap" role="tablist" aria-label="입력 모드">
            <button
              type="button"
              className={`dist-seg-button${mode === "time" ? " is-active" : ""}`}
              onClick={() => {
                setMode("time");
                setInput("");
              }}
            >
              기록(시간)
            </button>
            <button
              type="button"
              className={`dist-seg-button${mode === "rank" ? " is-active" : ""}`}
              onClick={() => {
                setMode("rank");
                setInput("");
              }}
            >
              등수
            </button>
          </div>

          <div className="dist-input-row">
            <label className="dist-input-box">
              <input
                type="text"
                value={input}
                onChange={(event) => setInput(event.target.value)}
                placeholder={mode === "time" ? (distance === 500 ? "예: 52.4" : "예: 1:49.20") : "예: 12"}
                inputMode="decimal"
              />
              <span>{mode === "time" ? "분:초" : "등"}</span>
            </label>
            {raw && (
              <button type="button" className="dist-clear-button" onClick={() => setInput("")}>
                지우기
              </button>
            )}
          </div>

          {hasError && (
            <div className="dist-error-text">
              {mode === "time"
                ? "시간 형식을 확인해주세요. 2분 29초 15는 2:29.15, 45초 8은 45.8로 적어주세요."
                : "등수는 숫자만 적어주세요. 12등이면 12로 쓰면 돼요."}
            </div>
          )}
        </div>
      </section>

      {calc.showResult && selectedRow && edges && (
        <section className="dist-card">
          <div className="dist-group-label">{groupLabel}</div>
          <div className="dist-verdict">{calc.verdict}</div>
          <div className="dist-verdict-detail">{calc.verdictDetail}</div>

          <div className="dist-band-wrap">
            <div className="dist-band-labels">
              <span>{leftLabel}</span>
              <span>{rightLabel}</span>
            </div>
            <div className="dist-band-marker-wrap">
              {calc.markerPos !== null && (
                <div className="dist-marker" style={{ left: `${calc.markerPos}%` }}>
                  <div className="dist-marker-tag">내 기록</div>
                  <div className="dist-marker-line" />
                </div>
              )}
              <div className="dist-band">
                <div />
                <div />
                <div />
                <div />
              </div>
            </div>
            <div className="dist-edge-labels">
              {edgeLabels.map((label, idx) => (
                <span key={`${label}-${idx}`}>{label}</span>
              ))}
            </div>
            <div className="dist-reading-guide">{readingGuide}</div>
          </div>

          <div className="dist-caution-box">
            <div className="dist-caution-title">이 숫자로 아이의 앞날을 알 수는 없어요</div>
            <div className="dist-caution-body">
              지금 어디쯤인지를 보여주는 것뿐이에요. 같은 나이에 뒤에 있던 선수가 몇 년 뒤 앞서는 일은 흔해요. 진로를 정하는 근거로 쓰지 말아주세요.
            </div>
          </div>
        </section>
      )}

      {calc.showThin && (
        <section className="dist-card dist-thin-card">
          <div className="dist-thin-title">이 조건은 공개하지 않아요</div>
          <div className="dist-thin-body">
            이 조건은 참가 선수가 적어 개인 기록이 짐작될 수 있어서 공개하지 않아요. 기록이 없거나 실력이 낮다는 뜻은 아니에요.
          </div>
          {thinActions.length > 0 && (
            <div className="dist-thin-actions">
              {thinActions.map((action) => (
                <button key={action.label} type="button" onClick={action.onClick}>
                  {action.label}
                </button>
              ))}
            </div>
          )}
        </section>
      )}

      <section className="dist-card">
        <h2>이 숫자는 어디서 온 걸까요?</h2>
        <p className="dist-notes-intro">오해하기 쉬운 점을 먼저 적어둘게요.</p>
        <div className="dist-notes-list">
          {NOTES.map((note) => (
            <article key={note.q} className="dist-note-item">
              <div className="dist-note-q">{note.q}</div>
              <div className="dist-note-a">{note.a}</div>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}

const TIME_EDGE_PERCENTILES = [10, 30, 50, 70, 90];
const RANK_EDGE_PERCENTILES = [10, 25, 50, 75, 90];

function isInsufficient(row: PeerDistributionRow, mode: InputMode): boolean {
  return mode === "time" ? row.timeInsufficient : row.rankInsufficient;
}

function countOf(row: PeerDistributionRow, mode: InputMode): number | null {
  return mode === "time" ? row.timeCount : row.rankCount;
}

function edgePercentiles(mode: InputMode): number[] {
  return mode === "time" ? TIME_EDGE_PERCENTILES : RANK_EDGE_PERCENTILES;
}

function buildEdges(row: PeerDistributionRow | undefined, mode: InputMode): number[] | null {
  if (!row || isInsufficient(row, mode)) return null;
  if (mode === "time") {
    const values = [row.timeP10, row.timeP30, row.timeP50, row.timeP70, row.timeP90];
    if (values.some((value) => typeof value !== "number")) return null;
    return values as number[];
  }
  if (typeof row.rankP25 !== "number" || typeof row.rankP50 !== "number" || typeof row.rankP75 !== "number") return null;
  const leftGap = row.rankP50 - row.rankP25;
  const rightGap = row.rankP75 - row.rankP50;
  const p10 = Math.max(1, row.rankP25 - leftGap * 0.6);
  const p90 = row.rankP75 + rightGap * 0.6;
  return [p10, row.rankP25, row.rankP50, row.rankP75, p90];
}

function parseTime(raw: string): number | null {
  const text = String(raw).trim();
  if (!text) return null;
  let matched = text.match(/^(\d+):(\d{1,2}(?:\.\d+)?)$/);
  if (matched) return Number.parseInt(matched[1], 10) * 60 + Number.parseFloat(matched[2]);
  matched = text.match(/^(\d+)분\s*(\d{1,2}(?:\.\d+)?)초?$/);
  if (matched) return Number.parseInt(matched[1], 10) * 60 + Number.parseFloat(matched[2]);
  matched = text.match(/^(\d{1,3}(?:\.\d+)?)초?$/);
  if (matched) return Number.parseFloat(matched[1]);
  return Number.NaN;
}

function percentOf(edges: number[], value: number, mode: InputMode): number {
  const percentiles = edgePercentiles(mode);
  if (value <= edges[0]) return 8;
  if (value >= edges[4]) return 94;
  for (let idx = 0; idx < 4; idx += 1) {
    if (value >= edges[idx] && value <= edges[idx + 1]) {
      const ratio = (value - edges[idx]) / (edges[idx + 1] - edges[idx]);
      return percentiles[idx] + ratio * (percentiles[idx + 1] - percentiles[idx]);
    }
  }
  return 50;
}

function bandPos(edges: number[], value: number): number {
  if (value <= edges[0]) return 0;
  if (value >= edges[4]) return 100;
  for (let idx = 0; idx < 4; idx += 1) {
    if (value >= edges[idx] && value <= edges[idx + 1]) {
      const ratio = (value - edges[idx]) / (edges[idx + 1] - edges[idx]);
      return (idx + ratio) * 25;
    }
  }
  return 50;
}

function formatSeconds(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(2)}초`;
  const minute = Math.floor(seconds / 60);
  const remain = seconds - minute * 60;
  return `${minute}분 ${remain < 10 ? "0" : ""}${remain.toFixed(2)}초`;
}

function formatRank(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

function aggregateRows(rows: PeerDistributionRow[]): PeerDistributionRow[] {
  const grouped = new Map<string, PeerDistributionRow[]>();
  for (const row of rows) {
    const key = `${row.gender}__${row.distance}`;
    const bucket = grouped.get(key);
    if (bucket) bucket.push(row);
    else grouped.set(key, [row]);
  }
  const result: PeerDistributionRow[] = [];
  for (const bucket of grouped.values()) {
    const seed = bucket[0];
    const timeValid = bucket.filter((row) => !row.timeInsufficient && typeof row.timeCount === "number");
    const rankValid = bucket.filter((row) => !row.rankInsufficient && typeof row.rankCount === "number");
    const timeTotal = timeValid.reduce((sum, row) => sum + (row.timeCount ?? 0), 0);
    const rankTotal = rankValid.reduce((sum, row) => sum + (row.rankCount ?? 0), 0);
    result.push({
      birthYear: -1,
      gender: seed.gender,
      distance: seed.distance,
      timeCount: timeTotal > 0 ? timeTotal : null,
      timeInsufficient: timeTotal <= 0,
      rankCount: rankTotal > 0 ? rankTotal : null,
      rankInsufficient: rankTotal <= 0,
      timeP05: weightedMetric(timeValid, "timeP05", "timeCount"),
      timeP10: weightedMetric(timeValid, "timeP10", "timeCount"),
      timeP20: weightedMetric(timeValid, "timeP20", "timeCount"),
      timeP30: weightedMetric(timeValid, "timeP30", "timeCount"),
      timeP40: weightedMetric(timeValid, "timeP40", "timeCount"),
      timeP50: weightedMetric(timeValid, "timeP50", "timeCount"),
      timeP60: weightedMetric(timeValid, "timeP60", "timeCount"),
      timeP70: weightedMetric(timeValid, "timeP70", "timeCount"),
      timeP80: weightedMetric(timeValid, "timeP80", "timeCount"),
      timeP90: weightedMetric(timeValid, "timeP90", "timeCount"),
      timeP95: weightedMetric(timeValid, "timeP95", "timeCount"),
      rankP25: weightedMetric(rankValid, "rankP25", "rankCount"),
      rankP50: weightedMetric(rankValid, "rankP50", "rankCount"),
      rankP75: weightedMetric(rankValid, "rankP75", "rankCount"),
    });
  }
  return result.sort((a, b) => {
    if (a.gender !== b.gender) return a.gender.localeCompare(b.gender, "ko");
    return a.distance - b.distance;
  });
}

function weightedMetric(
  rows: PeerDistributionRow[],
  key: keyof PeerDistributionRow,
  countKey: "timeCount" | "rankCount",
): number | null {
  let weightedSum = 0;
  let weight = 0;
  for (const row of rows) {
    const value = row[key];
    const count = row[countKey];
    if (typeof value !== "number" || typeof count !== "number" || count <= 0) continue;
    weightedSum += value * count;
    weight += count;
  }
  if (weight <= 0) return null;
  return weightedSum / weight;
}
