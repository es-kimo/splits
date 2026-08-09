import { useEffect, useMemo, useState, type ReactNode } from "react";

import type { DistributionDoc, PeerDistributionRow } from "../lib/types";

type InputMode = "record" | "rank";

interface Props extends DistributionDoc {}

interface CalcResult {
  status: "idle" | "invalid" | "missing" | "insufficient" | "ok";
  message?: string;
  topPercent?: number;
}

const RECORD_POINTS = [
  { key: "timeP10", q: 10 },
  { key: "timeP25", q: 25 },
  { key: "timeP50", q: 50 },
  { key: "timeP75", q: 75 },
  { key: "timeP90", q: 90 },
] as const;

const RANK_POINTS = [
  { key: "rankP25", q: 25 },
  { key: "rankP50", q: 50 },
  { key: "rankP75", q: 75 },
] as const;

export default function DistributionTool(props: Props) {
  const defaultRow = props.rows.find((row) => !row.insufficient) ?? props.rows[0];
  const [birthYear, setBirthYear] = useState<number | null>(defaultRow?.birthYear ?? null);
  const [gender, setGender] = useState(defaultRow?.gender ?? "");
  const [schoolLevel, setSchoolLevel] = useState(defaultRow?.schoolLevel ?? "");
  const [distance, setDistance] = useState<number | null>(defaultRow?.distance ?? null);
  const [mode, setMode] = useState<InputMode>("record");
  const [inputValue, setInputValue] = useState("");
  const [includeInsufficient, setIncludeInsufficient] = useState(false);

  const preferredRows = useMemo(() => {
    const sufficientRows = props.rows.filter((row) => !row.insufficient);
    if (includeInsufficient || !sufficientRows.length) return props.rows;
    return sufficientRows;
  }, [includeInsufficient, props.rows]);

  const availableBirthYears = useMemo(
    () => props.filters.birthYears.filter((item) => preferredRows.some((row) => row.birthYear === item)),
    [preferredRows, props.filters.birthYears],
  );
  const availableGenders = useMemo(
    () =>
      props.filters.genders.filter((item) =>
        preferredRows.some((row) => row.birthYear === birthYear && row.gender === item),
      ),
    [birthYear, props.filters.genders, preferredRows],
  );
  const availableSchoolLevels = useMemo(
    () =>
      props.filters.schoolLevels.filter((item) =>
        preferredRows.some((row) => row.birthYear === birthYear && row.gender === gender && row.schoolLevel === item),
      ),
    [birthYear, gender, props.filters.schoolLevels, preferredRows],
  );
  const availableDistances = useMemo(
    () =>
      props.filters.distances.filter((item) =>
        preferredRows.some(
          (row) =>
            row.birthYear === birthYear && row.gender === gender && row.schoolLevel === schoolLevel && row.distance === item,
        ),
      ),
    [birthYear, gender, schoolLevel, props.filters.distances, preferredRows],
  );

  useEffect(() => {
    if (availableBirthYears.length && (birthYear === null || !availableBirthYears.includes(birthYear))) {
      setBirthYear(availableBirthYears[0]);
    }
  }, [availableBirthYears, birthYear]);
  useEffect(() => {
    if (availableGenders.length && !availableGenders.includes(gender)) setGender(availableGenders[0]);
  }, [availableGenders, gender]);
  useEffect(() => {
    if (availableSchoolLevels.length && !availableSchoolLevels.includes(schoolLevel)) setSchoolLevel(availableSchoolLevels[0]);
  }, [availableSchoolLevels, schoolLevel]);
  useEffect(() => {
    if (availableDistances.length && (distance === null || !availableDistances.includes(distance))) {
      setDistance(availableDistances[0]);
    }
  }, [availableDistances, distance]);
  useEffect(() => {
    const currentExists = preferredRows.some(
      (row) =>
        row.birthYear === birthYear && row.gender === gender && row.schoolLevel === schoolLevel && row.distance === distance,
    );
    if (currentExists || !preferredRows.length) return;
    const next = preferredRows[0];
    setBirthYear(next.birthYear);
    setGender(next.gender);
    setSchoolLevel(next.schoolLevel);
    setDistance(next.distance);
  }, [birthYear, distance, gender, preferredRows, schoolLevel]);

  const selectedRow = useMemo(() => {
    if (birthYear === null || distance === null || !gender || !schoolLevel) return undefined;
    return props.rows.find(
      (row) =>
        row.birthYear === birthYear && row.gender === gender && row.schoolLevel === schoolLevel && row.distance === distance,
    );
  }, [birthYear, distance, gender, schoolLevel, props.rows]);
  const alternativeHint = useMemo(() => {
    if (!selectedRow || !selectedRow.insufficient) return "";
    return buildAlternativeHint(selectedRow, props.rows);
  }, [selectedRow, props.rows]);
  const sufficientCount = useMemo(() => props.rows.filter((row) => !row.insufficient).length, [props.rows]);

  const calcResult = useMemo<CalcResult>(() => {
    if (!selectedRow) {
      return { status: "missing", message: "선택한 조건의 분포가 없습니다." };
    }
    if (selectedRow.insufficient) {
      return { status: "insufficient", message: props.insufficientText + " (해당 조건은 집계 인원이 부족합니다.)" };
    }
    const normalizedInput = inputValue.trim();
    if (!normalizedInput) {
      return { status: "idle", message: mode === "record" ? "기록을 입력해 주세요." : "순위를 입력해 주세요." };
    }
    if (mode === "record") {
      const seconds = parseRecordSeconds(normalizedInput);
      if (seconds === null) {
        return { status: "invalid", message: "기록 형식이 올바르지 않습니다. 예) 1:31.52 또는 91.52" };
      }
      const points = buildPoints(selectedRow, RECORD_POINTS);
      const topPercent = interpolateTopPercent(seconds, points);
      if (topPercent === null) {
        return { status: "missing", message: "선택한 조건에 기록 분포 기준값이 없습니다." };
      }
      return { status: "ok", topPercent };
    }
    const rankValue = Number(normalizedInput.replace(",", "."));
    if (!Number.isFinite(rankValue) || rankValue <= 0) {
      return { status: "invalid", message: "순위는 1 이상의 숫자로 입력해 주세요." };
    }
    const points = buildPoints(selectedRow, RANK_POINTS);
    const topPercent = interpolateTopPercent(rankValue, points);
    if (topPercent === null) {
      return { status: "missing", message: "선택한 조건에 순위 분포 기준값이 없습니다." };
    }
    return { status: "ok", topPercent };
  }, [inputValue, mode, props.insufficientText, selectedRow]);

  return (
    <div style={{ display: "grid", gap: 12 }}>
      <p style={helperTextStyle}>
        입력값은 브라우저 안에서만 계산해요. 서버로 전송하거나 저장하지 않습니다.
      </p>
      <div style={{ display: "flex", gap: 8, alignItems: "center", justifyContent: "space-between", flexWrap: "wrap" }}>
        <p style={helperTextStyle}>조회 가능 조합 {sufficientCount}개 / 전체 {props.rows.length}개</p>
        <button type="button" onClick={() => setIncludeInsufficient((prev) => !prev)} style={chipStyle(includeInsufficient)}>
          데이터 부족 구간 보기 {includeInsufficient ? "켜짐" : "꺼짐"}
        </button>
      </div>
      <div style={gridStyle}>
        <SelectBox label="출생연도" value={String(birthYear ?? "")} onChange={(v) => setBirthYear(Number(v) || null)}>
          {availableBirthYears.map((item) => (
            <option key={item} value={item}>
              {item}년
            </option>
          ))}
        </SelectBox>
        <SelectBox label="성별" value={gender} onChange={setGender}>
          {availableGenders.map((item) => (
            <option key={item} value={item}>
              {item}
            </option>
          ))}
        </SelectBox>
        <SelectBox label="학령구간" value={schoolLevel} onChange={setSchoolLevel}>
          {availableSchoolLevels.map((item) => (
            <option key={item} value={item}>
              {item}
            </option>
          ))}
        </SelectBox>
        <SelectBox label="거리" value={String(distance ?? "")} onChange={(v) => setDistance(Number(v) || null)}>
          {availableDistances.map((item) => (
            <option key={item} value={item}>
              {item}m
            </option>
          ))}
        </SelectBox>
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <button type="button" onClick={() => setMode("record")} style={chipStyle(mode === "record")}>
          기록 입력
        </button>
        <button type="button" onClick={() => setMode("rank")} style={chipStyle(mode === "rank")}>
          순위 입력
        </button>
      </div>
      <label style={{ display: "grid", gap: 6 }}>
        <span style={labelStyle}>{mode === "record" ? "기록(초 또는 분:초)" : "순위"}</span>
        <input
          type="text"
          value={inputValue}
          onChange={(event) => setInputValue(event.target.value)}
          placeholder={mode === "record" ? "예: 1:31.52 또는 91.52" : "예: 12"}
          style={inputStyle}
          inputMode="decimal"
        />
      </label>
      <article style={resultCardStyle(calcResult.status)}>
        {calcResult.status === "ok" ? (
          <>
            <strong style={{ fontSize: 18, letterSpacing: "-0.02em" }}>
              상위 약 {Math.max(1, Math.round(calcResult.topPercent ?? 0))}%
            </strong>
            <p style={{ margin: "6px 0 0", fontSize: 13.5, color: "#5B5F68" }}>
              같은 조건 집단에서 입력값의 상대 위치를 분위값으로 근사했습니다.
            </p>
          </>
        ) : (
          <p style={{ margin: 0, fontSize: 14, color: calcResult.status === "invalid" ? "#B42318" : "#5B5F68" }}>
            {calcResult.message}
          </p>
        )}
      </article>
      {calcResult.status === "insufficient" && alternativeHint && <p style={helperTextStyle}>{alternativeHint}</p>}
      {selectedRow && !selectedRow.insufficient && (
        <p style={helperTextStyle}>
          {mode === "record"
            ? `기준값: P10 ${formatSeconds(selectedRow.timeP10)} · P50 ${formatSeconds(selectedRow.timeP50)} · P90 ${formatSeconds(selectedRow.timeP90)}`
            : `기준값: P25 ${formatRank(selectedRow.rankP25)}등 · P50 ${formatRank(selectedRow.rankP50)}등 · P75 ${formatRank(selectedRow.rankP75)}등`}
          {selectedRow.athleteCount ? ` · 집단 인원 ${selectedRow.athleteCount}명` : ""}
        </p>
      )}
      <p style={helperTextStyle}>k-익명 기준은 {props.kAnonymityMin}명입니다.</p>
    </div>
  );
}

