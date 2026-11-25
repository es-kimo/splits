package kr.splits.reservation.admin

import com.fasterxml.jackson.databind.ObjectMapper
import kr.splits.reservation.board.BoardService
import kr.splits.reservation.board.BookingRound
import kr.splits.reservation.board.BookingRoundRepository
import kr.splits.reservation.board.RoundDto
import kr.splits.reservation.club.Club
import kr.splits.reservation.club.ClubMember
import kr.splits.reservation.club.ClubMemberRepository
import kr.splits.reservation.club.MemberDto
import kr.splits.reservation.common.BadRequestException
import kr.splits.reservation.common.ConflictException
import kr.splits.reservation.common.NotFoundException
import kr.splits.reservation.log.EventLogger
import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional
import java.time.Clock
import java.time.LocalDateTime

data class MemberRequest(val name: String? = null, val active: Boolean? = null)

data class RoundRequest(
    val title: String? = null,
    /** 한국 시간. 예: 2026-11-25T10:00 */
    val opensAt: LocalDateTime? = null,
    val bookingUrl: String? = null,
    /** 코트 번호 → 예약 페이지 주소 */
    val courtLinks: Map<String, String>? = null,
    val archived: Boolean? = null,
)

@Service
class AdminService(
    private val members: ClubMemberRepository,
    private val rounds: BookingRoundRepository,
    private val boardService: BoardService,
    private val eventLogger: EventLogger,
    private val objectMapper: ObjectMapper,
    private val clock: Clock,
) {
    @Transactional
    fun addMember(club: Club, request: MemberRequest): MemberDto {
        val name = cleanName(request.name)
        if (members.findByClubIdAndName(club.id, name) != null) {
            throw ConflictException("${name}님은 이미 있어요.", "MEMBER_DUPLICATE")
        }
        val member = members.save(ClubMember(club.id, name, active = true, createdAt = now()))
        eventLogger.admin(club.id, null, "MEMBER_ADDED", "모임원 추가: $name")
        return MemberDto(member.id, member.name, member.active)
    }

    @Transactional
    fun updateMember(club: Club, memberId: Long, request: MemberRequest): MemberDto {
        val member = members.findById(memberId).orElse(null)?.takeIf { it.clubId == club.id }
            ?: throw NotFoundException("모임원을 찾을 수 없어요.")
        request.name?.let {
            val name = cleanName(it)
            val sameName = members.findByClubIdAndName(club.id, name)
            if (sameName != null && sameName.id != member.id) {
                throw ConflictException("${name}님은 이미 있어요.", "MEMBER_DUPLICATE")
            }
            member.name = name
        }
        request.active?.let { member.active = it }
        eventLogger.admin(club.id, null, "MEMBER_UPDATED", "모임원 수정: ${member.name}${if (member.active) "" else " (비활성)"}")
        return MemberDto(member.id, member.name, member.active)
    }

    @Transactional
    fun createRound(club: Club, request: RoundRequest): RoundDto {
        val round = rounds.save(
            BookingRound(
                clubId = club.id,
                title = cleanTitle(request.title),
                opensAt = request.opensAt ?: throw BadRequestException("예약 오픈 일시를 넣어 주세요."),
                bookingUrl = cleanUrl(request.bookingUrl),
                courtLinks = encodeCourtLinks(request.courtLinks),
                createdAt = now(),
            ),
        )
        eventLogger.admin(club.id, round.id, "ROUND_CREATED", "회차 생성: ${round.title}")
        return boardService.toRoundDto(round)
    }

    @Transactional
    fun updateRound(club: Club, roundId: Long, request: RoundRequest): RoundDto {
        val round = rounds.findByIdForUpdate(roundId)?.takeIf { it.clubId == club.id }
            ?: throw NotFoundException("회차를 찾을 수 없어요.")
        request.title?.let { round.title = cleanTitle(it) }
        request.opensAt?.let { round.opensAt = it }
        // 주소는 빈 문자열을 보내면 지운다. 필드를 아예 보내지 않으면 그대로 둔다.
        request.bookingUrl?.let { round.bookingUrl = cleanUrl(it) }
        request.courtLinks?.let { round.courtLinks = encodeCourtLinks(it) }
        request.archived?.let { round.archived = it }
        round.boardVersion += 1
        eventLogger.admin(club.id, round.id, "ROUND_UPDATED", "회차 수정: ${round.title}")
        return boardService.toRoundDto(round)
    }

    private fun cleanName(raw: String?): String {
        val name = raw?.trim().orEmpty()
        if (name.isEmpty() || name.length > 40) throw BadRequestException("이름은 1~40자로 적어 주세요.")
        return name
    }

    private fun cleanTitle(raw: String?): String {
        val title = raw?.trim().orEmpty()
        if (title.isEmpty() || title.length > 80) throw BadRequestException("회차 이름은 1~80자로 적어 주세요.")
        return title
    }

    /**
     * 화면에서 링크로 그려지는 값이라 http(s) 주소만 받는다.
     * `javascript:` 같은 주소가 저장되면 누르는 사람의 브라우저에서 스크립트가 돈다.
     */
    private fun cleanUrl(raw: String?): String? {
        val url = raw?.trim().orEmpty()
        if (url.isEmpty()) return null
        if (url.length > 500 || !(url.startsWith("https://") || url.startsWith("http://"))) {
            throw BadRequestException("주소는 https:// 로 시작하는 500자 이하로 넣어 주세요.")
        }
        return url
    }

    private fun encodeCourtLinks(raw: Map<String, String>?): String? {
        val cleaned = raw.orEmpty()
            .mapNotNull { (court, url) ->
                val courtNo = court.trim().toIntOrNull() ?: throw BadRequestException("코트 번호가 올바르지 않아요.")
                BoardService.validateCourt(courtNo)
                cleanUrl(url)?.let { courtNo.toString() to it }
            }
            .toMap()
        if (cleaned.isEmpty()) return null
        return objectMapper.writeValueAsString(cleaned).also {
            if (it.length > 2000) throw BadRequestException("코트 주소가 너무 길어요.")
        }
    }

    private fun now(): LocalDateTime = LocalDateTime.now(clock)
}
