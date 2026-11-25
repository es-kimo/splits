import { useSyncExternalStore } from 'react'

/**
 * 이 기기에 남기는 것: 모임 링크의 토큰, 고른 이름, 총무 토큰.
 * 카톡 안 브라우저와 크롬은 저장소가 따로라서, 각각 한 번씩 이름을 고르게 된다.
 */
export interface Session {
  clubToken: string | null
  memberId: number | null
  adminToken: string | null
}

const KEYS = {
  clubToken: 'court.clubToken',
  memberId: 'court.memberId',
  adminToken: 'court.adminToken',
} as const

// 사생활 보호 모드에서는 localStorage가 예외를 던진다. 그때는 탭이 열려 있는 동안만 기억한다.
const memory = new Map<string, string>()

function readRaw(key: string): string | null {
  try {
    return window.localStorage.getItem(key)
  } catch {
    return memory.get(key) ?? null
  }
}

function writeRaw(key: string, value: string | null): void {
  try {
    if (value === null) window.localStorage.removeItem(key)
    else window.localStorage.setItem(key, value)
  } catch {
    if (value === null) memory.delete(key)
    else memory.set(key, value)
  }
}

function load(): Session {
  const memberId = Number(readRaw(KEYS.memberId))
  return {
    clubToken: readRaw(KEYS.clubToken),
    memberId: Number.isInteger(memberId) && memberId > 0 ? memberId : null,
    adminToken: readRaw(KEYS.adminToken),
  }
}

let current: Session = load()
const listeners = new Set<() => void>()

function update(next: Session): void {
  current = next
  listeners.forEach((listener) => listener())
}

export const session = {
  get: (): Session => current,

  /** 다른 모임의 링크로 들어오면 이전 모임에서 고른 이름과 총무 토큰은 버린다. */
  setClubToken(clubToken: string): void {
    if (current.clubToken === clubToken) return
    writeRaw(KEYS.clubToken, clubToken)
    writeRaw(KEYS.memberId, null)
    writeRaw(KEYS.adminToken, null)
    update({ clubToken, memberId: null, adminToken: null })
  },

  setMemberId(memberId: number | null): void {
    writeRaw(KEYS.memberId, memberId === null ? null : String(memberId))
    update({ ...current, memberId })
  },

  setAdminToken(adminToken: string | null): void {
    writeRaw(KEYS.adminToken, adminToken)
    update({ ...current, adminToken })
  },

  clear(): void {
    Object.values(KEYS).forEach((key) => writeRaw(key, null))
    update({ clubToken: null, memberId: null, adminToken: null })
  },

  subscribe(listener: () => void): () => void {
    listeners.add(listener)
    return () => listeners.delete(listener)
  },
}

export function useSession(): Session {
  return useSyncExternalStore(session.subscribe, session.get)
}
