import { isRealDate, toIsoDate, weekdayName } from './dates'

/**
 * 카톡 공지에 올리던 계획 형식을 그대로 읽는다.
 *
 *   1. 가람 : [3번코트] 12/5(토) 16~18시
 *   2. 가람 : [아무코트] 12/27(일) 10~12시
 *
 * 번호로 시작하지 않는 줄(제목, 우선순위 설명 등)은 건너뛴다.
 */
export interface ParsedPlanLine {
  slotNo: number
  name: string
  courtPref: number | null
  playDate: string
  startHour: number
  endHour: number
  /** 저장은 되지만 확인이 필요한 점. */
  warnings: string[]
}

export interface PlanParseError {
  lineNo: number
  text: string
  reason: string
}

export interface PlanParseResult {
  lines: ParsedPlanLine[]
  errors: PlanParseError[]
}

export interface PlanBase {
  /** 예약이 열리는 해와 달. 경기 날짜에 연도가 없어서 여기서 추정한다. */
  year: number
  month: number
}

const NUMBERED = /^\s*(\d+)\s*[.)]/
const LINE =
  /^\s*(\d+)\s*[.)]\s*(.+?)\s*[:：]\s*\[\s*(.+?)\s*\]\s*(\d{1,2})\s*\/\s*(\d{1,2})\s*(?:\(\s*([일월화수목금토])\s*\))?\s*(\d{1,2})\s*시?\s*[~\-–]\s*(\d{1,2})\s*시?\s*$/

function parseCourt(text: string): number | null | undefined {
  const compact = text.replace(/\s/g, '')
  if (/^아무(코트)?$/.test(compact)) return null
  const match = /^(\d+)번?코트$/.exec(compact)
  return match ? Number(match[1]) : undefined
}

/** 12월에 열리는 예약에 "1/3"이 있으면 다음 해 1월이다. */
function resolveYear(month: number, base: PlanBase): number {
  return month >= base.month ? base.year : base.year + 1
}

export function parsePlan(text: string, base: PlanBase): PlanParseResult {
  const lines: ParsedPlanLine[] = []
  const errors: PlanParseError[] = []
  const seen = new Set<number>()

  text.split(/\r?\n/).forEach((raw, index) => {
    if (!NUMBERED.test(raw)) return
    const lineNo = index + 1
    const fail = (reason: string) => errors.push({ lineNo, text: raw.trim(), reason })

    const match = LINE.exec(raw)
    if (!match) {
      fail('형식을 읽지 못했어요. 예: 1. 이름 : [3번코트] 12/5(토) 16~18시')
      return
    }
    const [, slotNoText, name, courtText, monthText, dayText, weekday, startText, endText] = match
    const slotNo = Number(slotNoText)
    const month = Number(monthText)
    const day = Number(dayText)
    const startHour = Number(startText)
    const endHour = Number(endText)

    if (seen.has(slotNo)) return fail(`${slotNo}번이 두 번 나와요.`)
    const courtPref = parseCourt(courtText)
    if (courtPref === undefined) return fail(`코트를 읽지 못했어요: [${courtText}]`)
    const date = { year: resolveYear(month, base), month, day }
    if (!isRealDate(date)) return fail(`달력에 없는 날짜예요: ${month}/${day}`)
    if (startHour < 0 || endHour > 24 || startHour >= endHour) return fail(`시간이 이상해요: ${startHour}~${endHour}`)

    const playDate = toIsoDate(date)
    const warnings: string[] = []
    if (weekday && weekday !== weekdayName(playDate)) {
      warnings.push(`${month}/${day} 날짜는 ${weekdayName(playDate)}요일이에요. (${weekday})로 적혀 있어요.`)
    }

    seen.add(slotNo)
    lines.push({ slotNo, name: name.trim(), courtPref, playDate, startHour, endHour, warnings })
  })

  return { lines, errors }
}

export interface PlanTextSlot {
  slotNo: number
  playDate: string
  startHour: number
  endHour: number
  courtPref: number | null
  assigneeName: string | null
}

/** 저장된 계획을 같은 형식의 글로 되돌린다. 고쳐서 다시 붙여넣을 수 있게 한다. */
export function formatPlan(slots: PlanTextSlot[]): string {
  return [...slots]
    .sort((a, b) => a.slotNo - b.slotNo)
    .map((slot) => {
      const [, month, day] = slot.playDate.split('-').map(Number)
      const court = slot.courtPref === null ? '아무코트' : `${slot.courtPref}번코트`
      const name = slot.assigneeName ?? '담당없음'
      return `${slot.slotNo}. ${name} : [${court}] ${month}/${day}(${weekdayName(slot.playDate)}) ${slot.startHour}~${slot.endHour}시`
    })
    .join('\n')
}

/** 공지 형식에서 담당자가 없다는 표시로 쓰는 이름. */
export const NO_ASSIGNEE_NAME = '담당없음'
