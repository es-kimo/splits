package kr.splits.reservation.club

import jakarta.persistence.Column
import jakarta.persistence.Entity
import jakarta.persistence.GeneratedValue
import jakarta.persistence.GenerationType
import jakarta.persistence.Id
import jakarta.persistence.Table
import org.springframework.data.jpa.repository.JpaRepository
import java.time.LocalDateTime

@Entity
@Table(name = "club")
class Club(
    @Column(nullable = false)
    var name: String,

    /** 모임 링크에 들어가는 값. 이 값을 아는 사람만 모임 데이터를 볼 수 있다. */
    @Column(name = "access_token", nullable = false)
    var accessToken: String,

    @Column(name = "admin_pin_hash", nullable = false)
    var adminPinHash: String,

    @Column(name = "created_at", nullable = false)
    var createdAt: LocalDateTime,

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    var id: Long = 0,
)

@Entity
@Table(name = "club_member")
class ClubMember(
    @Column(name = "club_id", nullable = false)
    var clubId: Long,

    @Column(nullable = false)
    var name: String,

    @Column(nullable = false)
    var active: Boolean,

    @Column(name = "created_at", nullable = false)
    var createdAt: LocalDateTime,

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    var id: Long = 0,
)

interface ClubRepository : JpaRepository<Club, Long> {
    fun findByAccessToken(accessToken: String): Club?
}

interface ClubMemberRepository : JpaRepository<ClubMember, Long> {
    fun findByClubIdOrderByNameAsc(clubId: Long): List<ClubMember>
    fun findByClubIdAndName(clubId: Long, name: String): ClubMember?
}
