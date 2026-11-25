import { describe, expect, it } from 'vitest'
import { formatPlan, parsePlan } from './planParser'

const BASE = { year: 2026, month: 11 }

describe('parsePlan', () => {
  it('카톡 공지 형식을 읽고, 번호로 시작하지 않는 줄은 건너뛴다', () => {
    const text = [
      '[신정교 테니스장 : 12월 예약 계획]',
      '',
      '코트예약 우선순위',
      '- 1순위 : 토요일 14~18시, 3번코트 확보 (오후반을 위해)',
      '',
      '코트예약 할당',
      '1. 가람 : [3번코트] 12/5(토) 16~18시',
      '2. 가람 : [아무코트] 12/27(일) 10~12시',
      '18. 하늘 : [아무코트] 12/6(일) 10~12시',
    ].join('\n')

    const result = parsePlan(text, BASE)

    expect(result.errors).toEqual([])
    expect(result.lines).toEqual([
      { slotNo: 1, name: '가람', courtPref: 3, playDate: '2026-12-05', startHour: 16, endHour: 18, warnings: [] },
      { slotNo: 2, name: '가람', courtPref: null, playDate: '2026-12-27', startHour: 10, endHour: 12, warnings: [] },
      { slotNo: 18, name: '하늘', courtPref: null, playDate: '2026-12-06', startHour: 10, endHour: 12, warnings: [] },
    ])
  })

  it('띄어쓰기와 요일 생략, 전각 콜론을 받아들인다', () => {
    const result = parsePlan('3) 나래 ： [ 2 번 코트 ] 12 / 13 10시~12시', BASE)

    expect(result.errors).toEqual([])
    expect(result.lines[0]).toMatchObject({ slotNo: 3, name: '나래', courtPref: 2, playDate: '2026-12-13' })
  })

  it('요일이 날짜와 다르면 저장은 하되 알려준다', () => {
    const result = parsePlan('1. 가람 : [3번코트] 12/5(일) 16~18시', BASE)

    expect(result.errors).toEqual([])
    expect(result.lines[0].warnings).toEqual(['12/5 날짜는 토요일이에요. (일)로 적혀 있어요.'])
  })

  it('12월에 여는 예약의 1월 날짜는 다음 해로 읽는다', () => {
    const result = parsePlan('1. 가람 : [3번코트] 1/9(토) 14~16시', { year: 2026, month: 12 })

    expect(result.lines[0].playDate).toBe('2027-01-09')
    expect(result.lines[0].warnings).toEqual([])
  })

  it('읽지 못한 줄은 줄 번호와 이유를 돌려준다', () => {
    const text = [
      '1. 가람 : [3번코트] 12/5(토) 16~18시',
      '1. 나래 : [3번코트] 12/12(토) 16~18시',
      '2. 다온 : [잔디코트] 12/12(토) 14~16시',
      '3. 라온 : [3번코트] 12/32(토) 14~16시',
      '4. 마루 : [3번코트] 12/19(토) 18~16시',
      '5. 바다 12/19 토요일 오후',
    ].join('\n')

    const result = parsePlan(text, BASE)

    expect(result.lines.map((line) => line.slotNo)).toEqual([1])
    expect(result.errors.map((error) => [error.lineNo, error.reason])).toEqual([
      [2, '1번이 두 번 나와요.'],
      [3, '코트를 읽지 못했어요: [잔디코트]'],
      [4, '달력에 없는 날짜예요: 12/32'],
      [5, '시간이 이상해요: 18~16'],
      [6, '형식을 읽지 못했어요. 예: 1. 이름 : [3번코트] 12/5(토) 16~18시'],
    ])
  })
})

describe('formatPlan', () => {
  it('저장된 계획을 다시 읽을 수 있는 글로 되돌린다', () => {
    const text = formatPlan([
      { slotNo: 2, playDate: '2026-12-27', startHour: 10, endHour: 12, courtPref: null, assigneeName: null },
      { slotNo: 1, playDate: '2026-12-05', startHour: 16, endHour: 18, courtPref: 3, assigneeName: '가람' },
    ])

    expect(text).toBe('1. 가람 : [3번코트] 12/5(토) 16~18시\n2. 담당없음 : [아무코트] 12/27(일) 10~12시')
    expect(parsePlan(text, BASE).lines.map((line) => [line.slotNo, line.name, line.playDate])).toEqual([
      [1, '가람', '2026-12-05'],
      [2, '담당없음', '2026-12-27'],
    ])
  })
})
