import { z } from 'zod'

// 서버 응답은 화면에 쓰기 전에 모양을 확인한다. 어긋나면 빈 화면 대신 오류 문구가 뜬다.

export const MemberSchema = z.object({
  id: z.number(),
  name: z.string(),
  active: z.boolean(),
})
export type Member = z.infer<typeof MemberSchema>

export const RoundSummarySchema = z.object({
  id: z.number(),
  title: z.string(),
  opensAt: z.string(),
})

export const ClubSchema = z.object({
  id: z.number(),
  name: z.string(),
  members: z.array(MemberSchema),
  rounds: z.array(RoundSummarySchema),
  currentRoundId: z.number().nullable(),
  serverTime: z.string(),
})
export type Club = z.infer<typeof ClubSchema>

export const RoundSchema = z.object({
  id: z.number(),
  title: z.string(),
  opensAt: z.string(),
  bookingUrl: z.string().nullable(),
  courtLinks: z.record(z.string(), z.string()),
  version: z.number(),
  archived: z.boolean(),
})
export type Round = z.infer<typeof RoundSchema>

export const SlotStateSchema = z.enum(['PLANNED', 'SECURED', 'NEED_HELP', 'CLOSED'])
export type SlotState = z.infer<typeof SlotStateSchema>

export const SlotSchema = z.object({
  id: z.number(),
  slotNo: z.number(),
  playDate: z.string(),
  startHour: z.number(),
  endHour: z.number(),
  courtPref: z.number().nullable(),
  assigneeMemberId: z.number().nullable(),
  state: SlotStateSchema,
  failMemberId: z.number().nullable(),
  reservationId: z.number().nullable(),
})
export type Slot = z.infer<typeof SlotSchema>

export const ReservationSchema = z.object({
  id: z.number(),
  playDate: z.string(),
  startHour: z.number(),
  endHour: z.number(),
  courtNo: z.number(),
  bookerMemberId: z.number(),
  reportedByMemberId: z.number(),
  slotId: z.number().nullable(),
  createdAt: z.string(),
})
export type Reservation = z.infer<typeof ReservationSchema>

export const SummarySchema = z.object({
  total: z.number(),
  secured: z.number(),
  needHelp: z.number(),
  closed: z.number(),
  planned: z.number(),
  unplanned: z.number(),
})
export type Summary = z.infer<typeof SummarySchema>

export const BoardSchema = z.object({
  round: RoundSchema,
  slots: z.array(SlotSchema),
  reservations: z.array(ReservationSchema),
  summary: SummarySchema,
  serverTime: z.string(),
})
export type Board = z.infer<typeof BoardSchema>

export const EventSchema = z.object({
  id: z.number(),
  actorName: z.string(),
  type: z.string(),
  detail: z.string(),
  createdAt: z.string(),
})
export type BoardEvent = z.infer<typeof EventSchema>

export const AdminLoginSchema = z.object({
  token: z.string(),
  expiresAt: z.string(),
})

export type FailKind = 'NEED_HELP' | 'CLOSED'

export interface PlanItem {
  slotNo: number
  playDate: string
  startHour: number
  endHour: number
  courtPref: number | null
  assigneeMemberId: number | null
}