function buildPoints(
  row: PeerDistributionRow,
  source: ReadonlyArray<{ key: keyof PeerDistributionRow; q: number }>,
): Array<{ value: number; q: number }> {
  const points = source
    .map((item) => ({ value: row[item.key], q: item.q }))
    .filter((item): item is { value: number; q: number } => typeof item.value === "number");
  return points.sort((a, b) => a.value - b.value);
}

function interpolateTopPercent(value: number, points: Array<{ value: number; q: number }>): number | null {
  if (!points.length) return null;
  if (points.length === 1) return clamp(points[0].q, 1, 99);
  if (value <= points[0].value) {
    return clamp(extrapolate(value, points[0], points[1], "left"), 1, 99);
  }
  for (let idx = 0; idx < points.length - 1; idx += 1) {
    const left = points[idx];
    const right = points[idx + 1];
    if (value <= right.value) {
      if (right.value === left.value) return clamp(right.q, 1, 99);
      const ratio = (value - left.value) / (right.value - left.value);
      return clamp(left.q + ratio * (right.q - left.q), 1, 99);
    }
  }
  const last = points[points.length - 1];
  const prev = points[points.length - 2];
  return clamp(extrapolate(value, prev, last, "right"), 1, 99);
}

function extrapolate(value: number, left: { value: number; q: number }, right: { value: number; q: number }, side: "left" | "right"): number {
  if (right.value === left.value) return side === "left" ? left.q : right.q;
  const slope = (right.q - left.q) / (right.value - left.value);
  if (side === "left") return left.q - slope * (left.value - value);
  return right.q + slope * (value - right.value);
}

