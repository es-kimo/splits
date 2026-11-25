import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useState } from 'react'
import { ApiError, api, errorMessage, serverNow } from './api'
import { IDLE_POLL_MS, LIVE_POLL_MS, LIVE_WINDOW_AFTER_MS, LIVE_WINDOW_BEFORE_MS } from './config'
import type { Board } from './types'

export const keys = {
  club: ['club'] as const,
  board: (roundId: number) => ['board', roundId] as const,
  events: (roundId: number) => ['events', roundId] as const,
}

export function useClub(enabled: boolean) {
  return useQuery({
    queryKey: keys.club,
    queryFn: api.getClub,
    enabled,
    // 이름 목록은 자주 바뀌지 않는다. 화면으로 돌아올 때만 다시 읽는다.
    staleTime: 30_000,
    retry: (failureCount, error) => !(error instanceof ApiError && error.status === 401) && failureCount < 2,
  })
}

function pollInterval(board: Board | undefined): number {
  if (!board) return LIVE_POLL_MS
  const opensAt = Date.parse(board.round.opensAt)
  const now = serverNow()
  const live = now >= opensAt - LIVE_WINDOW_BEFORE_MS && now <= opensAt + LIVE_WINDOW_AFTER_MS
  return live ? LIVE_POLL_MS : IDLE_POLL_MS
}

/**
 * 현황판을 주기적으로 다시 읽는다.
 * 마지막으로 본 버전을 보내고, 서버가 "그대로"(204)라고 하면 가진 것을 그대로 쓴다.
 * 화면이 가려져 있으면 쉬고, 돌아오면 바로 한 번 읽는다.
 */
export function useBoard(roundId: number | null) {
  const queryClient = useQueryClient()
  return useQuery({
    queryKey: keys.board(roundId ?? 0),
    enabled: roundId !== null,
    queryFn: async () => {
      const id = roundId as number
      const previous = queryClient.getQueryData<Board>(keys.board(id))
      const next = await api.getBoard(id, previous?.round.version)
      if (next) return next
      if (previous) return previous
      // 가진 게 없는데 "그대로"를 받을 일은 없지만, 그래도 전체를 다시 받는다.
      return (await api.getBoard(id)) as Board
    },
    refetchInterval: (query) => pollInterval(query.state.data),
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
    staleTime: 0,
  })
}

export function useEvents(roundId: number, enabled: boolean) {
  return useQuery({
    queryKey: keys.events(roundId),
    queryFn: () => api.getEvents(roundId),
    enabled,
  })
}

/**
 * 현황판을 바꾸는 동작을 실행한다. 서버가 돌려준 새 현황판을 바로 화면에 반영한다.
 * 실패하면 문장을 [error]에 담고 false를 돌려준다. 다른 사람이 먼저 바꿔서 실패한 경우를 위해 현황판도 다시 읽는다.
 */
export function useBoardAction(roundId: number) {
  const queryClient = useQueryClient()
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const run = useCallback(
    async (action: () => Promise<Board>): Promise<boolean> => {
      setPending(true)
      setError(null)
      try {
        queryClient.setQueryData(keys.board(roundId), await action())
        void queryClient.invalidateQueries({ queryKey: keys.events(roundId) })
        return true
      } catch (caught) {
        setError(errorMessage(caught))
        void queryClient.invalidateQueries({ queryKey: keys.board(roundId) })
        return false
      } finally {
        setPending(false)
      }
    },
    [queryClient, roundId],
  )

  return { run, pending, error }
}

/** 서버 시계 기준의 현재 시각을 1초마다 새로 준다. 카운트다운에 쓴다. */
export function useServerNow(intervalMs = 1000): number {
  const [now, setNow] = useState(serverNow)
  useEffect(() => {
    const timer = window.setInterval(() => setNow(serverNow()), intervalMs)
    return () => window.clearInterval(timer)
  }, [intervalMs])
  return now
}
