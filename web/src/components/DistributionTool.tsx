import { useMemo, useState } from "react";

import type { DistributionAgeRow, DistributionDistanceRow, DistributionYearRow } from "../lib/types";

type Dimension = "age" | "distance" | "year";
type DistributionRow = DistributionAgeRow | DistributionDistanceRow | DistributionYearRow;

interface Props {
  kAnonymityMin: number;
  byAge: DistributionAgeRow[];
  byDistance: DistributionDistanceRow[];
  byYear: DistributionYearRow[];
}

function keyLabel(row: DistributionRow, dimension: Dimension): string {
  if (dimension === "age") return `${(row as DistributionAgeRow).age}살`;
  if (dimension === "distance") return `${(row as DistributionDistanceRow).distance}m`;
  return `${(row as DistributionYearRow).year}년`;
}

function keyValue(row: DistributionRow, dimension: Dimension): number {
  if (dimension === "age") return (row as DistributionAgeRow).age;
  if (dimension === "distance") return (row as DistributionDistanceRow).distance;
  return (row as DistributionYearRow).year;
}

export default function DistributionTool(props: Props) {
  const [dimension, setDimension] = useState<Dimension>("age");
  const [sortByTop3, setSortByTop3] = useState(false);

  const rows = useMemo(() => {
    const base: DistributionRow[] =
      dimension === "age" ? props.byAge : dimension === "distance" ? props.byDistance : props.byYear;
    const next = [...base];
    if (sortByTop3) {
      next.sort((a, b) => b.top3Rate - a.top3Rate || keyValue(a, dimension) - keyValue(b, dimension));
    } else {
      next.sort((a, b) => keyValue(a, dimension) - keyValue(b, dimension));
    }
    return next;
  }, [dimension, props.byAge, props.byDistance, props.byYear, sortByTop3]);

  const maxSample = rows.reduce((acc, row) => Math.max(acc, row.sampleSize), 0);

  return (
    <div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
        <button type="button" onClick={() => setDimension("age")} style={chipStyle(dimension === "age")}>
          나이별
        </button>
        <button type="button" onClick={() => setDimension("distance")} style={chipStyle(dimension === "distance")}>
          종목별
        </button>
        <button type="button" onClick={() => setDimension("year")} style={chipStyle(dimension === "year")}>
          연도별
        </button>
        <button type="button" onClick={() => setSortByTop3((v) => !v)} style={chipStyle(sortByTop3)}>
          {sortByTop3 ? "TOP3 비율순" : "기본순"}
        </button>
      </div>
      <p style={{ margin: "0 0 14px", fontSize: 13, color: "#8A8F99" }}>
        익명성 보호 기준은 k≥{props.kAnonymityMin}입니다. 기준 미만 그룹은 표시하지 않습니다.
      </p>
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {rows.map((row) => {
          const sampleRatio = maxSample > 0 ? row.sampleSize / maxSample : 0;
          return (
            <article
              key={`${dimension}-${keyValue(row, dimension)}`}
              style={{ background: "#FAFBFC", borderRadius: 14, padding: "12px 12px 10px" }}
            >
              <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 8 }}>
                <b style={{ fontSize: 15 }}>{keyLabel(row, dimension)}</b>
                <span style={{ fontSize: 12.5, color: "#8A8F99" }}>{row.athleteCount}명 · 표본 {row.sampleSize}건</span>
              </div>
              <div style={{ marginTop: 7, height: 8, background: "#E9ECF1", borderRadius: 99 }}>
                <span
                  style={{
                    display: "block",
                    width: `${Math.max(sampleRatio * 100, 4)}%`,
                    height: 8,
                    borderRadius: 99,
                    background: "#B9CCFB",
                  }}
                />
              </div>
              <div style={{ marginTop: 8, fontSize: 13, color: "#5B5F68" }}>
                최고 {row.rankMin}등 · 중앙값 {row.rankMedian.toFixed(1)}등 · 최저 {row.rankMax}등 · TOP3{" "}
                {(row.top3Rate * 100).toFixed(1)}%
              </div>
            </article>
          );
        })}
      </div>
    </div>
  );
}

function chipStyle(active: boolean): React.CSSProperties {
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
