# site/data JSON 계약 스키마

`build_data.py`가 생성하고 Astro 렌더러(`web/`)가 소비하는 데이터 계약입니다.  
렌더링 계층은 아래 JSON만 입력으로 사용하며, CSV를 직접 읽지 않습니다.

## 출력 파일

1. `site/data/athletes.json`
2. `site/data/meets.json`
3. `site/data/distribution.json`
4. `site/data/meta.json`

## 1) athletes.json

```json
{
  "ages": [7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18],
  "athletes": [
    {
      "idNo": "string",
      "slug": "string",
      "url": "athlete/{slug}/",
      "name": "string",
      "birth": 2004,
      "team": "string",
      "gender": "string|null",
      "designationReason": "string",
      "mediaReportUrl": "https://...",
      "designatedAt": "YYYY-MM-DD",
      "status": "active",
      "first": 9,
      "ages": { "7": 1, "8": null, "...": null, "18": 3 },
      "elem": { "best": 1, "median": 2.5, "worst": 12, "count": 37 },
      "history": [
        {
          "year": 2015,
          "age": 11,
          "meet": "대회명",
          "distance": 500,
          "sf": false,
          "rank": 2,
          "round": "A|B|종합|..."
        }
      ]
    }
  ]
}
```

## 2) meets.json

대회 단위 익명 집계입니다.

```json
{
  "items": [
    {
      "year": 2024,
      "meet": "대회명",
      "raceCount": 128,
      "athleteCount": 14,
      "distanceSet": [500, 1000, 1500],
      "roundTypes": ["A", "B", "종합"],
      "hasSemifinal": true
    }
  ]
}
```

## 3) distribution.json

`data/stats_distribution.csv`를 JSON으로 변환한 익명 통계(`k >= 10`)입니다.

```json
{
  "kAnonymityMin": 10,
  "insufficientText": "데이터 부족",
  "filters": {
    "birthYears": [2008, 2009],
    "genders": ["남", "여"],
    "schoolLevels": ["초등", "중등", "고등", "대학", "일반", "오픈"],
    "distances": [500, 1000, 1500, 3000]
  },
  "rows": [
    {
      "birthYear": 2009,
      "gender": "남",
      "schoolLevel": "중등",
      "distance": 1000,
      "athleteCount": 24,
      "insufficient": false,
      "timeP10": 87.123,
      "timeP25": 88.014,
      "timeP50": 89.432,
      "timeP75": 91.205,
      "timeP90": 93.114,
      "rankP25": 2.0,
      "rankP50": 4.0,
      "rankP75": 7.0
    },
    {
      "birthYear": 1980,
      "gender": "여",
      "schoolLevel": "일반",
      "distance": 3000,
      "athleteCount": null,
      "insufficient": true,
      "timeP10": null,
      "timeP25": null,
      "timeP50": null,
      "timeP75": null,
      "timeP90": null,
      "rankP25": null,
      "rankP50": null,
      "rankP75": null
    }
  ]
}
```

- `rows`는 `출생연도+성별+학령구간+거리` 단위이며, 원본 CSV의 행 순서를 정규화해 제공합니다.
- `insufficient=true`인 행은 `k` 기준 미달 구간이며, `athleteCount`와 지표 값은 모두 `null`입니다.
- `filters`는 클라이언트 UI 선택지 생성을 위한 사전 인덱스입니다.

## 4) meta.json

렌더러 메타/헤더 지표와 갱신 정보를 담습니다.

```json
{
  "athleteCount": 14,
  "placementCount": 1234,
  "yearStart": 2012,
  "yearEnd": 2025,
  "yearSpan": 13,
  "ageMin": 7,
  "ageMax": 25,
  "elemTop2Count": 14,
  "elemWorstBand": "20등대",
  "firstAgeMin": 7,
  "firstAgeMax": 12,
  "missingElemNames": [],
  "generatedAt": "YYYY-MM-DD",
  "publicFigureCount": 14,
  "activeFigureCount": 14
}
```

## 개인정보/공개 범위 규칙

- 개인 식별 정보는 `data/public_figures.csv`에서 `상태=active`인 선수만 포함합니다.
- 명단 외 선수의 `idNo`, 이름, 소속, 출생 정보는 JSON에 포함하지 않습니다.
- `distribution.json`은 집계값만 포함하며 원시 레코드/개별 선수 식별자를 포함하지 않습니다.
