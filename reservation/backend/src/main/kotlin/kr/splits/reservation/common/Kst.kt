package kr.splits.reservation.common

import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration
import java.time.Clock
import java.time.DayOfWeek
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter

/** 예약 오픈 시각과 경기 날짜는 모두 한국 시간 기준이다. 서버 시간대 설정에 기대지 않는다. */
object Kst {
    val ZONE: ZoneId = ZoneId.of("Asia/Seoul")

    private val WEEKDAYS = mapOf(
        DayOfWeek.MONDAY to "월",
        DayOfWeek.TUESDAY to "화",
        DayOfWeek.WEDNESDAY to "수",
        DayOfWeek.THURSDAY to "목",
        DayOfWeek.FRIDAY to "금",
        DayOfWeek.SATURDAY to "토",
        DayOfWeek.SUNDAY to "일",
    )

    fun iso(dateTime: LocalDateTime): String =
        dateTime.atZone(ZONE).toOffsetDateTime().format(DateTimeFormatter.ISO_OFFSET_DATE_TIME)

    /** 기록에 남길 때 쓰는 짧은 표기. 예: 12/5(토) 14~16 */
    fun slotLabel(date: LocalDate, startHour: Int, endHour: Int): String =
        "${date.monthValue}/${date.dayOfMonth}(${WEEKDAYS.getValue(date.dayOfWeek)}) $startHour~$endHour"
}

@Configuration
class TimeConfig {
    @Bean
    fun clock(): Clock = Clock.system(Kst.ZONE)
}
