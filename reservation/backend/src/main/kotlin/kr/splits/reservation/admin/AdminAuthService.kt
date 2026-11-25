package kr.splits.reservation.admin

import kr.splits.reservation.club.Club
import kr.splits.reservation.common.TooManyRequestsException
import kr.splits.reservation.common.UnauthorizedException
import org.springframework.beans.factory.annotation.Value
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder
import org.springframework.stereotype.Service
import java.security.MessageDigest
import java.time.Clock
import java.time.Duration
import java.time.Instant
import java.util.Base64
import java.util.concurrent.ConcurrentHashMap
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

data class AdminToken(val token: String, val expiresAt: Instant)

/**
 * 총무 PIN 확인과 총무 토큰 발급.
 *
 * 토큰은 서버에 저장하지 않는다. `만료시각.서명` 형태이고, 서명에 PIN 해시를 섞어서
 * PIN을 바꾸면 이전 토큰이 모두 무효가 된다.
 */
@Service
class AdminAuthService(
    @Value("\${reservation.admin-token-secret}") private val secret: String,
    private val clock: Clock,
) {
    private val encoder = BCryptPasswordEncoder()
    private val failures = ConcurrentHashMap<Long, MutableList<Instant>>()

    init {
        require(secret.isNotBlank()) { "reservation.admin-token-secret 값이 비어 있습니다." }
    }

    fun hashPin(pin: String): String = encoder.encode(pin)

    fun login(club: Club, pin: String): AdminToken {
        val now = clock.instant()
        if (recentFailures(club.id, now) >= MAX_FAILURES) {
            throw TooManyRequestsException("PIN을 여러 번 틀렸어요. 10분 뒤에 다시 시도해 주세요.", "ADMIN_LOCKED")
        }
        if (!encoder.matches(pin, club.adminPinHash)) {
            failures.computeIfAbsent(club.id) { mutableListOf() }.let { synchronized(it) { it.add(now) } }
            throw UnauthorizedException("PIN이 맞지 않아요.", "ADMIN_PIN_INVALID")
        }
        failures.remove(club.id)
        val expiresAt = now.plus(TOKEN_TTL)
        return AdminToken("${expiresAt.epochSecond}.${sign(club, expiresAt.epochSecond)}", expiresAt)
    }

    fun isValid(club: Club, token: String?): Boolean {
        val parts = token?.split('.') ?: return false
        if (parts.size != 2) return false
        val expiresAt = parts[0].toLongOrNull() ?: return false
        if (expiresAt <= clock.instant().epochSecond) return false
        return MessageDigest.isEqual(sign(club, expiresAt).toByteArray(), parts[1].toByteArray())
    }

    private fun recentFailures(clubId: Long, now: Instant): Int {
        val list = failures[clubId] ?: return 0
        synchronized(list) {
            list.removeIf { it.isBefore(now.minus(LOCK_WINDOW)) }
            return list.size
        }
    }

    private fun sign(club: Club, expiresAtEpochSecond: Long): String {
        val mac = Mac.getInstance(ALGORITHM)
        mac.init(SecretKeySpec(secret.toByteArray(), ALGORITHM))
        val signature = mac.doFinal("${club.id}.$expiresAtEpochSecond.${club.adminPinHash}".toByteArray())
        return Base64.getUrlEncoder().withoutPadding().encodeToString(signature)
    }

    companion object {
        private const val ALGORITHM = "HmacSHA256"
        private const val MAX_FAILURES = 5
        private val LOCK_WINDOW: Duration = Duration.ofMinutes(10)
        private val TOKEN_TTL: Duration = Duration.ofDays(30)
    }
}
