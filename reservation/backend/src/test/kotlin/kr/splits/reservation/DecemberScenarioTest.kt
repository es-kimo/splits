package kr.splits.reservation

import org.junit.jupiter.api.Test
import kotlin.test.assertEquals

/**
 * 이 서비스를 만들게 된 실제 예약일의 흐름을 가상 이름으로 옮긴 것.
 *
 * 계획 18건 중 13건을 확보했는데 그중 5건은 배정자가 아닌 사람이 잡았고,
 * 본인은 "실패"라고 알렸지만 다른 사람이 이미 잡은 슬롯이 섞여 있었다.
 * 계획에 없던 예약도 7건 생겼다. 이 상태가 한 화면에서 맞게 집계되는지 본다.
 */
class DecemberScenarioTest : ApiTestSupport() {

    @Test
    fun `계획 18건이 확보 13 마감 3 보고 없음 2 계획 외 7로 집계된다`() {
        val club = createClub("가람", "나래", "다온", "라온", "마루", "바다", "새봄", "아라", "자람", "차미", "하늘")
        club.savePlan(
            club.slot(1, "2026-12-05", 16, 3, "가람"),
            club.slot(2, "2026-12-27", 10, null, "가람"),
            club.slot(3, "2026-12-13", 10, null, "나래"),
            club.slot(4, "2026-12-12", 14, 3, "다온"),
            club.slot(5, "2026-12-13", 14, 3, "라온"),
            club.slot(6, "2026-12-26", 14, 3, "마루"),
            club.slot(7, "2026-12-27", 14, 3, "마루"),
            club.slot(8, "2026-12-19", 14, 3, "바다"),
            club.slot(9, "2026-12-20", 14, 3, "바다"),
            club.slot(10, "2026-12-19", 16, 3, "새봄"),
            club.slot(11, "2026-12-20", 16, 3, "새봄"),
            club.slot(12, "2026-12-26", 16, 3, "아라"),
            club.slot(13, "2026-12-27", 16, 3, "아라"),
            club.slot(14, "2026-12-12", 16, 3, "자람"),
            club.slot(15, "2026-12-13", 16, 3, "자람"),
            club.slot(16, "2026-12-05", 14, 3, "차미"),
            club.slot(17, "2026-12-20", 10, null, "차미"),
            club.slot(18, "2026-12-06", 10, null, "하늘"),
        )

        // 10:02 ~ 10:03
        club.reserve("마루", "2026-12-27", 14, 3, slotNo = 7)
        club.fail("자람", 14, "CLOSED")
        club.fail("다온", 4, "CLOSED") // 본인은 실패했지만 사실은 가람이 잡았다
        club.fail("나래", 3, "CLOSED")
        club.reserve("새봄", "2026-12-19", 16, 3, slotNo = 10)
        club.reserve("새봄", "2026-12-20", 16, 3, slotNo = 11)
        club.reserve("하늘", "2026-12-06", 10, 2, slotNo = 18)

        // 10:04 ~ 10:06
        club.reserve("차미", "2026-12-05", 14, 3, slotNo = 16)
        club.fail("차미", 17, "CLOSED")
        club.reserve("차미", "2026-12-20", 8, 3) // 10~12시를 못 잡아 8~10시로
        club.reserve("바다", "2026-12-26", 14, 3) // 남의 6번을 잡음
        club.reserve("바다", "2026-12-19", 14, 3, slotNo = 8)
        club.reserve("바다", "2026-12-20", 14, 3, slotNo = 9)
        club.fail("아라", 12, "NEED_HELP")
        club.fail("아라", 13, "NEED_HELP")
        club.reserve("새봄", "2026-12-26", 16, 3, slotNo = 12) // 대신 잡아 줌
        club.reserve("가람", "2026-12-05", 16, 3)
        club.reserve("가람", "2026-12-12", 14, 3) // 4번: "마감" 보고가 있었지만 확보로 바뀌어야 한다
        club.reserve("가람", "2026-12-13", 16, 3)
        club.reserve("가람", "2026-12-27", 16, 3)

        // 10:06 ~ 10:10 계획에 없던 예약
        club.reserve("차미", "2026-12-25", 16, 1)
        club.reserve("차미", "2026-12-25", 16, 3)
        listOf("2026-12-03", "2026-12-10", "2026-12-17", "2026-12-24").forEach {
            club.reserve("나래", it, 16, 1)
        }

        val board = club.board().body
        val states = board.statesByNo()

        assertEquals(setOf(1, 4, 6, 7, 8, 9, 10, 11, 12, 13, 15, 16, 18), states.filterValues { it == "SECURED" }.keys)
        assertEquals(setOf(3, 14, 17), states.filterValues { it == "CLOSED" }.keys)
        assertEquals(setOf(2, 5), states.filterValues { it == "PLANNED" }.keys)

        val summary = board["summary"]
        assertEquals(18, summary["total"].asInt())
        assertEquals(13, summary["secured"].asInt())
        assertEquals(3, summary["closed"].asInt())
        assertEquals(2, summary["planned"].asInt())
        assertEquals(0, summary["needHelp"].asInt())
        assertEquals(7, summary["unplanned"].asInt())

        // 확보 13건 중 5건은 배정자가 아닌 사람이 잡았다.
        val bookerBySlot = board["reservations"].filter { !it["slotId"].isNull }.associate { it["slotId"].asLong() to it["bookerMemberId"].asLong() }
        val takenByOthers = board["slots"]
            .filter { it["state"].asText() == "SECURED" }
            .filter { bookerBySlot.getValue(it["id"].asLong()) != it["assigneeMemberId"].asLong() }
            .map { it["slotNo"].asInt() }
        assertEquals(listOf(4, 6, 12, 13, 15), takenByOthers)
    }
}
