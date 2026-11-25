package kr.splits.reservation.club

import kr.splits.reservation.admin.AdminAuthService
import kr.splits.reservation.board.BookingRoundRepository
import kr.splits.reservation.common.BadRequestException
import kr.splits.reservation.common.Kst
import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional
import java.security.SecureRandom
import java.time.Clock
import java.time.LocalDateTime

data class MemberDto(val id: Long, val name: String, val active: Boolean)

data class RoundSummaryDto(val id: Long, val title: String, val opensAt: String)

data class ClubResponse(
    val id: Long,
    val name: String,
    val members: List<MemberDto>,
    val rounds: List<RoundSummaryDto>,
    /** 보관하지 않은 회차 중 예약 오픈이 가장 늦은 것. */
    val currentRoundId: Long?,
    val serverTime: String,
)

data class CreatedClub(val clubId: Long, val accessToken: String)

@Service
class ClubService(
    private val clubs: ClubRepository,
    private val members: ClubMemberRepository,
    private val rounds: BookingRoundRepository,
    private val adminAuthService: AdminAuthService,
    private val clock: Clock,
) {
    private val random = SecureRandom()

    @Transactional(readOnly = true)
    fun describe(club: Club): ClubResponse {
        val activeRounds = rounds.findByClubIdAndArchivedFalseOrderByOpensAtDescIdDesc(club.id)
        return ClubResponse(
            id = club.id,
            name = club.name,
            // 그만둔 사람의 예전 예약도 이름이 보여야 하므로 비활성 멤버까지 내려준다.
            members = members.findByClubIdOrderByNameAsc(club.id).map { MemberDto(it.id, it.name, it.active) },
            rounds = activeRounds.map { RoundSummaryDto(it.id, it.title, Kst.iso(it.opensAt)) },
            currentRoundId = activeRounds.firstOrNull()?.id,
            serverTime = Kst.iso(LocalDateTime.now(clock)),
        )
    }

    @Transactional
    fun create(name: String, adminPin: String): CreatedClub {
        val trimmed = name.trim()
        if (trimmed.isEmpty() || trimmed.length > 60) throw BadRequestException("모임 이름은 1~60자로 적어 주세요.")
        validatePin(adminPin)
        val club = clubs.save(
            Club(
                name = trimmed,
                accessToken = newAccessToken(),
                adminPinHash = adminAuthService.hashPin(adminPin),
                createdAt = LocalDateTime.now(clock),
            ),
        )
        return CreatedClub(club.id, club.accessToken)
    }

    /** 256비트 난수. 링크를 모르면 맞힐 수 없다. */
    private fun newAccessToken(): String {
        val bytes = ByteArray(32)
        random.nextBytes(bytes)
        return bytes.joinToString("") { "%02x".format(it) }
    }

    companion object {
        fun validatePin(pin: String) {
            if (pin.length !in 4..32) throw BadRequestException("PIN은 4자 이상으로 정해 주세요.")
        }
    }
}
