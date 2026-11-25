package kr.splits.reservation.admin

import kr.splits.reservation.board.BoardResponse
import kr.splits.reservation.board.BoardService
import kr.splits.reservation.board.PlanItem
import kr.splits.reservation.board.RoundDto
import kr.splits.reservation.club.AccessResolver
import kr.splits.reservation.club.ClubService
import kr.splits.reservation.club.CreatedClub
import kr.splits.reservation.club.MemberDto
import kr.splits.reservation.common.NotFoundException
import org.springframework.beans.factory.annotation.Value
import org.springframework.http.HttpStatus
import org.springframework.web.bind.annotation.PatchMapping
import org.springframework.web.bind.annotation.PathVariable
import org.springframework.web.bind.annotation.PostMapping
import org.springframework.web.bind.annotation.PutMapping
import org.springframework.web.bind.annotation.RequestBody
import org.springframework.web.bind.annotation.RequestHeader
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.ResponseStatus
import org.springframework.web.bind.annotation.RestController
import java.security.MessageDigest

data class LoginRequest(val pin: String)

data class LoginResponse(val token: String, val expiresAt: String)

@RestController
@RequestMapping("/api/v1/admin")
class AdminController(
    private val access: AccessResolver,
    private val adminAuthService: AdminAuthService,
    private val adminService: AdminService,
    private val boardService: BoardService,
) {
    @PostMapping("/login")
    fun login(
        @RequestHeader(AccessResolver.CLUB_TOKEN, required = false) clubToken: String?,
        @RequestBody request: LoginRequest,
    ): LoginResponse {
        val token = adminAuthService.login(access.club(clubToken), request.pin)
        return LoginResponse(token.token, token.expiresAt.toString())
    }

    @PostMapping("/members")
    @ResponseStatus(HttpStatus.CREATED)
    fun addMember(
        @RequestHeader(AccessResolver.CLUB_TOKEN, required = false) clubToken: String?,
        @RequestHeader(AccessResolver.ADMIN_TOKEN, required = false) adminToken: String?,
        @RequestBody request: MemberRequest,
    ): MemberDto {
        val club = access.club(clubToken)
        access.requireAdmin(club, adminToken)
        return adminService.addMember(club, request)
    }

    @PatchMapping("/members/{memberId}")
    fun updateMember(
        @RequestHeader(AccessResolver.CLUB_TOKEN, required = false) clubToken: String?,
        @RequestHeader(AccessResolver.ADMIN_TOKEN, required = false) adminToken: String?,
        @PathVariable memberId: Long,
        @RequestBody request: MemberRequest,
    ): MemberDto {
        val club = access.club(clubToken)
        access.requireAdmin(club, adminToken)
        return adminService.updateMember(club, memberId, request)
    }

    @PostMapping("/rounds")
    @ResponseStatus(HttpStatus.CREATED)
    fun createRound(
        @RequestHeader(AccessResolver.CLUB_TOKEN, required = false) clubToken: String?,
        @RequestHeader(AccessResolver.ADMIN_TOKEN, required = false) adminToken: String?,
        @RequestBody request: RoundRequest,
    ): RoundDto {
        val club = access.club(clubToken)
        access.requireAdmin(club, adminToken)
        return adminService.createRound(club, request)
    }

    @PatchMapping("/rounds/{roundId}")
    fun updateRound(
        @RequestHeader(AccessResolver.CLUB_TOKEN, required = false) clubToken: String?,
        @RequestHeader(AccessResolver.ADMIN_TOKEN, required = false) adminToken: String?,
        @PathVariable roundId: Long,
        @RequestBody request: RoundRequest,
    ): RoundDto {
        val club = access.club(clubToken)
        access.requireAdmin(club, adminToken)
        return adminService.updateRound(club, roundId, request)
    }

    @PutMapping("/rounds/{roundId}/slots")
    fun replacePlan(
        @RequestHeader(AccessResolver.CLUB_TOKEN, required = false) clubToken: String?,
        @RequestHeader(AccessResolver.ADMIN_TOKEN, required = false) adminToken: String?,
        @PathVariable roundId: Long,
        @RequestBody items: List<PlanItem>,
    ): BoardResponse {
        val club = access.club(clubToken)
        access.requireAdmin(club, adminToken)
        return boardService.replacePlan(club, roundId, items)
    }
}

data class CreateClubRequest(val name: String, val adminPin: String)

/**
 * 모임을 처음 만드는 통로. 가입 화면이 없으므로 운영자가 비밀값을 들고 한 번 호출한다.
 * 비밀값을 설정하지 않은 환경에서는 경로 자체가 없는 것처럼 404로 답한다.
 */
@RestController
@RequestMapping("/api/v1/bootstrap")
class BootstrapController(
    @Value("\${reservation.bootstrap-secret:}") private val bootstrapSecret: String,
    private val clubService: ClubService,
) {
    @PostMapping("/clubs")
    @ResponseStatus(HttpStatus.CREATED)
    fun createClub(
        @RequestHeader("X-Bootstrap-Secret", required = false) secret: String?,
        @RequestBody request: CreateClubRequest,
    ): CreatedClub {
        val matches = bootstrapSecret.isNotBlank() && secret != null &&
            MessageDigest.isEqual(bootstrapSecret.toByteArray(), secret.toByteArray())
        if (!matches) throw NotFoundException("찾을 수 없어요.")
        return clubService.create(request.name, request.adminPin)
    }
}
