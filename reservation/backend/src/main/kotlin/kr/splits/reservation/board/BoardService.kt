package kr.splits.reservation.board

import com.fasterxml.jackson.databind.ObjectMapper
import com.fasterxml.jackson.module.kotlin.readValue
import kr.splits.reservation.club.Club
import kr.splits.reservation.club.ClubMember
import kr.splits.reservation.club.ClubMemberRepository
import kr.splits.reservation.common.BadRequestException
import kr.splits.reservation.common.ConflictException
import kr.splits.reservation.common.Kst
import kr.splits.reservation.common.NotFoundException
import kr.splits.reservation.log.EventLogRepository
import kr.splits.reservation.log.EventLogger
import org.springframework.dao.DataIntegrityViolationException
import org.springframework.data.domain.PageRequest
import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional
import java.time.Clock
import java.time.LocalDateTime

/**
 * 현황판 조회와, 현황판을 바꾸는 모든 동작.
 *
 * 바꾸는 동작은 전부 [lockRound]로 회차 한 줄을 먼저 잠근다. 10시 정각에 여러 명이 동시에
 * 눌러도 같은 회차 안에서는 한 번에 하나씩 처리되므로, "빈 슬롯인지 보고 붙인다" 같은
 * 읽고-쓰기 판단이 서로 엇갈리지 않는다. DB의 UNIQUE 제약은 그 뒤의 마지막 방어선이다.
 */
