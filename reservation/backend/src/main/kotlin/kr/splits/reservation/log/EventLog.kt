package kr.splits.reservation.log

import jakarta.persistence.Column
import jakarta.persistence.Entity
import jakarta.persistence.GeneratedValue
import jakarta.persistence.GenerationType
import jakarta.persistence.Id
import jakarta.persistence.Table
import kr.splits.reservation.club.ClubMember
import org.springframework.data.domain.Pageable
import org.springframework.data.jpa.repository.JpaRepository
import org.springframework.stereotype.Component
import java.time.Clock
import java.time.LocalDateTime

@Entity
@Table(name = "event_log")
class EventLog(
    @Column(name = "club_id", nullable = false)
    var clubId: Long,

    @Column(name = "round_id")
    var roundId: Long? = null,

    @Column(name = "actor_member_id")
    var actorMemberId: Long? = null,

    /** 이름이 나중에 바뀌어도 기록은 당시 이름으로 남긴다. */
    @Column(name = "actor_name", nullable = false)
    var actorName: String,

    @Column(nullable = false)
    var type: String,

    @Column(nullable = false)
    var detail: String,

    @Column(name = "created_at", nullable = false)
    var createdAt: LocalDateTime,

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    var id: Long = 0,
)

interface EventLogRepository : JpaRepository<EventLog, Long> {
    fun findByRoundIdOrderByIdDesc(roundId: Long, pageable: Pageable): List<EventLog>
}

@Component
class EventLogger(
    private val repository: EventLogRepository,
    private val clock: Clock,
) {
    fun member(actor: ClubMember, roundId: Long?, type: String, detail: String) {
        save(actor.clubId, roundId, actor.id, actor.name, type, detail)
    }

    fun admin(clubId: Long, roundId: Long?, type: String, detail: String) {
        save(clubId, roundId, null, ADMIN_NAME, type, detail)
    }

    private fun save(clubId: Long, roundId: Long?, actorId: Long?, actorName: String, type: String, detail: String) {
        repository.save(
            EventLog(
                clubId = clubId,
                roundId = roundId,
                actorMemberId = actorId,
                actorName = actorName,
                type = type,
                detail = detail.take(MAX_DETAIL),
                createdAt = LocalDateTime.now(clock),
            ),
        )
    }

    companion object {
        const val ADMIN_NAME = "총무"
        private const val MAX_DETAIL = 500
    }
}
