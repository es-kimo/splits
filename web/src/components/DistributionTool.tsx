import { useEffect, useMemo, useState } from "react";

import type { DistributionDoc, PeerDistributionRow } from "../lib/types";

type InputMode = "time" | "rank";
type AgeInputMode = "grade" | "birth-year";

interface Props extends DistributionDoc {
  homeUrl?: string;
  showTopLink?: boolean;
  showHero?: boolean;
}

interface ThinAction {
  label: string;
  onClick: () => void;
}

interface GradeOption {
  id: string;
  label: string;
  approxAge: number;
}

interface RowResolution {
  row: PeerDistributionRow;
  requestedYear: number;
  resolvedYear: number;
  delta: number;
  usedFallback: boolean;
}

const CURRENT_YEAR = new Date().getFullYear();

const GRADE_OPTIONS: GradeOption[] = [
  { id: "elem-1", label: "초1", approxAge: 8 },
  { id: "elem-2", label: "초2", approxAge: 9 },
  { id: "elem-3", label: "초3", approxAge: 10 },
  { id: "elem-4", label: "초4", approxAge: 11 },
  { id: "elem-5", label: "초5", approxAge: 12 },
  { id: "elem-6", label: "초6", approxAge: 13 },
  { id: "mid-1", label: "중1", approxAge: 14 },
  { id: "mid-2", label: "중2", approxAge: 15 },
  { id: "mid-3", label: "중3", approxAge: 16 },
  { id: "high-1", label: "고1", approxAge: 17 },
  { id: "high-2", label: "고2", approxAge: 18 },
  { id: "high-3", label: "고3", approxAge: 19 },
];

const NOTES = [
  {
    q: "학년은 어떻게 계산하나요?",
    a: "지금 학년을 올해 기준의 출생연도로 바꿔서 비교해요. 학년이 또래와 다르면 아래에서 출생연도를 직접 넣어주세요.",
  },
  {
    q: "어떤 경기의 기록인가요?",
    a: "예선 기록이에요. 결승은 순위 싸움 때문에 일부러 천천히 타는 경우가 많아서, 실력을 견주기에는 예선이 더 안정적이에요.",
  },
  {
    q: "쇼트트랙 기록만 있나요?",
    a: "네. 같은 날 함께 열리는 스피드스케이팅 경기 기록은 빼고 모았어요.",
  },
  {
    q: "기록과 등수의 비교 인원이 왜 다른가요?",
    a: "기록은 예선에 나온 모든 선수를 쓰고, 등수는 학령별 결승과 채점종합만 써요. 대상이 되는 경기가 달라서 인원도 달라집니다.",
  },
  {
    q: "이 숫자로 알 수 없는 건 무엇인가요?",
    a: "훈련량, 부상, 성장 시기, 지도 환경처럼 실제 경기력을 크게 좌우하는 것들은 여기에 담겨 있지 않아요.",
  },
];

