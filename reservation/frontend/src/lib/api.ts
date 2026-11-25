import type { z } from 'zod'
import { session } from './session'
import {
  AdminLoginSchema,
  BoardSchema,
  ClubSchema,
  EventSchema,
  MemberSchema,
  RoundSchema,
  type Board,
  type BoardEvent,
  type Club,
  type FailKind,
  type Member,
  type PlanItem,
  type Round,
} from './types'

const BASE = '/api/v1'

export class ApiError extends Error {
  readonly status: number
  readonly code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

/** 화면에 그대로 보여줄 문장으로 바꾼다. */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message
  return '연결이 잠시 끊겼어요. 다시 시도해 주세요.'
}

// 카운트다운은 기기 시계가 아니라 서버 시계 기준으로 센다. 응답을 받을 때마다 차이를 다시 잰다.
let serverOffsetMs = 0

function syncClock(serverTime: string): void {
  const parsed = Date.parse(serverTime)
  if (!Number.isNaN(parsed)) serverOffsetMs = parsed - Date.now()
}

export function serverNow(): number {
  return Date.now() + serverOffsetMs
}

interface RequestOptions {
  body?: unknown
}

async function send(method: string, path: string, options: RequestOptions = {}): Promise<Response> {
  const { clubToken, memberId, adminToken } = session.get()
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (clubToken) headers['X-Club-Token'] = clubToken
  if (memberId !== null) headers['X-Member-Id'] = String(memberId)
  if (adminToken) headers['X-Admin-Token'] = adminToken
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'

  let response: Response
  try {
    response = await fetch(`${BASE}${path}`, {
      method,
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      cache: 'no-store',
    })
  } catch {
    throw new ApiError(0, 'NETWORK', '연결이 잠시 끊겼어요. 다시 시도해 주세요.')
  }
  if (response.ok) return response

  let code = 'UNKNOWN'
  let message = '잠시 문제가 생겼어요. 다시 시도해 주세요.'
  try {
    const payload: unknown = await response.json()
    if (payload && typeof payload === 'object') {
      const record = payload as Record<string, unknown>
      if (typeof record.code === 'string') code = record.code
      // 스프링 기본 오류 응답에도 message가 있지만 사용자용 문장이 아니다. code가 있을 때만 믿는다.
      if (typeof record.code === 'string' && typeof record.message === 'string') message = record.message
    }
  } catch {
    // 본문이 JSON이 아니면 기본 문구를 쓴다.
  }
  throw new ApiError(response.status, code, message)
}

async function parse<S extends z.ZodType>(response: Response, schema: S): Promise<z.infer<S>> {
  const result = schema.safeParse(await response.json())
  if (!result.success) {
    console.error('응답 모양이 예상과 달라요', result.error)
    throw new ApiError(response.status, 'BAD_RESPONSE', '화면을 새로 고쳐 주세요. 앱이 업데이트됐을 수 있어요.')
  }
  return result.data
}

async function parseBoard(response: Response): Promise<Board> {
  const board = await parse(response, BoardSchema)
  syncClock(board.serverTime)
  return board
}

export interface ReservationInput {
  slotId: number | null
  playDate: string
  startHour: number
  endHour: number
  courtNo: number
  bookerMemberId: number
}

export interface RoundInput {
  title?: string
  /** 한국 시간. 예: 2026-11-25T10:00 */
  opensAt?: string
  bookingUrl?: string
  courtLinks?: Record<string, string>
  archived?: boolean
}

export const api = {
  async getClub(): Promise<Club> {
    const club = await parse(await send('GET', '/club'), ClubSchema)
    syncClock(club.serverTime)
    return club
  },

  /** 바뀐 게 없으면 null. */
  async getBoard(roundId: number, since?: number): Promise<Board | null> {
    const query = since === undefined ? '' : `?since=${since}`
    const response = await send('GET', `/rounds/${roundId}/board${query}`)
    return response.status === 204 ? null : parseBoard(response)
  },

  async getEvents(roundId: number): Promise<BoardEvent[]> {
    return parse(await send('GET', `/rounds/${roundId}/events`), EventSchema.array())
  },

  async createReservation(roundId: number, input: ReservationInput): Promise<Board> {
    return parseBoard(await send('POST', `/rounds/${roundId}/reservations`, { body: input }))
  },

  async cancelReservation(roundId: number, reservationId: number): Promise<Board> {
    return parseBoard(await send('DELETE', `/rounds/${roundId}/reservations/${reservationId}`))
  },

  async reportFail(roundId: number, slotId: number, kind: FailKind): Promise<Board> {
    return parseBoard(await send('POST', `/rounds/${roundId}/slots/${slotId}/fail`, { body: { kind } }))
  },

  async clearFail(roundId: number, slotId: number): Promise<Board> {
    return parseBoard(await send('DELETE', `/rounds/${roundId}/slots/${slotId}/fail`))
  },

  async setAssignee(roundId: number, slotId: number, memberId: number | null): Promise<Board> {
    return parseBoard(await send('PUT', `/rounds/${roundId}/slots/${slotId}/assignee`, { body: { memberId } }))
  },

  async adminLogin(pin: string): Promise<string> {
    const result = await parse(await send('POST', '/admin/login', { body: { pin } }), AdminLoginSchema)
    return result.token
  },

  async addMember(name: string): Promise<Member> {
    return parse(await send('POST', '/admin/members', { body: { name } }), MemberSchema)
  },

  async updateMember(memberId: number, patch: { name?: string; active?: boolean }): Promise<Member> {
    return parse(await send('PATCH', `/admin/members/${memberId}`, { body: patch }), MemberSchema)
  },

  async createRound(input: RoundInput): Promise<Round> {
    return parse(await send('POST', '/admin/rounds', { body: input }), RoundSchema)
  },

  async updateRound(roundId: number, input: RoundInput): Promise<Round> {
    return parse(await send('PATCH', `/admin/rounds/${roundId}`, { body: input }), RoundSchema)
  },

  async savePlan(roundId: number, items: PlanItem[]): Promise<Board> {
    return parseBoard(await send('PUT', `/admin/rounds/${roundId}/slots`, { body: items }))
  },
}
