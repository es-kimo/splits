package kr.splits.reservation

import org.junit.jupiter.api.Test
import org.springframework.http.HttpMethod
import java.util.concurrent.Callable
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class BoardApiTest : ApiTestSupport() {

    @Test
    fun `모임 토큰이 없거나 틀리면 이름 목록을 받을 수 없다`() {
        createClub("가람", "나래")

        assertEquals(401, call(HttpMethod.GET, "/club").status)
        assertEquals(401, call(HttpMethod.GET, "/club", clubToken = "not-a-real-token").status)
    }

    @Test
    fun `모임 토큰이 있으면 모임원과 현재 회차를 받는다`() {
        val club = createClub("가람", "나래")

        val result = call(HttpMethod.GET, "/club", club.token)

        assertEquals(200, result.status)
        assertEquals(listOf("가람", "나래"), result.body["members"].map { it["name"].asText() })
        assertEquals(club.roundId, result.body["currentRoundId"].asLong())
    }

    @Test
    fun `다른 모임의 회차와 모임원은 쓸 수 없다`() {
        val mine = createClub("가람")
        val other = createClub("나래")
        mine.savePlan(mine.slot(1, "2026-12-05", 14, 3, "가람"))

        // 남의 회차 번호로 조회
        assertEquals(404, call(HttpMethod.GET, "/rounds/${mine.roundId}/board", other.token).status)

        // 남의 회차 번호로 예약 등록
        val write = call(
            HttpMethod.POST, "/rounds/${mine.roundId}/reservations", other.token, memberId = other.id("나래"),
            body = mapOf("playDate" to "2026-12-05", "startHour" to 14, "endHour" to 16, "courtNo" to 3, "bookerMemberId" to other.id("나래")),
        )
        assertEquals(404, write.status)

        // 내 모임 토큰에 남의 모임원 번호
        val foreignMember = call(
            HttpMethod.POST, "/rounds/${mine.roundId}/reservations", mine.token, memberId = other.id("나래"),
            body = mapOf("playDate" to "2026-12-05", "startHour" to 14, "endHour" to 16, "courtNo" to 3, "bookerMemberId" to mine.id("가람")),
        )
        assertEquals(400, foreignMember.status)
        assertEquals("MEMBER_INVALID", foreignMember.code)

        assertEquals("PLANNED", mine.board().body.slotByNo(1)["state"].asText())
    }

    @Test
    fun `배정자가 아닌 사람이 잡아도 슬롯은 확보가 되고 예약자가 따로 남는다`() {
        val club = createClub("가람", "나래")
        club.savePlan(club.slot(4, "2026-12-12", 14, 3, "가람"))

        val result = club.reserve("나래", "2026-12-12", 14, 3)

        assertEquals(200, result.status)
        val slot = result.body.slotByNo(4)
        assertEquals("SECURED", slot["state"].asText())
        assertEquals(club.id("가람"), slot["assigneeMemberId"].asLong())
        val reservation = result.body["reservations"].single()
        assertEquals(club.id("나래"), reservation["bookerMemberId"].asLong())
        assertEquals(slot["id"].asLong(), reservation["slotId"].asLong())
    }

    @Test
    fun `대신 입력하면 예약자와 입력한 사람이 따로 기록된다`() {
        val club = createClub("가람", "나래")
        club.savePlan(club.slot(1, "2026-12-05", 16, 3, "가람"))

        val result = club.reserve(actor = "나래", date = "2026-12-05", start = 16, court = 3, slotNo = 1, booker = "가람")

        val reservation = result.body["reservations"].single()
        assertEquals(club.id("가람"), reservation["bookerMemberId"].asLong())
        assertEquals(club.id("나래"), reservation["reportedByMemberId"].asLong())
    }

    @Test
    fun `같은 날짜 시간 코트는 한 번만 등록되고 먼저 넣은 사람을 알려준다`() {
        val club = createClub("가람", "나래")
        club.savePlan(club.slot(1, "2026-12-05", 14, 3, "가람"))
        club.reserve("가람", "2026-12-05", 14, 3)

        val second = club.reserve("나래", "2026-12-05", 14, 3)

        assertEquals(409, second.status)
        assertEquals("RESERVATION_DUPLICATE", second.code)
        assertTrue("가람" in second.message, second.message)
        assertEquals(1, club.board().body["reservations"].size())
    }

    @Test
    fun `두 명이 동시에 같은 예약을 등록하면 한 건만 들어간다`() {
        val club = createClub("가람", "나래")
        club.savePlan(club.slot(1, "2026-12-05", 14, 3, "가람"))
        val start = CountDownLatch(1)
        val pool = Executors.newFixedThreadPool(2)

        val statuses = try {
            listOf("가람", "나래")
                .map { name ->
                    pool.submit(Callable {
                        start.await()
                        club.reserve(name, "2026-12-05", 14, 3, slotNo = null).status
                    })
                }
                .also { start.countDown() }
                .map { it.get(20, TimeUnit.SECONDS) }
        } finally {
            pool.shutdownNow()
        }

        assertEquals(listOf(200, 409), statuses.sorted())
        assertEquals(1, club.board().body["reservations"].size())
    }

    @Test
    fun `같은 시간에 코트를 둘 잡으면 하나는 계획 외로 남는다`() {
        val club = createClub("가람", "나래")
        club.savePlan(club.slot(18, "2026-12-06", 10, null, "가람"))
        club.reserve("가람", "2026-12-06", 10, 2)

        val result = club.reserve("나래", "2026-12-06", 10, 1)

        assertEquals(200, result.status)
        assertEquals(1, result.body["summary"]["secured"].asInt())
        assertEquals(1, result.body["summary"]["unplanned"].asInt())
    }

    @Test
    fun `계획에 없는 시간의 예약은 계획 외로 모인다`() {
        val club = createClub("가람")
        club.savePlan(club.slot(17, "2026-12-20", 10, null, "가람"))

        val result = club.reserve("가람", "2026-12-20", 8, 3)

        assertEquals("PLANNED", result.body.slotByNo(17)["state"].asText())
        assertTrue(result.body["reservations"].single()["slotId"].isNull)
        assertEquals(1, result.body["summary"]["unplanned"].asInt())
    }

    @Test
    fun `슬롯과 날짜가 다른 예약을 그 슬롯에 붙일 수 없다`() {
        val club = createClub("가람")
        club.savePlan(club.slot(1, "2026-12-05", 14, 3, "가람"))

        val result = club.reserve("가람", "2026-12-06", 14, 3, slotNo = 1)

        assertEquals(400, result.status)
    }

    @Test
    fun `못 한다고 알리면 도움 필요가 되고 누가 잡으면 확보로 바뀐다`() {
        val club = createClub("가람", "나래")
        club.savePlan(club.slot(4, "2026-12-12", 14, 3, "가람"))

        val failed = club.fail("가람", 4, "NEED_HELP")
        assertEquals("NEED_HELP", failed.body.slotByNo(4)["state"].asText())
        assertEquals(1, failed.body["summary"]["needHelp"].asInt())

        val secured = club.reserve("나래", "2026-12-12", 14, 3)
        assertEquals("SECURED", secured.body.slotByNo(4)["state"].asText())
        assertEquals(0, secured.body["summary"]["needHelp"].asInt())
    }

    @Test
    fun `이미 확보된 슬롯은 마감으로 바꿀 수 없다`() {
        val club = createClub("가람", "나래")
        club.savePlan(club.slot(4, "2026-12-12", 14, 3, "가람"))
        club.reserve("나래", "2026-12-12", 14, 3)

        val result = club.fail("가람", 4, "CLOSED")

        assertEquals(409, result.status)
        assertEquals("SLOT_ALREADY_SECURED", result.code)
    }

    @Test
    fun `도움 필요인 슬롯을 다른 사람이 맡으면 대기로 돌아간다`() {
        val club = createClub("가람", "나래")
        club.savePlan(club.slot(4, "2026-12-12", 14, 3, "가람"))
        val slotId = club.fail("가람", 4, "NEED_HELP").body.slotByNo(4)["id"].asLong()

        val result = call(
            HttpMethod.PUT, "/rounds/${club.roundId}/slots/$slotId/assignee", club.token, memberId = club.id("나래"),
            body = mapOf("memberId" to club.id("나래")),
        )

        val slot = result.body.slotByNo(4)
        assertEquals("PLANNED", slot["state"].asText())
        assertEquals(club.id("나래"), slot["assigneeMemberId"].asLong())
    }

    @Test
    fun `예약을 취소하면 같은 시간의 계획 외 예약이 그 슬롯을 채운다`() {
        val club = createClub("가람", "나래")
        club.savePlan(club.slot(18, "2026-12-06", 10, null, "가람"))
        val first = club.reserve("가람", "2026-12-06", 10, 2).body["reservations"].single()["id"].asLong()
        club.reserve("나래", "2026-12-06", 10, 1)

        val result = call(
            HttpMethod.DELETE, "/rounds/${club.roundId}/reservations/$first", club.token, memberId = club.id("가람"),
        )

        assertEquals(200, result.status)
        assertEquals("SECURED", result.body.slotByNo(18)["state"].asText())
        val remaining = result.body["reservations"].single()
        assertEquals(1, remaining["courtNo"].asInt())
        assertEquals(0, result.body["summary"]["unplanned"].asInt())
    }

    @Test
    fun `마지막 예약을 취소하면 슬롯이 다시 빈다`() {
        val club = createClub("가람")
        club.savePlan(club.slot(1, "2026-12-05", 14, 3, "가람"))
        val id = club.reserve("가람", "2026-12-05", 14, 3).body["reservations"].single()["id"].asLong()

        val result = call(HttpMethod.DELETE, "/rounds/${club.roundId}/reservations/$id", club.token, memberId = club.id("가람"))

        assertEquals("PLANNED", result.body.slotByNo(1)["state"].asText())
        assertEquals(0, result.body["reservations"].size())
        // 취소한 뒤에는 같은 코트·시간을 다시 등록할 수 있어야 한다.
        assertEquals(200, club.reserve("가람", "2026-12-05", 14, 3).status)
    }

    @Test
    fun `바뀐 게 없으면 본문 없이 204를 받고 바뀌면 새 현황을 받는다`() {
        val club = createClub("가람")
        club.savePlan(club.slot(1, "2026-12-05", 14, 3, "가람"))
        val version = club.board().body["round"]["version"].asLong()

        assertEquals(204, club.board(since = version).status)

        club.reserve("가람", "2026-12-05", 14, 3)
        val changed = club.board(since = version)
        assertEquals(200, changed.status)
        assertTrue(changed.body["round"]["version"].asLong() > version)
    }

    @Test
    fun `바꾼 내용은 누가 했는지와 함께 기록에 남는다`() {
        val club = createClub("가람", "나래")
        club.savePlan(club.slot(1, "2026-12-05", 14, 3, "가람"))
        club.reserve(actor = "나래", date = "2026-12-05", start = 14, court = 3, booker = "가람")

        val events = call(HttpMethod.GET, "/rounds/${club.roundId}/events", club.token).body

        val latest = events.first()
        assertEquals("나래", latest["actorName"].asText())
        assertEquals("RESERVATION_CREATED", latest["type"].asText())
        assertTrue("12/5(토) 14~16 3코트" in latest["detail"].asText(), latest["detail"].asText())
    }
}
