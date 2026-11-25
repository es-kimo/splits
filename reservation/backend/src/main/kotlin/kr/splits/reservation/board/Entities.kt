package kr.splits.reservation.board

import jakarta.persistence.Column
import jakarta.persistence.Entity
import jakarta.persistence.GeneratedValue
import jakarta.persistence.GenerationType
import jakarta.persistence.Id
import jakarta.persistence.LockModeType
import jakarta.persistence.Table
import org.springframework.data.jpa.repository.JpaRepository
import org.springframework.data.jpa.repository.Lock
import org.springframework.data.jpa.repository.Query
import org.springframework.data.repository.query.Param
import java.time.LocalDate
import java.time.LocalDateTime

@Entity
@Table(name = "booking_round")
class BookingRound(
    @Column(name = "club_id", nullable = false)
    var clubId: Long,

    @Column(nullable = false)
    var title: String,

    /** 예약 사이트가 열리는 시각(한국 시간). */
    @Column(name = "opens_at", nullable = false)
    var opensAt: LocalDateTime,

    @Column(name = "booking_url")
    var bookingUrl: String? = null,

    /** 코트 번호 → 예약 페이지 주소. JSON 문자열로 둔다. */
    @Column(name = "court_links")
    var courtLinks: String? = null,

    @Column(name = "board_version", nullable = false)
    var boardVersion: Long = 1,

    @Column(nullable = false)
    var archived: Boolean = false,

    @Column(name = "created_at", nullable = false)
    var createdAt: LocalDateTime,

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    var id: Long = 0,
)

enum class FailKind {
    /** 맡은 사람이 못 한다. 아직 잡을 수 있을지도 모른다. */
    NEED_HELP,

    /** 마감된 걸 확인했다. */
    CLOSED,
}

@Entity
@Table(name = "plan_slot")
class PlanSlot(
    @Column(name = "round_id", nullable = false)
    var roundId: Long,

    @Column(name = "slot_no", nullable = false)
    var slotNo: Int,

    @Column(name = "play_date", nullable = false)
    var playDate: LocalDate,

    @Column(name = "start_hour", nullable = false)
    var startHour: Int,

    @Column(name = "end_hour", nullable = false)
    var endHour: Int,

    /** null이면 아무 코트. */
    @Column(name = "court_pref")
    var courtPref: Int? = null,

    @Column(name = "assignee_member_id")
    var assigneeMemberId: Long? = null,

    // Hibernate 6은 MySQL에서 enum을 네이티브 ENUM으로 기대해 VARCHAR 컬럼 검증이 어긋난다.
    // 문자열로 저장하고 코드에서 FailKind로 바꿔 쓴다.
    @Column(name = "fail_kind")
    var failKindCode: String? = null,

    @Column(name = "fail_member_id")
    var failMemberId: Long? = null,

    @Column(name = "fail_at")
    var failAt: LocalDateTime? = null,

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    var id: Long = 0,
) {
    val failKind: FailKind?
        get() = failKindCode?.let(FailKind::valueOf)

    fun markFail(kind: FailKind, memberId: Long, at: LocalDateTime) {
        failKindCode = kind.name
        failMemberId = memberId
        failAt = at
    }

    fun clearFail() {
        failKindCode = null
        failMemberId = null
        failAt = null
    }
}

@Entity
@Table(name = "reservation")
class Reservation(
    @Column(name = "round_id", nullable = false)
    var roundId: Long,

    @Column(name = "play_date", nullable = false)
    var playDate: LocalDate,

    @Column(name = "start_hour", nullable = false)
    var startHour: Int,

    @Column(name = "end_hour", nullable = false)
    var endHour: Int,

    @Column(name = "court_no", nullable = false)
    var courtNo: Int,

    /** 예약 사이트에서 실제로 예약한 사람. */
    @Column(name = "booker_member_id", nullable = false)
    var bookerMemberId: Long,

    /** 이 화면에 입력한 사람. 대신 입력했으면 예약자와 다르다. */
    @Column(name = "reported_by_member_id", nullable = false)
    var reportedByMemberId: Long,

    @Column(name = "slot_id")
    var slotId: Long? = null,

    /** 살아 있으면 1, 취소되면 null. */
    @Column(name = "active_key")
    var activeKey: Int? = ACTIVE,

    @Column(name = "created_at", nullable = false)
    var createdAt: LocalDateTime,

    @Column(name = "cancelled_at")
    var cancelledAt: LocalDateTime? = null,

    @Column(name = "cancelled_by_member_id")
    var cancelledByMemberId: Long? = null,

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    var id: Long = 0,
) {
    val isActive: Boolean
        get() = activeKey == ACTIVE

    fun cancel(memberId: Long, at: LocalDateTime) {
        activeKey = null
        slotId = null
        cancelledAt = at
        cancelledByMemberId = memberId
    }

    companion object {
        const val ACTIVE = 1
    }
}

interface BookingRoundRepository : JpaRepository<BookingRound, Long> {
    fun findByClubIdAndArchivedFalseOrderByOpensAtDescIdDesc(clubId: Long): List<BookingRound>

    /**
     * 회차 한 줄을 잠근다. 현황판을 바꾸는 요청은 모두 이 잠금을 먼저 잡으므로,
     * 같은 회차의 변경은 한 번에 하나씩만 진행된다.
     */
    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select r from BookingRound r where r.id = :id")
    fun findByIdForUpdate(@Param("id") id: Long): BookingRound?
}

interface PlanSlotRepository : JpaRepository<PlanSlot, Long> {
    fun findByRoundIdOrderBySlotNoAsc(roundId: Long): List<PlanSlot>
}

interface ReservationRepository : JpaRepository<Reservation, Long> {
    fun findByRoundIdAndActiveKeyOrderByPlayDateAscStartHourAscCourtNoAsc(roundId: Long, activeKey: Int): List<Reservation>

    /** 취소된 예약까지 포함해, 이 슬롯을 가리키는 모든 예약. 슬롯을 지우기 전에 연결을 끊을 때 쓴다. */
    fun findBySlotId(slotId: Long): List<Reservation>
}
