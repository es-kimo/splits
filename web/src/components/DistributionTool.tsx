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
    q: "학년 입력은 어떻게 계산하나요?",
    a: "학년은 현재연도 기준의 근사 출생연도로 바꿔 계산합니다. 필요하면 출생연도를 직접 입력해서 비교할 수 있습니다.",
  },
  {
    q: "어떤 경기의 기록인가요?",
    a: "기록은 예선 기준입니다. 결승은 경기 운영 영향이 커서 실력 비교에는 예선 기록이 더 안정적입니다.",
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
    q: "이 데이터로 알 수 없는 것은 무엇인가요?",
    a: "훈련량, 부상, 성장 시기, 지도 환경처럼 실제 경기력에 큰 영향을 주는 요소는 포함하지 않습니다.",
  },
];

export default function DistributionTool(props: Props) {
  const allRows = props.rows;
  const showTopLink = props.showTopLink ?? true;
  const showHero = props.showHero ?? true;
  const initialRow = allRows.find((row) => !row.timeInsufficient || !row.rankInsufficient) ?? allRows[0];

  const defaultGradeId = useMemo(
    () => pickClosestGradeId(initialRow?.birthYear ?? null),
    [initialRow?.birthYear],
  );

  const [gender, setGender] = useState(initialRow?.gender ?? "");
  const [distance, setDistance] = useState<number | null>(initialRow?.distance ?? null);
  const [mode, setMode] = useState<InputMode>("time");
  const [ageInputMode, setAgeInputMode] = useState<AgeInputMode>("grade");
  const [gradeId, setGradeId] = useState(defaultGradeId);
  const [manualBirthYearInput, setManualBirthYearInput] = useState(
    initialRow?.birthYear ? String(initialRow.birthYear) : "",
  );
  const [input, setInput] = useState("");

  const availableGenders = useMemo(
    () => props.filters.genders.filter((item) => allRows.some((row) => row.gender === item)),
    [allRows, props.filters.genders],
  );

  const selectedGrade = useMemo(
    () => GRADE_OPTIONS.find((option) => option.id === gradeId) ?? GRADE_OPTIONS[0],
    [gradeId],
  );

  const manualBirthYear = useMemo(() => parseBirthYear(manualBirthYearInput), [manualBirthYearInput]);

  const hasBirthYearError =
    ageInputMode === "birth-year" &&
    manualBirthYearInput.trim().length > 0 &&
    !Number.isFinite(manualBirthYear);

  const targetBirthYear = useMemo(() => {
    if (ageInputMode === "grade") {
      return CURRENT_YEAR - selectedGrade.approxAge;
    }
    if (Number.isFinite(manualBirthYear)) {
      return manualBirthYear;
    }
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
    return resolveDistributionRow({
      rows: allRows,
      gender,
      distance,
      targetBirthYear,
      mode,
    });
  }, [allRows, distance, gender, mode, targetBirthYear]);

  const selectedRow = selectedResolution?.row;
  const selectedCount = selectedRow ? countOf(selectedRow, mode) : null;
  const groupCountText = selectedCount ? `${selectedCount}명` : `${props.kAnonymityMin}명 미만`;

  const groupYear = selectedResolution?.resolvedYear ?? targetBirthYear;
  const groupLabel = `${groupYear ?? "-"}년생 기준 · ${gender}자 · ${distance ?? "-"}m · 같은 조건 선수 ${groupCountText}`;

  const fallbackNotice = useMemo(() => {
    if (!selectedResolution || !selectedResolution.usedFallback || targetBirthYear === null) return null;
    const countText = selectedCount ? `${selectedCount}명` : `${props.kAnonymityMin}명 미만`;
    const startYear = targetBirthYear - selectedResolution.delta;
    const endYear = targetBirthYear + selectedResolution.delta;
    return `${targetBirthYear}년생 데이터가 부족해 ${startYear}~${endYear}년생 기준으로 표시합니다 (${countText}).`;
  }, [props.kAnonymityMin, selectedCount, selectedResolution, targetBirthYear]);

  const distanceGuide = useMemo(() => {
    if (targetBirthYear === null) return null;
    if (exactDistanceOptions.length > 0) return null;
    if (nearbyDistanceOptions.length > 0) {
      return `${targetBirthYear}년생 기준으로 공개 가능한 거리가 적어 ±2년 범위에서 선택 가능한 거리를 보여드려요.`;
    }
    return `${targetBirthYear}년생은 ±2년 범위에도 공개 가능한 거리가 없습니다.`;
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
        conclusion: `같은 조건 ${countText}의 분포예요`,
        detail:
          mode === "time"
            ? `빠른 쪽 10%는 ${formatSeconds(edges[0])} 안쪽, 가운데 구간은 ${formatSeconds(edges[2])} 전후입니다.`
            : `앞선 쪽 10%는 ${formatRank(edges[0])}등 안쪽, 가운데 구간은 ${formatRank(edges[2])}등 전후입니다.`,
        markerPos: null as number | null,
      };
    }

    const percentile = Math.max(1, Math.min(99, Math.round(percentOf(edges, parsed, mode))));
    const markerPos = bandPos(edges, parsed);

    let detail = "";
    const mid = edges[2];
    if (mode === "time") {
      const gap = mid - parsed;
      detail = `${formatSeconds(parsed)} · 같은 조건 중앙값(${formatSeconds(mid)})보다 ${Math.abs(gap).toFixed(2)}초 ${gap >= 0 ? "빠릅니다" : "느립니다"}.`;
    } else {
      const gap = mid - parsed;
      const gapText = Number.isInteger(gap) ? `${Math.abs(gap)}` : `${Math.abs(gap).toFixed(1)}`;
      detail =
        gap === 0
          ? `${parsed}등 · 같은 조건 중앙값(${formatRank(mid)}등)과 비슷합니다.`
          : `${parsed}등 · 같은 조건 중앙값(${formatRank(mid)}등)보다 ${gapText}계단 ${gap > 0 ? "앞섭니다" : "뒤에 있습니다"}.`;
    }

    return {
      showResult: true,
      conclusion: `같은 조건 ${countText} 중 상위 ${percentile}%예요`,
      detail,
      markerPos,
    };
  }, [edges, mode, parsed, props.kAnonymityMin, selectedRow]);

  const readingGuide =
    mode === "time"
      ? "왼쪽으로 갈수록 빠른 기록입니다. 숫자는 같은 조건에서의 구간 경계 기록입니다."
      : "왼쪽으로 갈수록 앞선 등수입니다. 숫자는 같은 조건에서의 구간 경계 등수입니다.";
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
        (item) =>
          item !== distance &&
          hasUsableRow({
            rows: allRows,
            gender,
            distance: item,
            targetBirthYear,
            mode,
          }),
      );
      if (typeof altDistance === "number") {
        actions.push({
          label: `${altDistance}m로 바꿔서 보기`,
          onClick: () => setDistance(altDistance),
        });
      }
    }

    if (ageInputMode === "grade") {
      actions.push({
        label: "출생연도로 직접 입력하기",
        onClick: () => setAgeInputMode("birth-year"),
      });
    } else {
      actions.push({
        label: "학년 입력으로 돌아가기",
        onClick: () => setAgeInputMode("grade"),
      });
    }

    return actions.slice(0, 2);
  }, [ageInputMode, allRows, availableDistances, distance, gender, mode, targetBirthYear]);

  return (
    <div className="dist-tool">
      {showTopLink && (
        <div className="dist-top-link">
          <a href={props.homeUrl ?? "../"}>← 메인으로</a>
        </div>
      )}

      {showHero && (
        <header className="dist-hero">
          <h1>우리 아이 기록, 또래 중에 어디쯤일까요?</h1>
          <p>비교 조건을 먼저 고르고, 기록이나 등수를 넣으면 한 줄 결론으로 위치를 바로 확인할 수 있어요.</p>
        </header>
      )}

      <section className="dist-card">
        <div>
          <div className="dist-stage-title">
            <span className="dist-stage-badge">1단계</span>
            <b>비교 조건을 고르세요</b>
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

          <div className="dist-group-label">나이 입력 방식</div>
          <div className="dist-seg-wrap" role="tablist" aria-label="나이 입력 방식">
            <button
              type="button"
              className={`dist-seg-button${ageInputMode === "grade" ? " is-active" : ""}`}
              onClick={() => setAgeInputMode("grade")}
            >
              학년으로 입력
            </button>
            <button
              type="button"
              className={`dist-seg-button${ageInputMode === "birth-year" ? " is-active" : ""}`}
              onClick={() => setAgeInputMode("birth-year")}
            >
              출생연도로 입력
            </button>
          </div>

          {ageInputMode === "grade" ? (
            <label className="dist-year-select">
              <span>학년</span>
              <select value={gradeId} onChange={(event) => setGradeId(event.target.value)}>
                {GRADE_OPTIONS.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.label}
                  </option>
                ))}
              </select>
              <p className="dist-age-mode-note">
                현재연도 기준으로 {targetBirthYear ?? "-"}년생에 가깝다고 보고 계산합니다.
              </p>
            </label>
          ) : (
            <label className="dist-year-select">
              <span>출생연도</span>
              <input
                type="number"
                inputMode="numeric"
                value={manualBirthYearInput}
                onChange={(event) => setManualBirthYearInput(event.target.value)}
                placeholder="예: 2013"
              />
              {hasBirthYearError && (
                <div className="dist-error-text">출생연도는 4자리 숫자로 입력해주세요. 예: 2013</div>
              )}
            </label>
          )}

          <div className="dist-group-label">거리</div>
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
            <b>기록이나 등수를 넣어보세요</b>
          </div>
          <p className="dist-input-guide">
            {mode === "time"
              ? "예선 기록을 적어주세요. 2분 29초 15는 2:29.15, 45초 8은 45.8처럼 입력하면 됩니다."
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

          {hasInputError && (
            <div className="dist-error-text">
              {mode === "time"
                ? "시간 형식을 확인해주세요. 2분 29초 15는 2:29.15, 45초 8은 45.8로 입력해주세요."
                : "등수는 숫자만 입력해주세요. 12등이면 12처럼 입력하면 됩니다."}
            </div>
          )}
        </div>
      </section>

      {calc?.showResult && selectedRow && edges && (
        <section className="dist-card">
          <div className="dist-group-label">{groupLabel}</div>
          {fallbackNotice && <div className="dist-fallback-note">{fallbackNotice}</div>}
          <div className="dist-verdict">{calc.conclusion}</div>
          <div className="dist-verdict-detail">{calc.detail}</div>

          <details className="dist-evidence">
            <summary className="dist-evidence-summary">근거 보기</summary>
            <div className="dist-evidence-inner">
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
            {noRowForSelection ? "가까운 연도에도 공개 가능한 데이터가 없습니다" : "이 조건은 공개하지 않습니다"}
          </div>
          <div className="dist-thin-body">
            {noRowForSelection
              ? "현재 선택한 조건은 ±2년 범위에서도 공개 기준을 충족한 데이터가 없습니다. 다른 거리나 나이 입력 방식으로 확인해주세요."
              : "이 조건은 참가 선수가 적어 개인 기록이 짐작될 수 있어서 공개하지 않습니다. 기록이 없거나 실력이 낮다는 뜻은 아닙니다."}
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
          근거로 사용하지 말아주세요.
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