@Service
class BoardService(
    private val rounds: BookingRoundRepository,
    private val slots: PlanSlotRepository,
    private val reservations: ReservationRepository,
    private val members: ClubMemberRepository,
    private val events: EventLogRepository,
    private val eventLogger: EventLogger,
    private val objectMapper: ObjectMapper,
    private val clock: Clock,
) {
    @Transactional(readOnly = true)
    fun board(club: Club, roundId: Long): BoardResponse = toBoard(findRound(club, roundId))

    @Transactional(readOnly = true)
    fun version(club: Club, roundId: Long): Long = findRound(club, roundId).boardVersion

    @Transactional(readOnly = true)
    fun events(club: Club, roundId: Long): List<EventDto> {
        val round = findRound(club, roundId)
        return events.findByRoundIdOrderByIdDesc(round.id, PageRequest.of(0, EVENT_PAGE_SIZE)).map {
            EventDto(it.id, it.actorName, it.type, it.detail, Kst.iso(it.createdAt))
        }
    }

    @Transactional
    fun createReservation(club: Club, actor: ClubMember, roundId: Long, request: CreateReservationRequest): BoardResponse {
        val round = lockRound(club, roundId)
        validateHours(request.startHour, request.endHour)
        validateCourt(request.courtNo)
        val booker = findMember(club, request.bookerMemberId)

        val active = activeReservations(round.id)
        active.firstOrNull {
            it.playDate == request.playDate && it.startHour == request.startHour && it.courtNo == request.courtNo
        }?.let { duplicate ->
            throw ConflictException(
                "이미 ${memberName(duplicate.bookerMemberId)}님 예약으로 등록돼 있어요.",
                "RESERVATION_DUPLICATE",
            )
        }

        val fulfilled = active.mapNotNull { it.slotId }.toSet()
        val slot = pickSlot(slots.findByRoundIdOrderBySlotNoAsc(round.id), fulfilled, request)

        val reservation = Reservation(
            roundId = round.id,
            playDate = request.playDate,
            startHour = request.startHour,
            endHour = request.endHour,
            courtNo = request.courtNo,
            bookerMemberId = booker.id,
            reportedByMemberId = actor.id,
            slotId = slot?.id,
            createdAt = now(),
        )
        try {
            reservations.saveAndFlush(reservation)
        } catch (e: DataIntegrityViolationException) {
            throw ConflictException("방금 다른 분이 같은 예약을 등록했어요. 화면을 확인해 주세요.", "RESERVATION_DUPLICATE")
        }
        slot?.clearFail()
        touch(round)

        val label = "${Kst.slotLabel(request.playDate, request.startHour, request.endHour)} ${request.courtNo}코트"
        val target = slot?.let { "${it.slotNo}번" } ?: "계획 외"
        eventLogger.member(actor, round.id, "RESERVATION_CREATED", "예약 등록: $label, 예약자 ${booker.name} ($target)")
        return toBoard(round)
    }

    @Transactional
    fun cancelReservation(club: Club, actor: ClubMember, roundId: Long, reservationId: Long): BoardResponse {
        val round = lockRound(club, roundId)
        val reservation = reservations.findById(reservationId).orElse(null)
            ?.takeIf { it.roundId == round.id }
            ?: throw NotFoundException("예약을 찾을 수 없어요.")
        if (!reservation.isActive) return toBoard(round)

        val label = "${Kst.slotLabel(reservation.playDate, reservation.startHour, reservation.endHour)} ${reservation.courtNo}코트"
        reservation.cancel(actor.id, now())
        // 취소로 비운 슬롯에 다른 예약을 붙이기 전에 먼저 반영해야 UNIQUE(slot_id, active_key)에 걸리지 않는다.
        reservations.saveAndFlush(reservation)
        relink(round.id)
        touch(round)

        eventLogger.member(actor, round.id, "RESERVATION_CANCELLED", "예약 취소: $label, 예약자 ${memberName(reservation.bookerMemberId)}")
        return toBoard(round)
    }

    @Transactional
    fun reportFail(club: Club, actor: ClubMember, roundId: Long, slotId: Long, kind: FailKind): BoardResponse {
        val round = lockRound(club, roundId)
        val slot = findSlot(round, slotId)
        if (activeReservations(round.id).any { it.slotId == slot.id }) {
            throw ConflictException("이미 확보된 시간이에요.", "SLOT_ALREADY_SECURED")
        }
        slot.markFail(kind, actor.id, now())
        touch(round)

        val what = if (kind == FailKind.CLOSED) "마감 확인" else "도움 요청"
        eventLogger.member(actor, round.id, "SLOT_FAILED", "$what: ${slot.slotNo}번 ${slotLabel(slot)}")
        return toBoard(round)
    }

    @Transactional
    fun clearFail(club: Club, actor: ClubMember, roundId: Long, slotId: Long): BoardResponse {
        val round = lockRound(club, roundId)
        val slot = findSlot(round, slotId)
        if (slot.failKind != null) {
            slot.clearFail()
            touch(round)
            eventLogger.member(actor, round.id, "SLOT_FAIL_CLEARED", "보고 되돌림: ${slot.slotNo}번 ${slotLabel(slot)}")
        }
        return toBoard(round)
    }

    @Transactional
    fun setAssignee(club: Club, actor: ClubMember, roundId: Long, slotId: Long, memberId: Long?): BoardResponse {
        val round = lockRound(club, roundId)
        val slot = findSlot(round, slotId)
        val assignee = memberId?.let { findMember(club, it) }
        slot.assigneeMemberId = assignee?.id
        // 누군가 넘겨받았으면 "도움 필요"는 풀린다. 마감 확인은 사실 보고이므로 그대로 둔다.
        if (assignee != null && slot.failKind == FailKind.NEED_HELP) slot.clearFail()
        touch(round)

        eventLogger.member(
            actor, round.id, "SLOT_ASSIGNED",
            "담당 변경: ${slot.slotNo}번 ${slotLabel(slot)} → ${assignee?.name ?: "담당 없음"}",
        )
        return toBoard(round)
    }

    /**
     * 계획 전체를 받은 목록으로 바꾼다. 번호가 같은 슬롯은 고치고, 목록에 없는 번호는 지운다.
     * 이미 등록된 예약은 지우지 않고, 날짜·시간이 맞는 슬롯에 다시 붙인다.
     */
    @Transactional
    fun replacePlan(club: Club, roundId: Long, items: List<PlanItem>): BoardResponse {
        val round = lockRound(club, roundId)
        if (items.size > MAX_SLOTS) throw BadRequestException("슬롯은 한 회차에 ${MAX_SLOTS}개까지 넣을 수 있어요.")
        items.groupBy { it.slotNo }.entries.firstOrNull { it.value.size > 1 }?.let {
            throw BadRequestException("${it.key}번이 두 번 들어 있어요.")
        }
        val clubMemberIds = members.findByClubIdOrderByNameAsc(club.id).map { it.id }.toSet()
        for (item in items) {
            if (item.slotNo < 1) throw BadRequestException("슬롯 번호는 1 이상이어야 해요.")
            validateHours(item.startHour, item.endHour)
            item.courtPref?.let(::validateCourt)
            if (item.assigneeMemberId != null && item.assigneeMemberId !in clubMemberIds) {
                throw BadRequestException("${item.slotNo}번의 담당자를 찾을 수 없어요.")
            }
        }

        val existing = slots.findByRoundIdOrderBySlotNoAsc(round.id).associateBy { it.slotNo }
        val incoming = items.associateBy { it.slotNo }

        // 1) 사라지거나 시간이 바뀌는 슬롯에서 예약을 떼어 낸다. 취소된 예약의 연결도 같이 끊어야 슬롯을 지울 수 있다.
        for ((slotNo, slot) in existing) {
            val next = incoming[slotNo]
            if (next == null || next.playDate != slot.playDate || next.startHour != slot.startHour) {
                reservations.findBySlotId(slot.id).forEach { it.slotId = null }
                slot.clearFail()
            }
        }
        reservations.flush()

        // 2) 지우고, 고치고, 새로 넣는다.
        slots.deleteAll(existing.filterKeys { it !in incoming }.values)
        slots.flush()
        for (item in items) {
            val slot = existing[item.slotNo]
            if (slot == null) {
                slots.save(
                    PlanSlot(
                        roundId = round.id,
                        slotNo = item.slotNo,
                        playDate = item.playDate,
                        startHour = item.startHour,
                        endHour = item.endHour,
                        courtPref = item.courtPref,
                        assigneeMemberId = item.assigneeMemberId,
                    ),
                )
            } else {
                slot.playDate = item.playDate
                slot.startHour = item.startHour
                slot.endHour = item.endHour
                slot.courtPref = item.courtPref
                slot.assigneeMemberId = item.assigneeMemberId
            }
        }
        slots.flush()

        // 3) 떼어 낸 예약과 계획 외 예약을 맞는 슬롯에 다시 붙인다.
        relink(round.id)
        touch(round)
        eventLogger.admin(club.id, round.id, "PLAN_REPLACED", "계획 저장: 슬롯 ${items.size}개")
        return toBoard(round)
    }

    // ---------------------------------------------------------------- 내부

    private fun findRound(club: Club, roundId: Long): BookingRound =
        rounds.findById(roundId).orElse(null)?.takeIf { it.clubId == club.id }
            ?: throw NotFoundException("회차를 찾을 수 없어요.")

    /** 다른 모임의 회차 번호를 넣어도 "없음"으로 답한다. */
    private fun lockRound(club: Club, roundId: Long): BookingRound =
        rounds.findByIdForUpdate(roundId)?.takeIf { it.clubId == club.id }
            ?: throw NotFoundException("회차를 찾을 수 없어요.")

    private fun findSlot(round: BookingRound, slotId: Long): PlanSlot =
        slots.findById(slotId).orElse(null)?.takeIf { it.roundId == round.id }
            ?: throw NotFoundException("슬롯을 찾을 수 없어요.")

    private fun findMember(club: Club, memberId: Long): ClubMember =
        members.findById(memberId).orElse(null)?.takeIf { it.clubId == club.id && it.active }
            ?: throw BadRequestException("모임원을 찾을 수 없어요.", "MEMBER_INVALID")

    private fun memberName(memberId: Long): String =
        members.findById(memberId).map { it.name }.orElse("알 수 없음")

    private fun activeReservations(roundId: Long): List<Reservation> =
        reservations.findByRoundIdAndActiveKeyOrderByPlayDateAscStartHourAscCourtNoAsc(roundId, Reservation.ACTIVE)

    private fun pickSlot(all: List<PlanSlot>, fulfilled: Set<Long>, request: CreateReservationRequest): PlanSlot? {
        if (request.slotId != null) {
            val slot = all.firstOrNull { it.id == request.slotId } ?: throw NotFoundException("슬롯을 찾을 수 없어요.")
            if (slot.playDate != request.playDate || slot.startHour != request.startHour) {
                throw BadRequestException("이 슬롯과 날짜·시간이 달라요. '계획에 없는 예약'으로 등록해 주세요.")
            }
            // 이미 다른 예약으로 채워진 슬롯이면 계획 외 예약으로 남긴다(같은 시간에 코트를 둘 잡은 경우).
            return slot.takeIf { it.id !in fulfilled }
        }
        return all
            .filter { it.id !in fulfilled && it.playDate == request.playDate && it.startHour == request.startHour }
            .minWithOrNull(compareBy<PlanSlot>({ courtRank(it, request.courtNo) }, { it.slotNo }))
    }

    /** 빈 슬롯마다 날짜·시간이 맞는 계획 외 예약을 찾아 붙인다. */
    private fun relink(roundId: Long) {
        val active = activeReservations(roundId)
        val fulfilled = active.mapNotNull { it.slotId }.toMutableSet()
        val unlinked = active.filter { it.slotId == null }.toMutableList()
        for (slot in slots.findByRoundIdOrderBySlotNoAsc(roundId)) {
            if (slot.id in fulfilled) continue
            val match = unlinked
                .filter { it.playDate == slot.playDate && it.startHour == slot.startHour }
                .minWithOrNull(compareBy<Reservation>({ courtRank(slot, it.courtNo) }, { it.createdAt }))
                ?: continue
            match.slotId = slot.id
            slot.clearFail()
            unlinked.remove(match)
            fulfilled.add(slot.id)
        }
        reservations.flush()
    }

    /** 계획한 코트와 같으면 0, 아무 코트 계획이면 1, 다른 코트면 2. 작을수록 먼저 붙인다. */
    private fun courtRank(slot: PlanSlot, courtNo: Int): Int = when (slot.courtPref) {
        courtNo -> 0
        null -> 1
        else -> 2
    }

    private fun touch(round: BookingRound) {
        round.boardVersion += 1
    }

    private fun toBoard(round: BookingRound): BoardResponse {
        val active = activeReservations(round.id)
        val bySlot = active.filter { it.slotId != null }.associateBy { it.slotId }
        val slotDtos = slots.findByRoundIdOrderBySlotNoAsc(round.id).map { slot ->
            val reservation = bySlot[slot.id]
            val state = when {
                reservation != null -> SlotState.SECURED
                slot.failKind == FailKind.CLOSED -> SlotState.CLOSED
                slot.failKind == FailKind.NEED_HELP -> SlotState.NEED_HELP
                else -> SlotState.PLANNED
            }
            SlotDto(
                id = slot.id,
                slotNo = slot.slotNo,
                playDate = slot.playDate,
                startHour = slot.startHour,
                endHour = slot.endHour,
                courtPref = slot.courtPref,
                assigneeMemberId = slot.assigneeMemberId,
                state = state,
                failMemberId = slot.failMemberId,
                reservationId = reservation?.id,
            )
        }
        val summary = SummaryDto(
            total = slotDtos.size,
            secured = slotDtos.count { it.state == SlotState.SECURED },
            needHelp = slotDtos.count { it.state == SlotState.NEED_HELP },
            closed = slotDtos.count { it.state == SlotState.CLOSED },
            planned = slotDtos.count { it.state == SlotState.PLANNED },
            unplanned = active.count { it.slotId == null },
        )
        return BoardResponse(
            round = toRoundDto(round),
            slots = slotDtos,
            reservations = active.map {
                ReservationDto(
                    id = it.id,
                    playDate = it.playDate,
                    startHour = it.startHour,
                    endHour = it.endHour,
                    courtNo = it.courtNo,
                    bookerMemberId = it.bookerMemberId,
                    reportedByMemberId = it.reportedByMemberId,
                    slotId = it.slotId,
                    createdAt = Kst.iso(it.createdAt),
                )
            },
            summary = summary,
            serverTime = Kst.iso(now()),
        )
    }

    fun toRoundDto(round: BookingRound): RoundDto = RoundDto(
        id = round.id,
        title = round.title,
        opensAt = Kst.iso(round.opensAt),
        bookingUrl = round.bookingUrl,
        courtLinks = round.courtLinks?.let { objectMapper.readValue<Map<String, String>>(it) } ?: emptyMap(),
        version = round.boardVersion,
        archived = round.archived,
    )

    private fun slotLabel(slot: PlanSlot): String = Kst.slotLabel(slot.playDate, slot.startHour, slot.endHour)

    private fun now(): LocalDateTime = LocalDateTime.now(clock)

    companion object {
        const val MAX_COURT = 20
        private const val MAX_SLOTS = 200
        private const val EVENT_PAGE_SIZE = 100

        fun validateHours(startHour: Int, endHour: Int) {
            if (startHour !in 0..23 || endHour !in 1..24 || startHour >= endHour) {
                throw BadRequestException("시간이 올바르지 않아요.")
            }
        }

        fun validateCourt(courtNo: Int) {
            if (courtNo !in 1..MAX_COURT) throw BadRequestException("코트 번호가 올바르지 않아요.")
        }
    }
}
