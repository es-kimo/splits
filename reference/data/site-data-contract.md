# site/data JSON 계약 스키마

`build_data.py`가 생성하고 `build_site.py`가 소비하는 데이터 계약입니다.  
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

익명 통계(`k >= 10`)만 공개합니다.

```json
{
  "kAnonymityMin": 10,
  "byAge": [
    {
      "age": 12,
      "athleteCount": 12,
      "sampleSize": 66,
      "rankMin": 1,
      "rankMedian": 4.0,
      "rankMax": 29,
      "top3Rate": 0.4091
    }
  ],
  "byDistance": [],
  "byYear": []
}
```

`byAge`, `byDistance`, `byYear`의 각 항목은 모두 동일하게 `athleteCount >= 10`인 그룹만 포함합니다.

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