function parseRecordSeconds(raw: string): number | null {
  const text = raw.trim().replace(",", ".");
  if (!text) return null;
  if (!text.includes(":")) {
    const value = Number(text);
    return Number.isFinite(value) && value > 0 ? value : null;
  }
  const parts = text.split(":");
  if (parts.length !== 2) return null;
  const minute = Number(parts[0]);
  const second = Number(parts[1]);
  if (!Number.isFinite(minute) || !Number.isFinite(second) || minute < 0 || second < 0 || second >= 60) return null;
  return minute * 60 + second;
}

function formatSeconds(value: number | null): string {
  if (value === null) return "-";
  if (!Number.isFinite(value)) return "-";
  if (value < 60) return `${value.toFixed(3)}초`;
  const minute = Math.floor(value / 60);
  const second = value - minute * 60;
  return `${minute}:${second.toFixed(3).padStart(6, "0")}`;
}

function formatRank(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "-";
  return value.toFixed(1);
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

function buildAlternativeHint(target: PeerDistributionRow, rows: PeerDistributionRow[]): string {
  const sameCoreRows = rows.filter(
    (row) =>
      !row.insufficient && row.birthYear === target.birthYear && row.gender === target.gender && row.distance === target.distance,
  );
  if (sameCoreRows.length) {
    const levels = uniqueValues(sameCoreRows.map((row) => row.schoolLevel)).slice(0, 4);
    return `같은 출생연도·성별·거리에서 조회 가능한 학령구간: ${levels.join(", ")}`;
  }
  const sameYearGender = rows.filter(
    (row) => !row.insufficient && row.birthYear === target.birthYear && row.gender === target.gender,
  );
  if (sameYearGender.length) {
    const combos = uniqueValues(sameYearGender.map((row) => `${row.schoolLevel} ${row.distance}m`)).slice(0, 4);
    return `같은 출생연도·성별에서 조회 가능한 조합: ${combos.join(" / ")}`;
  }
  return "같은 조건에서 조회 가능한 집계가 없어 다른 출생연도 또는 학령구간으로 바꿔 보세요.";
}

function uniqueValues(values: string[]): string[] {
  return Array.from(new Set(values));
}

function SelectBox(props: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  children: ReactNode;
}) {
  return (
    <label style={{ display: "grid", gap: 6 }}>
      <span style={labelStyle}>{props.label}</span>
      <select value={props.value} onChange={(event) => props.onChange(event.target.value)} style={selectStyle}>
        {props.children}
      </select>
    </label>
  );
}

