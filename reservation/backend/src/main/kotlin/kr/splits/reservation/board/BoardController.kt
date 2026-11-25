package kr.splits.reservation.board

import kr.splits.reservation.club.AccessResolver
import org.springframework.http.ResponseEntity
import org.springframework.web.bind.annotation.DeleteMapping
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.PathVariable
import org.springframework.web.bind.annotation.PostMapping
import org.springframework.web.bind.annotation.PutMapping
import org.springframework.web.bind.annotation.RequestBody
import org.springframework.web.bind.annotation.RequestHeader
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RequestParam
import org.springframework.web.bind.annotation.RestController

@RestController
@RequestMapping("/api/v1/rounds/{roundId}")
class BoardController(
    private val access: AccessResolver,
    private val boardService: BoardService,
) {
    /**
     * 화면이 2~3초마다 부른다. 마지막으로 본 버전을 `since`로 보내고, 바뀐 게 없으면 본문 없이 204를 받는다.
     * HTTP ETag 대신 쿼리 파라미터를 쓰는 이유: 중간 프록시가 ETag를 약한 형식으로 바꿔도 영향이 없다.
     */
    @GetMapping("/board")
    fun board(
        @RequestHeader(AccessResolver.CLUB_TOKEN, required = false) clubToken: String?,
        @PathVariable roundId: Long,
        @RequestParam(required = false) since: Long?,
    ): ResponseEntity<BoardResponse> {
        val club = access.club(clubToken)
        if (since != null && boardService.version(club, roundId) == since) {
            return ResponseEntity.noContent().build()
        }
        return ResponseEntity.ok(boardService.board(club, roundId))
    }

    @GetMapping("/events")
    fun events(
        @RequestHeader(AccessResolver.CLUB_TOKEN, required = false) clubToken: String?,
        @PathVariable roundId: Long,
    ): List<EventDto> = boardService.events(access.club(clubToken), roundId)

    @PostMapping("/reservations")
    fun createReservation(
        @RequestHeader(AccessResolver.CLUB_TOKEN, required = false) clubToken: String?,
        @RequestHeader(AccessResolver.MEMBER_ID, required = false) memberId: Long?,
        @PathVariable roundId: Long,
        @RequestBody request: CreateReservationRequest,
    ): BoardResponse {
        val club = access.club(clubToken)
        return boardService.createReservation(club, access.member(club, memberId), roundId, request)
    }

    @DeleteMapping("/reservations/{reservationId}")
    fun cancelReservation(
        @RequestHeader(AccessResolver.CLUB_TOKEN, required = false) clubToken: String?,
        @RequestHeader(AccessResolver.MEMBER_ID, required = false) memberId: Long?,
        @PathVariable roundId: Long,
        @PathVariable reservationId: Long,
    ): BoardResponse {
        val club = access.club(clubToken)
        return boardService.cancelReservation(club, access.member(club, memberId), roundId, reservationId)
    }

    @PostMapping("/slots/{slotId}/fail")
    fun reportFail(
        @RequestHeader(AccessResolver.CLUB_TOKEN, required = false) clubToken: String?,
        @RequestHeader(AccessResolver.MEMBER_ID, required = false) memberId: Long?,
        @PathVariable roundId: Long,
        @PathVariable slotId: Long,
        @RequestBody request: FailRequest,
    ): BoardResponse {
        val club = access.club(clubToken)
        return boardService.reportFail(club, access.member(club, memberId), roundId, slotId, request.kind)
    }

    @DeleteMapping("/slots/{slotId}/fail")
    fun clearFail(
        @RequestHeader(AccessResolver.CLUB_TOKEN, required = false) clubToken: String?,
        @RequestHeader(AccessResolver.MEMBER_ID, required = false) memberId: Long?,
        @PathVariable roundId: Long,
        @PathVariable slotId: Long,
    ): BoardResponse {
        val club = access.club(clubToken)
        return boardService.clearFail(club, access.member(club, memberId), roundId, slotId)
    }

    @PutMapping("/slots/{slotId}/assignee")
    fun setAssignee(
        @RequestHeader(AccessResolver.CLUB_TOKEN, required = false) clubToken: String?,
        @RequestHeader(AccessResolver.MEMBER_ID, required = false) memberId: Long?,
        @PathVariable roundId: Long,
        @PathVariable slotId: Long,
        @RequestBody request: AssigneeRequest,
    ): BoardResponse {
        val club = access.club(clubToken)
        return boardService.setAssignee(club, access.member(club, memberId), roundId, slotId, request.memberId)
    }
}
