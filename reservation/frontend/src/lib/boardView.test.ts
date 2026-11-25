import { describe, expect, it } from 'vitest'
import { bookingLinkFor, buildBoardView } from './boardView'
import { countdownLabel, dateLabel, isWeekend, kstTimeLabel } from './dates'
import { buildShareText } from './shareText'
import type { Board, Member, Reservation, Slot } from './types'

const members: Member[] = [
  { id: 1, name: '가람', active: true },
  { id: 2, name: '나래', active: true },
  { id: 3, name: '다온', active: false },
]

function slot(partial: Partial<Slot> & Pick<Slot, 'id' | 'slotNo' | 'playDate' | 'startHour'>): Slot {
  return {
    endHour: partial.startHour + 2,
    courtPref: 3,
    assigneeMemberId: null,
    state: 'PLANNED',
    failMemberId: null,
    reservationId: null,
    ...partial,
  }
}

function reservation(partial: Partial<Reservation> & Pick<Reservation, 'id' | 'playDate' | 'startHour' | 'bookerMemberId'>): Reservation {
  return {
    endHour: partial.startHour + 2,
    courtNo: 3,
    reportedByMemberId: partial.bookerMemberId,
    slotId: null,
    createdAt: '2026-11-25T10:01:00+09:00',
    ...partial,
  }
}

function board(slots: Slot[], reservations: Reservation[]): Board {
  return {
    round: {
      id: 1,
      title: '12월 예약',
      opensAt: '2026-11-25T10:00:00+09:00',
      bookingUrl: 'https://example.org/list',
      courtLinks: { '3': 'https://example.org/court/3' },
      version: 1,
      archived: false,
    },
    slots,
    reservations,
    summary: {
      total: slots.length,
      secured: slots.filter((s) => s.state === 'SECURED').length,
      needHelp: slots.filter((s) => s.state === 'NEED_HELP').length,
      closed: slots.filter((s) => s.state === 'CLOSED').length,
      planned: slots.filter((s) => s.state === 'PLANNED').length,
      unplanned: reservations.filter((r) => r.slotId === null).length,
    },
    serverTime: '2026-11-25T10:12:00+09:00',
  }
}

const sample = board(
  [
    slot({ id: 12, slotNo: 2, playDate: '2026-12-12', startHour: 16, assigneeMemberId: 2, state: 'NEED_HELP', failMemberId: 2 }),
    slot({ id: 11, slotNo: 1, playDate: '2026-12-05', startHour: 14, assigneeMemberId: 1 }),
    slot({ id: 13, slotNo: 3, playDate: '2026-12-12', startHour: 14, assigneeMemberId: 2, state: 'SECURED', reservationId: 101 }),
    slot({ id: 14, slotNo: 4, playDate: '2026-12-13', startHour: 10, courtPref: null, state: 'CLOSED' }),
    slot({ id: 15, slotNo: 5, playDate: '2026-12-20', startHour: 10, courtPref: null }),
  ],
  [
    reservation({ id: 101, playDate: '2026-12-12', startHour: 14, bookerMemberId: 1, slotId: 13 }),
    reservation({ id: 102, playDate: '2026-12-24', startHour: 16, bookerMemberId: 3, courtNo: 1 }),
  ],
)

