import { courtPrefLabel, dateLabel, kstTimeLabel } from './dates'
import type { Board, Slot } from './types'

const STATE_TEXT: Record<Slot['state'], string> = {
  PLANNED: '보고 없음',
  SECURED: '확보',
  NEED_HELP: '도움 필요',
  CLOSED: '놓침',
}

export interface ShareTextInput {
  board: Board
  memberName: (memberId: number | null) => string
  /** 현황판 주소. 글 끝에 붙인다. 모임 토큰이 들어간 주소는 넣지 않는다. */
  link: string
  nowMs: number
}

/**
 * 카톡방에 붙여넣을 결과 글.
 * 총무가 예약이 끝난 뒤 손으로 만들던 표를 대신한다.
 */
export function buildShareText({ board, memberName, link, nowMs }: ShareTextInput): string {
  const { summary } = board
  const reservationById = new Map(board.reservations.map((reservation) => [reservation.id, reservation]))

  const header = [
    `[${board.round.title}] ${kstTimeLabel(nowMs)} 기준`,
    [
      `확보 ${summary.secured}/${summary.total}`,
      summary.needHelp > 0 ? `도움 필요 ${summary.needHelp}` : null,
      summary.closed > 0 ? `놓침 ${summary.closed}` : null,
      summary.planned > 0 ? `보고 없음 ${summary.planned}` : null,
    ]
      .filter(Boolean)
      .join(' · '),
  ]

  const slotLines = [...board.slots]
    .sort((a, b) => a.playDate.localeCompare(b.playDate) || a.startHour - b.startHour || a.slotNo - b.slotNo)
    .map((slot) => {
      const when = `${dateLabel(slot.playDate)} ${slot.startHour}~${slot.endHour}`
      const reservation = slot.reservationId === null ? null : reservationById.get(slot.reservationId)
      if (reservation) {
        const booker = memberName(reservation.bookerMemberId)
        const assignee = slot.assigneeMemberId !== reservation.bookerMemberId ? `, 담당 ${memberName(slot.assigneeMemberId)}` : ''
        return `${when} ${reservation.courtNo}코트 → 확보 (${booker}${assignee})`
      }
      return `${when} ${courtPrefLabel(slot.courtPref)} → ${STATE_TEXT[slot.state]} (담당 ${memberName(slot.assigneeMemberId)})`
    })

  const unplanned = board.reservations
    .filter((reservation) => reservation.slotId === null)
    .sort((a, b) => a.playDate.localeCompare(b.playDate) || a.startHour - b.startHour || a.courtNo - b.courtNo)
    .map(
      (reservation) =>
        `${dateLabel(reservation.playDate)} ${reservation.startHour}~${reservation.endHour} ${reservation.courtNo}코트 (${memberName(reservation.bookerMemberId)})`,
    )

  return [
    ...header,
    '',
    ...slotLines,
    ...(unplanned.length > 0 ? ['', `계획에 없던 예약 ${unplanned.length}건`, ...unplanned] : []),
    '',
    link,
  ].join('\n')
}