function chipStyle(active: boolean) {
  return {
    flex: "none",
    minHeight: 40,
    padding: "0 14px",
    border: 0,
    borderRadius: 12,
    background: active ? "#17181C" : "#F2F4F7",
    color: active ? "#FFFFFF" : "#5B5F68",
    fontSize: 13.5,
    fontWeight: 700,
    cursor: "pointer",
    fontFamily: "inherit",
  };
}

function resultCardStyle(status: CalcResult["status"]) {
  if (status === "invalid") {
    return { ...baseResultStyle, border: "1px solid #FECDCA", background: "#FFF6F5" };
  }
  if (status === "ok") {
    return { ...baseResultStyle, border: "1px solid #D6E4FF", background: "#F5F8FF" };
  }
  return baseResultStyle;
}

const gridStyle = {
  display: "grid",
  gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
  gap: 10,
} as const;

const labelStyle = {
  fontSize: 12.5,
  fontWeight: 700,
  color: "#5B5F68",
} as const;

const selectStyle = {
  width: "100%",
  minHeight: 42,
  border: "1px solid #E3E7ED",
  borderRadius: 12,
  background: "#FFFFFF",
  padding: "0 12px",
  fontSize: 14,
  color: "#17181C",
  fontFamily: "inherit",
} as const;

const inputStyle = {
  width: "100%",
  minHeight: 44,
  border: "1px solid #D8DEE8",
  borderRadius: 12,
  background: "#FFFFFF",
  padding: "0 12px",
  fontSize: 15,
  color: "#17181C",
  fontFamily: "inherit",
} as const;

const helperTextStyle = {
  margin: 0,
  fontSize: 13,
  color: "#8A8F99",
} as const;

const baseResultStyle = {
  border: "1px solid #E3E7ED",
  background: "#FAFBFC",
  borderRadius: 14,
  padding: "14px 12px",
} as const;
