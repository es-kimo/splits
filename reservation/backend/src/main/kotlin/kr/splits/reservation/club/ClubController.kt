package kr.splits.reservation.club

import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.RequestHeader
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RestController

@RestController
@RequestMapping("/api/v1")
class ClubController(
    private val access: AccessResolver,
    private val clubService: ClubService,
) {
    @GetMapping("/health")
    fun health(): Map<String, String> = mapOf("status" to "ok")

    /** 모임 링크를 가진 사람에게만 모임 이름과 이름 목록을 준다. */
    @GetMapping("/club")
    fun club(@RequestHeader(AccessResolver.CLUB_TOKEN, required = false) clubToken: String?): ClubResponse =
        clubService.describe(access.club(clubToken))
}