export default function DistributionTool(props: Props) {
  const allRows = props.rows;
  const showHero = props.showHero ?? true;
  const initialRow = allRows.find((row) => !row.timeInsufficient || !row.rankInsufficient) ?? allRows[0];

  const defaultGradeId = useMemo(() => pickClosestGradeId(initialRow?.birthYear ?? null), [initialRow?.birthYear]);

  const [gender, setGender] = useState(initialRow?.gender ?? "");
  const [distance, setDistance] = useState<number | null>(initialRow?.distance ?? null);
  const [mode, setMode] = useState<InputMode>("time");
  const [ageInputMode, setAgeInputMode] = useState<AgeInputMode>("grade");
  const [gradeId, setGradeId] = useState(defaultGradeId);
  const [manualBirthYearInput, setManualBirthYearInput] = useState(initialRow?.birthYear ? String(initialRow.birthYear) : "");
  const [input, setInput] = useState("");

  const availableGenders = useMemo(
    () => props.filters.genders.filter((item) => allRows.some((row) => row.gender === item)),
    [allRows, props.filters.genders],
  );

  const selectedGrade = useMemo(() => GRADE_OPTIONS.find((option) => option.id === gradeId) ?? GRADE_OPTIONS[0], [gradeId]);

  const manualBirthYear = useMemo(() => parseBirthYear(manualBirthYearInput), [manualBirthYearInput]);

  const hasBirthYearError =
    ageInputMode === "birth-year" && manualBirthYearInput.trim().length > 0 && !Number.isFinite(manualBirthYear);

  const targetBirthYear = useMemo(() => {
    if (ageInputMode === "grade") return CURRENT_YEAR - selectedGrade.approxAge;
    if (Number.isFinite(manualBirthYear)) return manualBirthYear;
    return null;
  }, [ageInputMode, manualBirthYear, selectedGrade.approxAge]);

  const exactDistanceOptions = useMemo(
    () => distanceOptionsForYear(allRows, gender, targetBirthYear, 0),
    [allRows, gender, targetBirthYear],
  );
  const nearbyDistanceOptions = useMemo(
    () => distanceOptionsForYear(allRows, gender, targetBirthYear, 2),
    [allRows, gender, targetBirthYear],
  );
  const availableDistances = exactDistanceOptions.length > 0 ? exactDistanceOptions : nearbyDistanceOptions;

  useEffect(() => {
    if (availableGenders.length > 0 && !availableGenders.includes(gender)) {
      setGender(availableGenders[0]);
    }
  }, [availableGenders, gender]);

  useEffect(() => {
    if (availableDistances.length > 0 && (distance === null || !availableDistances.includes(distance))) {
      setDistance(availableDistances[0]);
      return;
    }
    if (availableDistances.length === 0) {
      setDistance(null);
    }
  }, [availableDistances, distance]);

  const selectedResolution = useMemo(() => {
    if (!gender || distance === null || targetBirthYear === null) return null;
    return resolveDistributionRow({ rows: allRows, gender, distance, targetBirthYear, mode });
  }, [allRows, distance, gender, mode, targetBirthYear]);

  const selectedRow = selectedResolution?.row;
  const selectedCount = selectedRow ? countOf(selectedRow, mode) : null;
  const groupCountText = selectedCount ? `${selectedCount}명` : `${props.kAnonymityMin}명 미만`;

  const groupYear = selectedResolution?.resolvedYear ?? targetBirthYear;
  const groupLabel = `${groupYear ?? "-"}년생 ${gender}자 ${distance ?? "-"}m · 함께 비교한 선수 ${groupCountText}`;

  const fallbackNotice = useMemo(() => {
    if (!selectedResolution || !selectedResolution.usedFallback || targetBirthYear === null) return null;
    const countText = selectedCount ? `${selectedCount}명` : `${props.kAnonymityMin}명 미만`;
    const startYear = targetBirthYear - selectedResolution.delta;
    const endYear = targetBirthYear + selectedResolution.delta;
    return `${targetBirthYear}년생만으로는 비교할 선수가 부족해서, ${startYear}~${endYear}년생을 함께 묶어 보여드려요 (${countText}).`;
  }, [props.kAnonymityMin, selectedCount, selectedResolution, targetBirthYear]);

  const distanceGuide = useMemo(() => {
    if (targetBirthYear === null) return null;
    if (exactDistanceOptions.length > 0) return null;
    if (nearbyDistanceOptions.length > 0) {
      return `${targetBirthYear}년생만으로는 보여드릴 수 있는 종목이 적어서, 앞뒤 2년까지 넓혀 고를 수 있게 했어요.`;
    }
    return `${targetBirthYear}년생은 앞뒤 2년까지 넓혀도 보여드릴 수 있는 종목이 없어요.`;
  }, [exactDistanceOptions.length, nearbyDistanceOptions.length, targetBirthYear]);

  const edges = useMemo(() => buildEdges(selectedRow, mode), [mode, selectedRow]);

  const raw = input.trim();
  const parsed = useMemo(() => {
    if (!raw) return null;
    if (mode === "time") return parseTime(raw);
    if (!/^\d{1,3}$/.test(raw)) return Number.NaN;
    return Number.parseInt(raw, 10);
  }, [mode, raw]);
  const hasInputError = raw.length > 0 && (parsed === null || Number.isNaN(parsed));

  const calc = useMemo(() => {
    if (!selectedRow || !edges || isInsufficient(selectedRow, mode)) return null;

    const countValue = countOf(selectedRow, mode);
    const countText = countValue ? `${countValue}명` : `${props.kAnonymityMin}명 미만`;
    const hasParsed = typeof parsed === "number" && Number.isFinite(parsed);

    if (!hasParsed) {
      return {
        showResult: true,
        conclusion: `또래 ${countText}은 이 정도였어요`,
        detail:
          mode === "time"
            ? `빠른 쪽 10명 중 1명은 ${formatSeconds(edges[0])} 안쪽이고, 한가운데는 ${formatSeconds(edges[2])} 전후예요.`
            : `앞선 쪽 10명 중 1명은 ${formatRank(edges[0])}등 안쪽이고, 한가운데는 ${formatRank(edges[2])}등 전후예요.`,
        markerPos: null as number | null,
        rangeNote: null as string | null,
      };
    }

    const percentile = Math.max(1, Math.min(99, Math.round(percentOf(edges, parsed, mode))));
    const markerPos = bandPos(edges, parsed);

    const mid = edges[2];
    let detail = "";
    if (mode === "time") {
      const gap = mid - parsed;
      detail = `${formatSeconds(parsed)} · 또래 한가운데(${formatSeconds(mid)})보다 ${Math.abs(gap).toFixed(2)}초 ${gap >= 0 ? "빨라요" : "느려요"}.`;
    } else {
      const gap = mid - parsed;
      const gapText = Number.isInteger(gap) ? `${Math.abs(gap)}` : `${Math.abs(gap).toFixed(1)}`;
      detail =
        gap === 0
          ? `${parsed}등 · 또래 한가운데(${formatRank(mid)}등)와 비슷해요.`
          : `${parsed}등 · 또래 한가운데(${formatRank(mid)}등)보다 ${gapText}계단 ${gap > 0 ? "앞서 있어요" : "뒤에 있어요"}.`;
    }

    let rangeNote: string | null = null;
    if (parsed < edges[0]) {
      rangeNote =
        mode === "time"
          ? `입력한 기록이 이 구간의 빠른 기준(${formatSeconds(edges[0])})보다 더 빨라요. 같은 학년·다른 종목도 함께 보면 현재 위치를 더 안정적으로 읽을 수 있어요.`
          : `입력한 등수가 이 구간의 앞선 기준(${formatRank(edges[0])}등)보다 더 앞서 있어요. 같은 학년·다른 종목도 함께 보면 현재 위치를 더 안정적으로 읽을 수 있어요.`;
    } else if (parsed > edges[4]) {
      rangeNote =
        mode === "time"
          ? `입력한 기록이 이 구간의 느린 기준(${formatSeconds(edges[4])})보다 더 느려요. 종목을 바꾸거나 앞뒤 학년도 함께 보면서 비교 범위를 넓혀보세요.`
          : `입력한 등수가 이 구간의 뒤쪽 기준(${formatRank(edges[4])}등)보다 더 뒤에 있어요. 종목을 바꾸거나 앞뒤 학년도 함께 보면서 비교 범위를 넓혀보세요.`;
    }

    return {
      showResult: true,
      conclusion: `또래 ${countText} 중 상위 ${percentile}%예요`,
      detail,
      markerPos,
      rangeNote,
    };
  }, [edges, mode, parsed, props.kAnonymityMin, selectedRow]);

  const readingGuide =
    mode === "time"
      ? "왼쪽으로 갈수록 빠른 기록이에요. 아래 숫자는 각 구간이 갈리는 지점의 기록이에요."
      : "왼쪽으로 갈수록 앞선 등수예요. 아래 숫자는 각 구간이 갈리는 지점의 등수예요.";
  const leftLabel = mode === "time" ? "빠른 기록" : "앞선 등수";
  const rightLabel = mode === "time" ? "느린 기록" : "뒤쪽 등수";
  const edgeLabels = edges?.map((value) => (mode === "time" ? formatSeconds(value) : `${formatRank(value)}등`)) ?? [];
  const quantileRows =
    edges?.map((value, idx) => ({
      label: `상위 ${edgePercentiles(mode)[idx]}% 지점`,
      value: mode === "time" ? formatSeconds(value) : `${formatRank(value)}등`,
    })) ?? [];

  const selectionReady = !hasBirthYearError && targetBirthYear !== null && distance !== null && gender.length > 0;
  const noRowForSelection = selectionReady && !selectedRow;
  const rowInsufficient = selectionReady && selectedRow ? isInsufficient(selectedRow, mode) || !edges : false;

  const thinActions = useMemo<ThinAction[]>(() => {
    const actions: ThinAction[] = [];

    if (targetBirthYear !== null && gender && distance !== null) {
      const altDistance = availableDistances.find(
        (item) => item !== distance && hasUsableRow({ rows: allRows, gender, distance: item, targetBirthYear, mode }),
      );
      if (typeof altDistance === "number") {
        actions.push({ label: `${altDistance}m로 바꿔서 보기`, onClick: () => setDistance(altDistance) });
      }
    }

    actions.push(
      mode === "time"
        ? { label: "등수로 바꿔서 보기", onClick: () => { setMode("rank"); setInput(""); } }
        : { label: "기록으로 바꿔서 보기", onClick: () => { setMode("time"); setInput(""); } },
    );

    return actions.slice(0, 2);
  }, [allRows, availableDistances, distance, gender, mode, targetBirthYear]);

  return (
    <div className="dist-tool">
      {showHero && (
        <header className="dist-hero">
          <h1>우리 아이 기록,
            <br />
            또래 중에 어디쯤일까요?
          </h1>
          <p>비교할 조건을 고르고 기록이나 등수를 넣으면, 또래 중 어디쯤인지 한 줄로 알려드려요.</p>
        </header>
      )}

      <section className="dist-card">
        <div>
          <div className="dist-stage-title">
            <span className="dist-stage-badge">1단계</span>
            <b>누구와 견줄지 골라주세요</b>
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

          <div className="dist-field-head">
            <div className="dist-group-label">학년</div>
            <button
              type="button"
              className="dist-text-button"
              onClick={() => setAgeInputMode(ageInputMode === "grade" ? "birth-year" : "grade")}
            >
              {ageInputMode === "grade" ? "출생연도로 넣기" : "학년으로 넣기"}
            </button>
          </div>

          {ageInputMode === "grade" ? (
            <>
              <div className="dist-chip-row">
                {GRADE_OPTIONS.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    className={`dist-chip${item.id === gradeId ? " is-active" : ""}`}
                    onClick={() => setGradeId(item.id)}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
              <p className="dist-age-mode-note">{targetBirthYear ?? "-"}년생과 비슷한 또래로 보고 견줘요.</p>
            </>
          ) : (
            <label className="dist-year-select">
              <input
                type="text"
                inputMode="numeric"
                maxLength={4}
                value={manualBirthYearInput}
                onChange={(event) => setManualBirthYearInput(event.target.value.replace(/[^\d]/g, ""))}
                placeholder="예: 2013"
                aria-label="출생연도"
              />
              {hasBirthYearError ? (
                <div className="dist-error-text">태어난 해를 네 자리로 적어주세요. 2013년생이면 2013처럼요.</div>
              ) : (
                <p className="dist-age-mode-note">태어난 해를 네 자리로 적어주세요.</p>
              )}
            </label>
          )}

          <div className="dist-group-label dist-group-label-spaced">종목</div>
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
          {distanceGuide && <p className="dist-distance-fallback-note">{distanceGuide}</p>}
        </div>

        <div className="dist-step-divider">
          <div className="dist-stage-title">
            <span className="dist-stage-badge">2단계</span>
            <b>아이 기록을 넣어주세요</b>
          </div>

          <div className="dist-seg-wrap" role="tablist" aria-label="무엇으로 견줄까요">
            <button
              type="button"
              className={`dist-seg-button${mode === "time" ? " is-active" : ""}`}
              onClick={() => {
                setMode("time");
                setInput("");
              }}
            >
              기록으로
            </button>
            <button
              type="button"
              className={`dist-seg-button${mode === "rank" ? " is-active" : ""}`}
              onClick={() => {
                setMode("rank");
                setInput("");
              }}
            >
              등수로
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
                aria-label={mode === "time" ? "예선 기록" : "결승 등수"}
              />
              <span>{mode === "time" ? "분:초" : "등"}</span>
            </label>
            {raw && (
              <button type="button" className="dist-clear-button" onClick={() => setInput("")}>
                지우기
              </button>
            )}
          </div>

          {hasInputError ? (
            <div className="dist-error-text">
              {mode === "time"
                ? "2분 29초 15는 2:29.15, 45초 8은 45.8처럼 적어주세요."
                : "숫자만 적어주세요. 12등이면 12처럼요."}
            </div>
          ) : (
            <p className="dist-input-guide">
              {mode === "time"
                ? "예선 기록을 적어주세요. 2분 29초 15는 2:29.15, 45초 8은 45.8이에요."
                : "결승에서 받은 등수를 숫자로 적어주세요."}
            </p>
          )}
        </div>
      </section>

      {calc?.showResult && selectedRow && edges && (
        <section className="dist-card">
          <div className="dist-group-label">{groupLabel}</div>
          {fallbackNotice && <div className="dist-fallback-note">{fallbackNotice}</div>}
          <div className="dist-verdict">{calc.conclusion}</div>
          <div className="dist-verdict-detail">{calc.detail}</div>
          {calc.rangeNote && <div className="dist-range-note">{calc.rangeNote}</div>}

          <details className="dist-evidence">
            <summary className="dist-evidence-summary">어떻게 나온 숫자인가요?</summary>
            <div className="dist-evidence-inner">
              <div className="dist-band-wrap">
                <div className="dist-band-labels">
                  <span>{leftLabel}</span>
                  <span>{rightLabel}</span>
                </div>
                <div className="dist-band-marker-wrap">
                  {calc.markerPos !== null && (
                    <div className="dist-marker" style={{ left: `${calc.markerPos}%` }}>
                      <div className="dist-marker-tag">우리 아이</div>
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

              <table className="dist-quantile-table">
                <tbody>
                  {quantileRows.map((item) => (
                    <tr key={item.label}>
                      <th>{item.label}</th>
                      <td>{item.value}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </section>
      )}

      {(noRowForSelection || rowInsufficient) && (
        <section className="dist-card dist-thin-card">
          {fallbackNotice && <div className="dist-fallback-note">{fallbackNotice}</div>}
          <div className="dist-thin-title">
            {noRowForSelection ? "견줄 또래를 찾지 못했어요" : "이 조건은 보여드릴 수 없어요"}
          </div>
          <div className="dist-thin-body">
            {noRowForSelection
              ? "앞뒤 2년까지 넓혀봐도 견줄 만한 기록이 모이지 않았어요. 종목을 바꾸거나 출생연도를 직접 넣어보세요."
              : "이 조건은 나온 선수가 적어서, 보여드리면 특정 아이의 기록이 짐작될 수 있어요. 기록이 없거나 실력이 낮다는 뜻은 아니에요."}
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
        <div className="dist-caution-title">이 숫자로 아이의 앞날을 알 수는 없어요</div>
        <div className="dist-caution-body">
          지금 어디쯤인지를 보여주는 참고 정보예요. 같은 나이에 뒤에 있던 선수가 몇 년 뒤 앞서는 일은 흔합니다. 진로를 정하는
          근거로는 쓰지 말아주세요.
        </div>
      </section>

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

function pickClosestGradeId(birthYear: number | null): string {
  if (birthYear === null) return GRADE_OPTIONS[0].id;
  const approxAge = CURRENT_YEAR - birthYear;
  let best = GRADE_OPTIONS[0];
  for (const option of GRADE_OPTIONS) {
    if (Math.abs(option.approxAge - approxAge) < Math.abs(best.approxAge - approxAge)) {
      best = option;
    }
  }
  return best.id;
}

function parseBirthYear(raw: string): number | null {
  const text = String(raw).trim();
  if (!text) return null;
  if (!/^\d{4}$/.test(text)) return Number.NaN;
  const value = Number.parseInt(text, 10);
  if (value < 1900 || value > CURRENT_YEAR) return Number.NaN;
  return value;
}

function distanceOptionsForYear(
  rows: PeerDistributionRow[],
  gender: string,
  targetBirthYear: number | null,
  maxDelta: number,
): number[] {
  if (!gender || targetBirthYear === null) return [];
  const set = new Set<number>();
  for (const row of rows) {
    if (row.gender !== gender) continue;
    if (Math.abs(row.birthYear - targetBirthYear) > maxDelta) continue;
    set.add(row.distance);
  }
  return Array.from(set).sort((a, b) => a - b);
}

function resolveDistributionRow(params: {
  rows: PeerDistributionRow[];
  gender: string;
  distance: number;
  targetBirthYear: number;
  mode: InputMode;
}): RowResolution | null {
  const { rows, gender, distance, targetBirthYear, mode } = params;

  for (const delta of [0, 1, 2]) {
    const candidates = rows.filter((row) => {
      if (row.gender !== gender || row.distance !== distance) return false;
      if (delta === 0) return row.birthYear === targetBirthYear;
      return Math.abs(row.birthYear - targetBirthYear) === delta;
    });
    if (candidates.length === 0) continue;

    const sufficient = candidates.filter((row) => !isInsufficient(row, mode));
    const pool = sufficient.length > 0 ? sufficient : candidates;
    const chosen = pool.slice().sort((a, b) => {
      const countDiff = (countOf(b, mode) ?? -1) - (countOf(a, mode) ?? -1);
      if (countDiff !== 0) return countDiff;
      const distanceA = Math.abs(a.birthYear - targetBirthYear);
      const distanceB = Math.abs(b.birthYear - targetBirthYear);
      if (distanceA !== distanceB) return distanceA - distanceB;
      return a.birthYear - b.birthYear;
    })[0];

    return {
      row: chosen,
      requestedYear: targetBirthYear,
      resolvedYear: chosen.birthYear,
      delta,
      usedFallback: chosen.birthYear !== targetBirthYear,
    };
  }

  return null;
}

function hasUsableRow(params: {
  rows: PeerDistributionRow[];
  gender: string;
  distance: number;
  targetBirthYear: number;
  mode: InputMode;
}): boolean {
  const resolved = resolveDistributionRow(params);
  return Boolean(resolved && !isInsufficient(resolved.row, params.mode));
}

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