describe('buildBoardView', () => {
  it('내가 맡았고 아직 끝나지 않은 슬롯만 내 할 일로 모은다', () => {
    expect(buildBoardView(sample, members, 1).mine.map((s) => s.slotNo)).toEqual([1])
    expect(buildBoardView(sample, members, 2).mine.map((s) => s.slotNo)).toEqual([2])
    expect(buildBoardView(sample, members, null).mine).toEqual([])
  })

  it('맡은 사람이 못 하거나 담당이 없는 슬롯을 도움 필요로 모으되 내 것은 뺀다', () => {
    expect(buildBoardView(sample, members, 1).needHelp.map((s) => s.slotNo)).toEqual([2, 5])
    expect(buildBoardView(sample, members, 2).needHelp.map((s) => s.slotNo)).toEqual([5])
  })

  it('날짜와 시간 순으로 묶고 확보된 슬롯에는 예약을 붙인다', () => {
    const view = buildBoardView(sample, members, 1)

    expect(view.byDate.map((group) => [group.playDate, group.slots.map((s) => s.slotNo)])).toEqual([
      ['2026-12-05', [1]],
      ['2026-12-12', [3, 2]],
      ['2026-12-13', [4]],
      ['2026-12-20', [5]],
    ])
    expect(view.byDate[1].slots[0].reservation?.bookerMemberId).toBe(1)
  })

  it('계획에 없던 예약과 사람별 주말·주중 건수를 낸다', () => {
    const view = buildBoardView(sample, members, 1)

    expect(view.unplanned.map((r) => r.id)).toEqual([102])
    // 그만둔 사람도 예약이 있으면 보이고, 예약이 없는 현역은 0건으로 보인다.
    expect(view.people).toEqual([
      { memberId: 1, name: '가람', weekend: 1, weekday: 0 },
      { memberId: 3, name: '다온', weekend: 0, weekday: 1 },
      { memberId: 2, name: '나래', weekend: 0, weekday: 0 },
    ])
  })
})

describe('bookingLinkFor', () => {
  it('계획한 코트의 주소가 있으면 그쪽을, 없으면 목록 주소를 준다', () => {
    expect(bookingLinkFor(sample, 3)).toBe('https://example.org/court/3')
    expect(bookingLinkFor(sample, 1)).toBe('https://example.org/list')
    expect(bookingLinkFor(sample, null)).toBe('https://example.org/list')
  })
})

describe('buildShareText', () => {
  it('카톡방에 붙여넣을 결과 글을 만든다', () => {
    const names = new Map(members.map((m) => [m.id, m.name]))
    const text = buildShareText({
      board: sample,
      memberName: (id) => (id === null ? '없음' : (names.get(id) ?? '알 수 없음')),
      link: 'https://court.example',
      nowMs: Date.parse('2026-11-25T10:12:00+09:00'),
    })

    expect(text).toBe(
      [
        '[12월 예약] 11/25 10:12 기준',
        '확보 1/5 · 도움 필요 1 · 놓침 1 · 보고 없음 2',
        '',
        '12/5(토) 14~16 3번 코트 → 보고 없음 (담당 가람)',
        '12/12(토) 14~16 3코트 → 확보 (가람, 담당 나래)',
        '12/12(토) 16~18 3번 코트 → 도움 필요 (담당 나래)',
        '12/13(일) 10~12 아무 코트 → 놓침 (담당 없음)',
        '12/20(일) 10~12 아무 코트 → 보고 없음 (담당 없음)',
        '',
        '계획에 없던 예약 1건',
        '12/24(목) 16~18 1코트 (다온)',
        '',
        'https://court.example',
      ].join('\n'),
    )
  })
})

describe('dates', () => {
  it('기기 시간대와 무관하게 요일을 낸다', () => {
    expect(dateLabel('2026-12-05')).toBe('12/5(토)')
    expect(dateLabel('2026-12-25')).toBe('12/25(금)')
    expect(isWeekend('2026-12-06')).toBe(true)
    expect(isWeekend('2026-12-25')).toBe(false)
  })

  it('남은 시간을 읽기 쉬운 말로 바꾼다', () => {
    expect(countdownLabel(2 * 86400_000 + 3 * 3600_000)).toBe('2일 3시간')
    expect(countdownLabel(3 * 3600_000 + 5 * 60_000)).toBe('3시간 5분')
    expect(countdownLabel(125_000)).toBe('2분 05초')
    expect(countdownLabel(-5)).toBe('0분 00초')
  })

  it('한국 시간으로 시각을 적는다', () => {
    expect(kstTimeLabel(Date.parse('2026-11-25T01:12:00Z'))).toBe('11/25 10:12')
  })
})
