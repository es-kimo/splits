package kr.splits.reservation.club

import kr.splits.reservation.admin.AdminAuthService
import kr.splits.reservation.common.BadRequestException
import kr.splits.reservation.common.UnauthorizedException
import org.springframework.stereotype.Component

/**
 * 요청 헤더에서 "어느 모임의 누구인지"를 풀어낸다.
 *
 * - X-Club-Token: 모임 링크에 들어 있는 값. 모든 요청에 필요하다.
 * - X-Member-Id: 화면에서 고른 이름. 본인 확인이 아니라 기록용이다.
 * - X-Admin-Token: PIN을 넣고 받은 총무 토큰.
 */
@Component
class AccessResolver(
    private val clubRepository: ClubRepository,
    private val memberRepository: ClubMemberRepository,
    private val adminAuthService: AdminAuthService,
) {
    fun club(clubToken: String?): Club =
        clubToken?.takeIf { it.isNotBlank() }?.let(clubRepository::findByAccessToken)
            ?: throw UnauthorizedException(
                "모임 링크가 올바르지 않아요. 카톡방에 올라온 링크로 다시 들어와 주세요.",
                "CLUB_TOKEN_INVALID",
            )

    /** 다른 모임의 멤버 번호를 보내도 통과하지 못하게, 반드시 모임과 함께 확인한다. */
    fun member(club: Club, memberId: Long?): ClubMember {
        val member = memberId?.let { memberRepository.findById(it).orElse(null) }
        if (member == null || member.clubId != club.id || !member.active) {
            throw BadRequestException("이름을 다시 골라 주세요.", "MEMBER_INVALID")
        }
        return member
    }

    fun requireAdmin(club: Club, adminToken: String?) {
        if (!adminAuthService.isValid(club, adminToken)) {
            throw UnauthorizedException("총무 PIN을 다시 입력해 주세요.", "ADMIN_TOKEN_INVALID")
        }
    }

    companion object {
        const val CLUB_TOKEN = "X-Club-Token"
        const val MEMBER_ID = "X-Member-Id"
        const val ADMIN_TOKEN = "X-Admin-Token"
    }
}
