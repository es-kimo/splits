package kr.splits.reservation

import org.junit.jupiter.api.Test
import org.springframework.http.HttpMethod
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class AdminApiTest : ApiTestSupport() {

    @Test
    fun `비밀값이 틀리면 모임을 만들 수 없다`() {
        val body = mapOf("name" to "몰래 만든 모임", "adminPin" to "1234")

        assertEquals(404, call(HttpMethod.POST, "/bootstrap/clubs", body = body).status)
        assertEquals(
            404,
            call(HttpMethod.POST, "/bootstrap/clubs", body = body, extraHeaders = mapOf("X-Bootstrap-Secret" to "wrong")).status,
        )
    }

    @Test
    fun `총무 토큰이 없으면 계획과 모임원을 바꿀 수 없다`() {
        val club = createClub("가람")

        val addMember = call(HttpMethod.POST, "/admin/members", club.token, body = mapOf("name" to "나래"))
        val savePlan = call(
            HttpMethod.PUT, "/admin/rounds/${club.roundId}/slots", club.token, adminToken = "123.bogus",
            body = listOf(club.slot(1, "2026-12-05", 14, 3, "가람")),
        )

        assertEquals(401, addMember.status)
        assertEquals(401, savePlan.status)
        assertEquals(0, club.board().body["slots"].size())
    }

    @Test
    fun `다른 모임의 총무 토큰은 통하지 않는다`() {
        val mine = createClub("가람")
        val other = createClub("나래")

        val result = call(HttpMethod.POST, "/admin/members", mine.token, adminToken = other.adminToken, body = mapOf("name" to "다온"))

        assertEquals(401, result.status)
    }

    @Test
    fun `PIN을 다섯 번 틀리면 맞는 PIN도 잠시 막힌다`() {
        val club = createClub("가람")

        repeat(5) {
            assertEquals(401, call(HttpMethod.POST, "/admin/login", club.token, body = mapOf("pin" to "0000")).status)
        }
        val locked = call(HttpMethod.POST, "/admin/login", club.token, body = mapOf("pin" to TEST_PIN))

        assertEquals(429, locked.status)
        assertEquals("ADMIN_LOCKED", locked.code)
    }

    @Test
    fun `같은 이름의 모임원은 두 번 넣을 수 없다`() {
        val club = createClub("가람")

        val result = call(HttpMethod.POST, "/admin/members", club.token, adminToken = club.adminToken, body = mapOf("name" to " 가람 "))

        assertEquals(409, result.status)
    }

    @Test
    fun `비활성으로 바꾼 모임원 이름으로는 입력할 수 없다`() {
        val club = createClub("가람", "나래")
        club.savePlan(club.slot(1, "2026-12-05", 14, 3, "가람"))
        call(
            HttpMethod.PATCH, "/admin/members/${club.id("나래")}", club.token, adminToken = club.adminToken,
            body = mapOf("active" to false),
        )

        val result = club.reserve("나래", "2026-12-05", 14, 3)

        assertEquals(400, result.status)
        assertEquals("MEMBER_INVALID", result.code)
    }

    @Test
    fun `링크로 그려지는 주소에 javascript 주소는 받지 않는다`() {
        val club = createClub("가람")

        val bookingUrl = call(
            HttpMethod.PATCH, "/admin/rounds/${club.roundId}", club.token, adminToken = club.adminToken,
            body = mapOf("bookingUrl" to "javascript:alert(1)"),
        )
        val courtLink = call(
            HttpMethod.PATCH, "/admin/rounds/${club.roundId}", club.token, adminToken = club.adminToken,
            body = mapOf("courtLinks" to mapOf("3" to "javascript:alert(1)")),
        )

        assertEquals(400, bookingUrl.status)
        assertEquals(400, courtLink.status)
    }

    @Test
    fun `회차에 예약 사이트 주소와 코트별 주소를 넣으면 현황판에 내려온다`() {
        val club = createClub("가람")

        call(
            HttpMethod.PATCH, "/admin/rounds/${club.roundId}", club.token, adminToken = club.adminToken,
            body = mapOf(
                "bookingUrl" to "https://example.org/list",
                "courtLinks" to mapOf("3" to "https://example.org/court/3", "1" to ""),
            ),
        )

        val round = club.board().body["round"]
        assertEquals("https://example.org/list", round["bookingUrl"].asText())
        assertEquals("https://example.org/court/3", round["courtLinks"]["3"].asText())
        assertTrue(round["courtLinks"]["1"] == null)
        assertEquals("2026-11-25T10:00:00+09:00", round["opensAt"].asText())
    }

    @Test
    fun `계획을 다시 저장해도 등록된 예약은 남고 맞는 슬롯에 다시 붙는다`() {
        val club = createClub("가람", "나래")
        club.savePlan(
            club.slot(1, "2026-12-05", 14, 3, "가람"),
            club.slot(2, "2026-12-12", 14, 3, "나래"),
        )
        club.reserve("가람", "2026-12-05", 14, 3)
        club.reserve("나래", "2026-12-12", 14, 3)

        // 1번을 지우고, 2번은 날짜를 옮기고, 12/5 14시를 3번으로 새로 넣는다.
        val result = club.savePlan(
            club.slot(2, "2026-12-13", 14, 3, "나래"),
            club.slot(3, "2026-12-05", 14, null, "가람"),
        )

        assertEquals(mapOf(2 to "PLANNED", 3 to "SECURED"), result.body.statesByNo())
        assertEquals(2, result.body["reservations"].size())
        assertEquals(1, result.body["summary"]["unplanned"].asInt())
    }

    @Test
    fun `같은 번호가 두 번 들어간 계획은 저장하지 않는다`() {
        val club = createClub("가람")

        val result = call(
            HttpMethod.PUT, "/admin/rounds/${club.roundId}/slots", club.token, adminToken = club.adminToken,
            body = listOf(club.slot(1, "2026-12-05", 14, 3, "가람"), club.slot(1, "2026-12-06", 14, 3, "가람")),
        )

        assertEquals(400, result.status)
        assertEquals(0, club.board().body["slots"].size())
    }
}
