package kr.splits.reservation.board

import java.time.LocalDate

enum class SlotState {
    /** 아직 아무 보고도 없다. */
    PLANNED,

    /** 누군가 이 시간을 잡았다. */
    SECURED,

    /** 맡은 사람이 못 한다고 알렸다. */
    NEED_HELP,

    /** 마감된 걸 확인했다. */
    CLOSED,
}

data class RoundDto(
    val id: Long,
    val title: String,
    val opensAt: String,
    val bookingUrl: String?,
    val courtLinks: Map<String, String>,
    val version: Long,
    val archived: Boolean,
)

data class SlotDto(
    val id: Long,
    val slotNo: Int,
    val playDate: LocalDate,
    val startHour: Int,
    val endHour: Int,
    val courtPref: Int?,
    val assigneeMemberId: Long?,
    val state: SlotState,
    val failMemberId: Long?,
    val reservationId: Long?,
)

data class ReservationDto(
    val id: Long,
    val playDate: LocalDate,
    val startHour: Int,
    val endHour: Int,
    val courtNo: Int,
    val bookerMemberId: Long,
    val reportedByMemberId: Long,
    val slotId: Long?,
    val createdAt: String,
)

data class SummaryDto(
    val total: Int,
    val secured: Int,
    val needHelp: Int,
    val closed: Int,
    val planned: Int,
    /** 계획에 없던 예약 건수. */
    val unplanned: Int,
)

data class BoardResponse(
    val round: RoundDto,
    val slots: List<SlotDto>,
    val reservations: List<ReservationDto>,
    val summary: SummaryDto,
    val serverTime: String,
)

data class EventDto(
    val id: Long,
    val actorName: String,
    val type: String,
    val detail: String,
    val createdAt: String,
)

data class CreateReservationRequest(
    /** 슬롯 카드에서 보고하면 채워진다. 비우면 날짜·시간이 맞는 빈 슬롯을 찾아 붙인다. */
    val slotId: Long? = null,
    val playDate: LocalDate,
    val startHour: Int,
    val endHour: Int,
    val courtNo: Int,
    val bookerMemberId: Long,
)

data class FailRequest(val kind: FailKind)

data class AssigneeRequest(val memberId: Long?)

data class PlanItem(
    val slotNo: Int,
    val playDate: LocalDate,
    val startHour: Int,
    val endHour: Int,
    val courtPref: Int? = null,
    val assigneeMemberId: Long? = null,
)
