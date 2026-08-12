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
          "meetSlug": "2015-대회-슬러그",
          "meetUrl": "meet/2015-대회-슬러그/",
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

대회 단위 메타데이터 + 익명 집계입니다.

```json
{
  "items": [
    {
      "year": 2024,
      "meet": "대회명",
      "slug": "2024-대회-슬러그-1a2b3c4d",
      "url": "meet/2024-대회-슬러그-1a2b3c4d/",
      "raceCount": 128,
      "athleteCount": 14,
      "distanceSet": [500, 1000, 1500],
      "roundTypes": ["A", "B", "종합"],
      "hasSemifinal": true,
      "dateStart": "2024-10-12",
      "dateEnd": "2024-10-13",
      "location": null,
      "categoryBreakdown": [
        { "category": "남자초등5,6학년", "athleteCount": 81 },
        { "category": "여자초등5,6학년", "athleteCount": 72 }
      ],
      "distanceDistribution": {
        "kAnonymityMin": 10,
        "insufficientText": "데이터 부족",
        "items": [
          {
            "distance": 500,
            "athleteCount": 64,
            "insufficient": false,
            "timeP10": 45.123,
            "timeP25": 46.001,
            "timeP50": 47.331,
            "timeP75": 49.224,
            "timeP90": 51.009
          },
          {
            "distance": 3000,
            "athleteCount": null,
            "insufficient": true,
            "timeP10": null,
            "timeP25": null,
            "timeP50": null,
            "timeP75": null,
            "timeP90": null
          }
        ]
      },
      "publicFigureResults": [
        {
          "name": "홍길동",
          "slug": "hong-gildong",
          "url": "athlete/hong-gildong/",
          "bestRank": 1,
          "raceCount": 3,
          "distances": [500, 1000, 1500],
          "rounds": ["A"],
          "placements": [
            { "distance": 500, "rank": 1, "sf": false, "round": "A" }
          ]
        }
      ],
      "seriesKey": "전국남녀 종합 쇼트트랙스피드스케이팅 선수권대회",
      "seriesName": "전국남녀 종합 쇼트트랙스피드스케이팅 선수권대회",
      "seriesRound": 39,
      "seriesLinks": [
        {
          "year": 2023,
          "meet": "KB금융그룹 제38회 전국남녀 종합 쇼트트랙스피드스케이팅 선수권대회",
          "slug": "2023-kb금융그룹-제38회-전국남녀-종합-쇼트트랙스피드스케이팅-8f9e0d1c",
          "url": "meet/2023-kb금융그룹-제38회-전국남녀-종합-쇼트트랙스피드스케이팅-8f9e0d1c/"
        }
      ]
    }
  ]
}
```

- `meets.slug`는 `<year>-<compact-seed>-<hash8>` 형식이며, 파일시스템 경로 한계를 넘지 않도록 seed를 UTF-8 바이트 길이 기준으로 제한합니다.

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
- 프런트엔드에서 "출생연도 포함 비교"와 "출생연도 통합 비교"를 모두 제공할 때는 `rows`를 기반으로 통합 모드 집계를 추가 계산해 사용할 수 있습니다.

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
- `meets.json`의 `publicFigureResults`는 공개 명단 선수만 포함하며, 일반 선수 개별 성적은 포함하지 않습니다.
- `meets.json`의 `distanceDistribution`은 `k>=10` 구간만 수치가 노출됩니다. 기준 미만 구간은 `insufficient=true`와 `null` 값으로 표시합니다.
