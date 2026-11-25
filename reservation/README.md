# reservation

모임이 공공 코트를 예약하는 날, **누가 어느 시간을 잡았는지 한 화면에서 보는 현황판**이에요.
예약 자체는 각자 예약 사이트에서 직접 하고, 이 서비스는 계획·보고·정리만 맡아요.

- 카톡방에 올린 링크 하나로 들어와요. 설치와 가입이 없어요.
- 처음 한 번 이름을 고르면 다음부터는 바로 열려요.
- 잡았으면 "예약했어요", 못 잡았으면 "못 잡았어요"를 눌러요. 다른 사람 화면에 3초 안에 반영돼요.
- 예약이 끝나면 "카톡에 올릴 결과 복사"로 정리된 글을 카톡방에 붙여넣어요.

## 하지 않는 것

- 예약 사이트에 대신 로그인하거나 자동으로 예약하지 않아요.
- 예약 사이트의 계정 정보를 받지 않아요.

## 구조

```
reservation/
  backend/    Kotlin + Spring Boot, Flyway, MySQL 8 (로컬은 H2)
  frontend/   Vite + React SPA, Cloudflare Worker(API 프록시)
```

핵심은 **계획과 실제 예약을 따로 저장**하는 거예요.

| 저장 단위 | 담는 것 |
|---|---|
| 계획 슬롯 (`plan_slot`) | 번호, 날짜, 시간, 코트 조건(특정 코트 또는 아무 코트), 담당자 |
| 실제 예약 (`reservation`) | 날짜, 시간, 코트, 예약자, 입력한 사람 |

- 예약을 등록하면 날짜·시간이 맞는 빈 슬롯에 붙어요. 담당자가 아닌 사람이 잡아도 그 슬롯은 "확보"예요.
- 맞는 슬롯이 없으면 "계획에 없던 예약"으로 따로 모여요.
- 같은 날짜·시간·코트는 한 건만 들어가요. 두 번째는 거절하고 먼저 넣은 사람을 알려줘요.
- 현황판을 바꾸는 요청은 회차 한 줄을 잠근 뒤 처리해요. 동시에 눌러도 한 번에 하나씩 반영돼요.

### 누구인지 확인하는 방식

| 무엇 | 어떻게 | 헤더 |
|---|---|---|
| 모임 | 링크에 든 256비트 토큰 | `X-Club-Token` |
| 사람 | 화면에서 고른 이름 (본인 확인 아님) | `X-Member-Id` |
| 총무 | PIN을 넣고 받은 30일짜리 토큰 | `X-Admin-Token` |

링크를 아는 사람은 누구 이름으로든 입력할 수 있어요. 대신 모든 변경을 "변경 기록"에 남겨요.
계획과 모임원을 고치는 것만 총무 PIN으로 막아요.

## 로컬 실행

도커 없이 돼요. 백엔드는 H2 파일 DB(`backend/build/localdb`)를 써요.

```bash
cd reservation/backend && ./gradlew bootRun
```

```bash
cd reservation/frontend && npm install && npm run dev
```

백엔드는 `http://localhost:8090`, 프런트는 `http://localhost:5180`이에요. 프런트의 `/api`는 백엔드로 넘어가요.

모임은 가입 화면이 없어서 한 번 직접 만들어요. 응답의 `accessToken`으로 `http://localhost:5180/g/<accessToken>`에 들어가면 돼요.

```bash
curl -s -X POST http://localhost:8090/api/v1/bootstrap/clubs -H 'Content-Type: application/json' -H 'X-Bootstrap-Secret: local-bootstrap' -d '{"name":"테스트 모임","adminPin":"2468"}' -w '\n%{http_code} %{content_type}\n'
```

## 테스트

```bash
cd reservation/backend && ./gradlew test
```

```bash
cd reservation/frontend && npm test && npm run build
```

- 백엔드 테스트는 실제 마이그레이션(`V1__init.sql`)으로 H2에 스키마를 만들어 돌려요.
- 프런트는 화면 렌더링 테스트를 두지 않고, 순수 로직(계획 글 읽기, 현황 정리, 카톡용 글)만 테스트해요.
- 테스트 데이터의 이름은 모두 가상이에요. **저장소가 공개라서 실제 모임원 이름, 카톡 내보내기 파일, 전화번호는 넣지 않아요.**

## 배포

주소는 두 개예요. 둘 다 Cloudflare에 있는 `splits.kr` 영역에 만들어요.

| 주소 | 역할 | 어디서 |
|---|---|---|
| `court.splits.kr` | 화면 + `/api` 프록시 | Cloudflare Worker (`frontend/wrangler.jsonc`) |
| `court-api.splits.kr` | 백엔드 | 오라클 인스턴스, Cloudflare Tunnel 경유 |

`court-api`를 `api.court`로 하지 않은 이유는 Cloudflare 무료 인증서가 한 단계 서브도메인까지만 덮기 때문이에요.

### 처음 한 번 (사람이 직접)

1. `splits.kr` 네임서버를 Cloudflare로 옮겨요. 기존 레코드(A 4개, `www` CNAME)는 **DNS 전용**으로 두면 쇼트트랙 사이트는 그대로예요.
2. Cloudflare Zero Trust에서 터널을 만들고, 공개 호스트 이름 `court-api.splits.kr`을 `http://backend:8080`으로 연결해요. 터널 토큰을 받아 둬요.
3. 오라클 인스턴스에서 저장소를 받고 환경 파일을 채워요.

   ```bash
   git clone https://github.com/es-kimo/splits.git ~/splits && cd ~/splits/reservation && cp .env.example .env
   ```

4. 백엔드를 띄워요. 호스트 포트를 열지 않아서 같은 인스턴스의 다른 서비스와 겹치지 않아요.

   ```bash
   docker compose -f docker-compose.prod.yml up -d --build
   ```

5. 모임을 만들고, `.env`의 `BOOTSTRAP_SECRET`을 비운 뒤 백엔드를 다시 띄워 엔드포인트를 닫아요.
6. GitHub 저장소 비밀값을 넣어요: `ORACLE_HOST`, `ORACLE_USERNAME`, `ORACLE_SSH_KEY`, `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`.

### 이후

`reservation-v0.1.0` 같은 태그를 푸시하면 `.github/workflows/reservation-deploy.yml`이 백엔드와 프런트를 올려요.

## 아직 없는 것

- 계획 자동 배정, 참여 모집
- 슬롯별 참석 표시, 안 쓰는 예약 취소 알림
- 카카오 로그인, 카카오톡 공유 버튼 (지금은 글 복사)
- 예약 사이트의 주간 한도 검사 (실제 적용 규칙이 확인되지 않아 사람별 건수만 보여줘요)
