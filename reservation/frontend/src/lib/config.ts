/** 구장의 코트 번호. 모임 설정으로 빼기 전까지는 여기 한 곳에서만 정한다. */
export const COURTS = [1, 2, 3] as const

/** 예약 사이트가 파는 시간대(시작 시각). 모두 2시간 단위다. */
export const START_HOURS = [8, 10, 12, 14, 16] as const

export const SLOT_HOURS = 2

/** 예약이 열리기 10분 전부터 1시간 뒤까지는 현황판을 자주 다시 읽는다. */
export const LIVE_WINDOW_BEFORE_MS = 10 * 60 * 1000
export const LIVE_WINDOW_AFTER_MS = 60 * 60 * 1000
export const LIVE_POLL_MS = 2500
export const IDLE_POLL_MS = 20000
