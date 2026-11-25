import { isWeekend } from './dates'
import type { Board, Member, Reservation, Slot } from './types'

export interface SlotView extends Slot {
  reservation: Reservation | null
}

export interface DateGroup {
  playDate: string
  slots: SlotView[]
}

export interface PersonSummary {
  memberId: number
  name: string
  weekend: number
  weekday: number
}

export interface BoardView {
  /** 내가 맡았고 아직 끝나지 않은 슬롯. */
  mine: SlotView[]
  /** 맡은 사람이 못 하거나 담당이 없는 슬롯. 내 것은 뺀다. */
  needHelp: SlotView[]
  byDate: DateGroup[]
  /** 계획에 없던 예약. */
  unplanned: Reservation[]
  people: PersonSummary[]
}

function bySchedule(a: Slot, b: Slot): number {
  return a.playDate.localeCompare(b.playDate) || a.startHour - b.startHour || a.slotNo - b.slotNo
}

export function isUnresolved(slot: Slot): boolean {
  return slot.state === 'PLANNED' || slot.state === 'NEED_HELP'
}

export function buildBoardView(board: Board, members: Member[], myId: number | null): BoardView {
  const reservationById = new Map(board.reservations.map((reservation) => [reservation.id, reservation]))
  const slots: SlotView[] = board.slots
    .map((slot) => ({
      ...slot,
      reservation: slot.reservationId === null ? null : (reservationById.get(slot.reservationId) ?? null),
    }))
    .sort(bySchedule)

  const mine = slots.filter((slot) => myId !== null && slot.assigneeMemberId === myId && isUnresolved(slot))
  const needHelp = slots.filter(
    (slot) =>
      !mine.includes(slot) &&
      (slot.state === 'NEED_HELP' || (slot.state === 'PLANNED' && slot.assigneeMemberId === null)),
  )

  const byDate: DateGroup[] = []
  for (const slot of slots) {
    const last = byDate.at(-1)
    if (last && last.playDate === slot.playDate) last.slots.push(slot)
    else byDate.push({ playDate: slot.playDate, slots: [slot] })
  }

  const unplanned = board.reservations
    .filter((reservation) => reservation.slotId === null)
    .sort((a, b) => a.playDate.localeCompare(b.playDate) || a.startHour - b.startHour || a.courtNo - b.courtNo)

  const counts = new Map<number, { weekend: number; weekday: number }>()
  for (const reservation of board.reservations) {
    const entry = counts.get(reservation.bookerMemberId) ?? { weekend: 0, weekday: 0 }
    if (isWeekend(reservation.playDate)) entry.weekend += 1
    else entry.weekday += 1
    counts.set(reservation.bookerMemberId, entry)
  }
  const people: PersonSummary[] = members
    .filter((member) => member.active || counts.has(member.id))
    .map((member) => ({
      memberId: member.id,
      name: member.name,
      weekend: counts.get(member.id)?.weekend ?? 0,
      weekday: counts.get(member.id)?.weekday ?? 0,
    }))
    .sort((a, b) => b.weekend + b.weekday - (a.weekend + a.weekday) || a.name.localeCompare(b.name, 'ko'))

  return { mine, needHelp, byDate, unplanned, people }
}

/** 슬롯에서 열 예약 페이지. 계획한 코트의 주소가 있으면 그쪽, 없으면 목록 주소. */
export function bookingLinkFor(board: Board, courtPref: number | null): string | null {
  if (courtPref !== null) {
    const direct = board.round.courtLinks[String(courtPref)]
    if (direct) return direct
  }
  return board.round.bookingUrl
}
