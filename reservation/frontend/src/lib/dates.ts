const WEEKDAYS = ['일', '월', '화', '수', '목', '금', '토'] as const

export interface DateParts {
  year: number
  month: number
  day: number
}

/** 'YYYY-MM-DD'를 쪼갠다. 기기 시간대와 무관하게 다루려고 Date 객체로 바꾸지 않는다. */
export function parseDate(iso: string): DateParts {
  const [year, month, day] = iso.split('-').map(Number)
  return { year, month, day }
}

export function toIsoDate({ year, month, day }: DateParts): string {
  return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`
}

/** 2월 30일처럼 달력에 없는 날짜를 걸러낸다. */
export function isRealDate({ year, month, day }: DateParts): boolean {
  const date = new Date(Date.UTC(year, month - 1, day))
  return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day
}

/** 0(일) ~ 6(토) */
export function weekdayIndex(iso: string): number {
  const { year, month, day } = parseDate(iso)
  return new Date(Date.UTC(year, month - 1, day)).getUTCDay()
}

export function weekdayName(iso: string): string {
  return WEEKDAYS[weekdayIndex(iso)]
}

export function isWeekend(iso: string): boolean {
  const index = weekdayIndex(iso)
  return index === 0 || index === 6
}

/** 12/5(토) */
export function dateLabel(iso: string): string {
  const { month, day } = parseDate(iso)
  return `${month}/${day}(${weekdayName(iso)})`
}

/** 14~16시 */
export function hoursLabel(startHour: number, endHour: number): string {
  return `${startHour}~${endHour}시`
}

export function courtPrefLabel(courtPref: number | null): string {
  return courtPref === null ? '아무 코트' : `${courtPref}번 코트`
}

/** 남은 시간을 사람이 읽는 말로. 1시간 미만은 초까지 보여준다. */
export function countdownLabel(remainingMs: number): string {
  const totalSeconds = Math.max(0, Math.ceil(remainingMs / 1000))
  const days = Math.floor(totalSeconds / 86400)
  const hours = Math.floor((totalSeconds % 86400) / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60
  if (days > 0) return `${days}일 ${hours}시간`
  if (hours > 0) return `${hours}시간 ${minutes}분`
  return `${minutes}분 ${String(seconds).padStart(2, '0')}초`
}

/** 서버가 준 시각(오프셋 포함)을 한국 시간 "11/25 10:12"로. */
export function kstTimeLabel(epochMs: number): string {
  const kst = new Date(epochMs + 9 * 60 * 60 * 1000)
  const hh = String(kst.getUTCHours()).padStart(2, '0')
  const mm = String(kst.getUTCMinutes()).padStart(2, '0')
  return `${kst.getUTCMonth() + 1}/${kst.getUTCDate()} ${hh}:${mm}`
}
