package kr.splits.reservation

import com.fasterxml.jackson.databind.JsonNode
import com.fasterxml.jackson.databind.ObjectMapper
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.http.HttpMethod
import org.springframework.http.MediaType
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.servlet.request.MockMvcRequestBuilders
import java.util.concurrent.atomic.AtomicInteger

data class ApiResult(val status: Int, val body: JsonNode) {
    val message: String get() = body.path("message").asText()
    val code: String get() = body.path("code").asText()
}

/** 테스트마다 새로 만드는 모임. 이름은 모두 가상이다. */
data class TestClub(
    val token: String,
    val adminToken: String,
    val members: Map<String, Long>,
    val roundId: Long,
) {
    fun id(name: String): Long = members.getValue(name)
}

@SpringBootTest
@AutoConfigureMockMvc
abstract class ApiTestSupport {

    @Autowired
    protected lateinit var mockMvc: MockMvc

    @Autowired
    protected lateinit var objectMapper: ObjectMapper

    protected fun call(
        method: HttpMethod,
        path: String,
        clubToken: String? = null,
        memberId: Long? = null,
        adminToken: String? = null,
        body: Any? = null,
        extraHeaders: Map<String, String> = emptyMap(),
    ): ApiResult {
        val request = MockMvcRequestBuilders.request(method, "/api/v1$path")
        clubToken?.let { request.header("X-Club-Token", it) }
        memberId?.let { request.header("X-Member-Id", it.toString()) }
        adminToken?.let { request.header("X-Admin-Token", it) }
        extraHeaders.forEach { (name, value) -> request.header(name, value) }
        if (body != null) {
            request.contentType(MediaType.APPLICATION_JSON).content(objectMapper.writeValueAsString(body))
        }
        val response = mockMvc.perform(request).andReturn().response
        val text = response.getContentAsString(Charsets.UTF_8)
        return ApiResult(response.status, if (text.isBlank()) objectMapper.createObjectNode() else objectMapper.readTree(text))
    }

    protected fun createClub(vararg memberNames: String, pin: String = TEST_PIN): TestClub {
        val created = call(
            HttpMethod.POST, "/bootstrap/clubs",
            body = mapOf("name" to "테스트 모임 ${sequence.incrementAndGet()}", "adminPin" to pin),
            extraHeaders = mapOf("X-Bootstrap-Secret" to "test-bootstrap"),
        )
        check(created.status == 201) { "모임 생성 실패: ${created.body}" }
        val token = created.body["accessToken"].asText()

        val login = call(HttpMethod.POST, "/admin/login", clubToken = token, body = mapOf("pin" to pin))
        check(login.status == 200) { "총무 로그인 실패: ${login.body}" }
        val adminToken = login.body["token"].asText()

        val members = memberNames.associateWith { name ->
            val added = call(HttpMethod.POST, "/admin/members", token, adminToken = adminToken, body = mapOf("name" to name))
            check(added.status == 201) { "모임원 추가 실패: ${added.body}" }
            added.body["id"].asLong()
        }

        val round = call(
            HttpMethod.POST, "/admin/rounds", token, adminToken = adminToken,
            body = mapOf("title" to "12월 예약", "opensAt" to "2026-11-25T10:00"),
        )
        check(round.status == 201) { "회차 생성 실패: ${round.body}" }
        return TestClub(token, adminToken, members, round.body["id"].asLong())
    }

    /** 계획 한 줄. 담당자는 이름으로 적는다. */
    protected fun TestClub.slot(no: Int, date: String, start: Int, court: Int?, assignee: String?): Map<String, Any?> = mapOf(
        "slotNo" to no,
        "playDate" to date,
        "startHour" to start,
        "endHour" to start + 2,
        "courtPref" to court,
        "assigneeMemberId" to assignee?.let(::id),
    )

    protected fun TestClub.savePlan(vararg slots: Map<String, Any?>): ApiResult =
        call(HttpMethod.PUT, "/admin/rounds/$roundId/slots", token, adminToken = adminToken, body = slots.toList())
            .also { check(it.status == 200) { "계획 저장 실패: ${it.body}" } }

    protected fun TestClub.board(since: Long? = null): ApiResult =
        call(HttpMethod.GET, "/rounds/$roundId/board${since?.let { "?since=$it" } ?: ""}", token)

    /** [actor]가 화면에 입력한다. [booker]를 따로 주면 대신 입력한 것이다. */
    protected fun TestClub.reserve(
        actor: String,
        date: String,
        start: Int,
        court: Int,
        slotNo: Int? = null,
        booker: String = actor,
    ): ApiResult {
        val slotId = slotNo?.let { no -> board().body["slots"].first { it["slotNo"].asInt() == no }["id"].asLong() }
        return call(
            HttpMethod.POST, "/rounds/$roundId/reservations", token, memberId = id(actor),
            body = mapOf(
                "slotId" to slotId,
                "playDate" to date,
                "startHour" to start,
                "endHour" to start + 2,
                "courtNo" to court,
                "bookerMemberId" to id(booker),
            ),
        )
    }

    protected fun TestClub.fail(actor: String, slotNo: Int, kind: String): ApiResult {
        val slotId = board().body["slots"].first { it["slotNo"].asInt() == slotNo }["id"].asLong()
        return call(
            HttpMethod.POST, "/rounds/$roundId/slots/$slotId/fail", token, memberId = id(actor),
            body = mapOf("kind" to kind),
        )
    }

    protected fun JsonNode.slotByNo(no: Int): JsonNode = this["slots"].first { it["slotNo"].asInt() == no }

    protected fun JsonNode.statesByNo(): Map<Int, String> =
        this["slots"].associate { it["slotNo"].asInt() to it["state"].asText() }

    companion object {
        const val TEST_PIN = "2468"
        private val sequence = AtomicInteger()
    }
}
