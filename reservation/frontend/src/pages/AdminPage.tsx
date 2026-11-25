import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useMemo, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { useClubContext } from '../components/ClubGate'
import { useToast } from '../components/Toast'
import { ApiError, api, errorMessage } from '../lib/api'
import { copyText } from '../lib/clipboard'
import { COURTS } from '../lib/config'
import { courtPrefLabel, dateLabel, hoursLabel } from '../lib/dates'
import { NO_ASSIGNEE_NAME, formatPlan, parsePlan, type PlanParseResult } from '../lib/planParser'
import { keys, useBoard } from '../lib/queries'
import { session, useSession } from '../lib/session'
import type { Board, PlanItem } from '../lib/types'

export function AdminPage() {
  const { club } = useClubContext()
  const { adminToken } = useSession()

  return (
    <>
      <div className="topbar">
        <div className="topbar-inner">
          <span className="topbar-title">{club.name} · 총무</span>
          <Link to="/" className="link-btn">
            현황판으로
          </Link>
        </div>
      </div>
      <main className="page">{adminToken ? <AdminContent /> : <PinForm />}</main>
    </>
  )
}

/** 총무 동작을 실행한다. 토큰이 만료됐으면 PIN 입력으로 돌려보낸다. */
function useAdminAction() {
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const run = useCallback(async <T,>(action: () => Promise<T>): Promise<T | undefined> => {
    setPending(true)
    setError(null)
    try {
      return await action()
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === 'ADMIN_TOKEN_INVALID') session.setAdminToken(null)
      setError(errorMessage(caught))
      return undefined
    } finally {
      setPending(false)
    }
  }, [])

  return { run, pending, error }
}

function ErrorBox({ message }: { message: string | null }) {
  if (!message) return null
  return (
    <div className="note-box is-danger" role="alert">
      {message}
    </div>
  )
}

function PinForm() {
  const [pin, setPin] = useState('')
  const { run, pending, error } = useAdminAction()

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    const token = await run(() => api.adminLogin(pin))
    if (token) session.setAdminToken(token)
  }

  return (
    <form className="center-screen" onSubmit={(event) => void submit(event)}>
      <h1 style={{ fontSize: 27, fontWeight: 800, letterSpacing: '-0.03em' }}>총무 PIN을 넣어 주세요</h1>
      <p className="lead">계획과 모임원을 고칠 때만 필요해요.</p>
      <ErrorBox message={error} />
      <input
        className="input"
        type="password"
        inputMode="numeric"
        autoComplete="off"
        aria-label="총무 PIN"
        value={pin}
        onChange={(event) => setPin(event.target.value)}
      />
      <button type="submit" className="btn is-block" disabled={pending || pin.length < 4}>
        확인
      </button>
    </form>
  )
}

function AdminContent() {
  const { club } = useClubContext()
  const [roundId, setRoundId] = useState<number | 'new' | null>(club.currentRoundId ?? 'new')
  const selected = typeof roundId === 'number' && club.rounds.some((round) => round.id === roundId) ? roundId : null
  const board = useBoard(selected).data

  return (
    <>
      <header className="page-head">
        <h1>총무 관리</h1>
      </header>
      <LinkSection />
      <MembersSection />
      <section className="card" aria-label="회차 선택">
        <label className="field">
          <span>고칠 회차</span>
          <select
            className="select"
            value={selected ?? 'new'}
            onChange={(event) => setRoundId(event.target.value === 'new' ? 'new' : Number(event.target.value))}
          >
            {club.rounds.map((round) => (
              <option key={round.id} value={round.id}>
                {round.title}
              </option>
            ))}
            <option value="new">새 회차 만들기</option>
          </select>
        </label>
      </section>
      {selected === null ? (
        <RoundSection key="new" board={null} onSaved={setRoundId} />
      ) : board && board.round.id === selected ? (
        <>
          <RoundSection key={`round-${selected}`} board={board} onSaved={setRoundId} />
          <PlanSection key={`plan-${selected}`} board={board} />
        </>
      ) : (
        <p className="hint">회차를 불러오는 중이에요.</p>
      )}
      <button type="button" className="link-btn" style={{ alignSelf: 'center' }} onClick={() => session.setAdminToken(null)}>
        총무 화면 잠그기
      </button>
    </>
  )
}

function LinkSection() {
  const { clubToken } = useSession()
  const toast = useToast()
  const link = `${window.location.origin}/g/${clubToken ?? ''}`

  return (
    <section className="card" aria-label="모임 링크">
      <div className="card-head">
        <h2>모임 링크</h2>
      </div>
      <div className="stack">
        <p className="hint">이 링크를 아는 사람은 누구나 현황을 보고 바꿀 수 있어요. 모임 카톡방에만 올려 주세요.</p>
        <button
          type="button"
          className="btn is-ghost is-block"
          onClick={() => void copyText(link).then((ok) => toast(ok ? '링크를 복사했어요.' : '복사하지 못했어요.', ok ? 'info' : 'error'))}
        >
          링크 복사
        </button>
      </div>
    </section>
  )
}

function MembersSection() {
  const { club } = useClubContext()
  const queryClient = useQueryClient()
  const { run, pending, error } = useAdminAction()
  const [name, setName] = useState('')
  const refresh = () => queryClient.invalidateQueries({ queryKey: keys.club })

  const add = async (event: FormEvent) => {
    event.preventDefault()
    if ((await run(() => api.addMember(name))) !== undefined) {
      setName('')
      await refresh()
    }
  }

  const rename = async (memberId: number, current: string) => {
    const next = window.prompt('새 이름을 적어 주세요.', current)?.trim()
    if (!next || next === current) return
    if ((await run(() => api.updateMember(memberId, { name: next }))) !== undefined) await refresh()
  }

  const setActive = async (memberId: number, active: boolean) => {
    if ((await run(() => api.updateMember(memberId, { active }))) !== undefined) await refresh()
  }

  return (
    <section className="card" aria-label="모임원">
      <div className="card-head">
        <h2>모임원</h2>
        <span className="count">{club.members.filter((member) => member.active).length}명</span>
      </div>
      <div className="stack">
        <ErrorBox message={error} />
        {club.members.map((member) => (
          <div key={member.id} className="row">
            <span className="grow" style={{ fontWeight: 700, color: member.active ? undefined : 'var(--faint-2)' }}>
              {member.name}
              {!member.active && ' (빠짐)'}
            </span>
            <button type="button" className="btn is-ghost is-small" disabled={pending} onClick={() => void rename(member.id, member.name)}>
              이름 고치기
            </button>
            <button type="button" className="btn is-ghost is-small" disabled={pending} onClick={() => void setActive(member.id, !member.active)}>
              {member.active ? '빼기' : '되살리기'}
            </button>
          </div>
        ))}
        <form className="row" onSubmit={(event) => void add(event)}>
          <input className="input grow" placeholder="이름" aria-label="추가할 이름" value={name} onChange={(event) => setName(event.target.value)} />
          <button type="submit" className="btn" disabled={pending || name.trim() === ''}>
            추가
          </button>
        </form>
      </div>
    </section>
  )
}

function RoundSection({ board, onSaved }: { board: Board | null; onSaved: (roundId: number) => void }) {
  const queryClient = useQueryClient()
  const toast = useToast()
  const { run, pending, error } = useAdminAction()
  const round = board?.round ?? null
  const [title, setTitle] = useState(round?.title ?? '')
  // 서버는 항상 한국 시간(+09:00)으로 내려주므로 앞 16자가 곧 입력창 값이다.
  const [opensAt, setOpensAt] = useState(round?.opensAt.slice(0, 16) ?? '')
  const [bookingUrl, setBookingUrl] = useState(round?.bookingUrl ?? '')
  const [courtLinks, setCourtLinks] = useState<Record<string, string>>(() =>
    Object.fromEntries(COURTS.map((court) => [String(court), round?.courtLinks[String(court)] ?? ''])),
  )

  const save = async (event: FormEvent) => {
    event.preventDefault()
    const input = { title, opensAt, bookingUrl, courtLinks }
    const saved = await run(() => (round ? api.updateRound(round.id, input) : api.createRound(input)))
    if (!saved) return
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: keys.club }),
      queryClient.invalidateQueries({ queryKey: keys.board(saved.id) }),
    ])
    toast(round ? '회차를 고쳤어요.' : '회차를 만들었어요.')
    onSaved(saved.id)
  }

  return (
    <section className="card" aria-label="회차 정보">
      <div className="card-head">
        <h2>{round ? '회차 정보' : '새 회차'}</h2>
      </div>
      <form className="stack" onSubmit={(event) => void save(event)}>
        <ErrorBox message={error} />
        <label className="field">
          <span>이름</span>
          <input className="input" placeholder="예: 1월 신정교 예약" value={title} onChange={(event) => setTitle(event.target.value)} />
        </label>
        <label className="field">
          <span>예약이 열리는 일시</span>
          <input className="input" type="datetime-local" value={opensAt} onChange={(event) => setOpensAt(event.target.value)} />
        </label>
        <label className="field">
          <span>예약 사이트 주소</span>
          <input className="input" type="url" inputMode="url" placeholder="https://" value={bookingUrl} onChange={(event) => setBookingUrl(event.target.value)} />
        </label>
        {COURTS.map((court) => (
          <label key={court} className="field">
            <span>{court}번 코트 예약 페이지 주소 (없으면 비워 두세요)</span>
            <input
              className="input"
              type="url"
              inputMode="url"
              placeholder="https://"
              value={courtLinks[String(court)] ?? ''}
              onChange={(event) => setCourtLinks({ ...courtLinks, [String(court)]: event.target.value })}
            />
          </label>
        ))}
        <button type="submit" className="btn is-block" disabled={pending || title.trim() === '' || opensAt === ''}>
          {round ? '회차 정보 저장' : '회차 만들기'}
        </button>
      </form>
    </section>
  )
}

function PlanSection({ board }: { board: Board }) {
  const { club, memberName } = useClubContext()
  const queryClient = useQueryClient()
  const toast = useToast()
  const { run, pending, error } = useAdminAction()

  const initialText = useMemo(
    () =>
      formatPlan(
        board.slots.map((slot) => ({
          slotNo: slot.slotNo,
          playDate: slot.playDate,
          startHour: slot.startHour,
          endHour: slot.endHour,
          courtPref: slot.courtPref,
          assigneeName: slot.assigneeMemberId === null ? null : memberName(slot.assigneeMemberId),
        })),
      ),
    // 처음 열 때의 계획만 글로 옮긴다. 이후에는 사용자가 고치는 글이 기준이다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  )
  const [text, setText] = useState(initialText)
  const [preview, setPreview] = useState<PlanParseResult | null>(null)

  const base = useMemo(() => {
    const [year, month] = board.round.opensAt.split('-').map(Number)
    return { year, month }
  }, [board.round.opensAt])

  const idByName = useMemo(
    () => new Map(club.members.filter((member) => member.active).map((member) => [member.name, member.id])),
    [club.members],
  )
  const unknownNames = useMemo(() => {
    if (!preview) return []
    const names = preview.lines.map((line) => line.name).filter((name) => name !== NO_ASSIGNEE_NAME && !idByName.has(name))
    return [...new Set(names)]
  }, [preview, idByName])

  const addMembers = async () => {
    for (const name of unknownNames) {
      if ((await run(() => api.addMember(name))) === undefined) break
    }
    await queryClient.invalidateQueries({ queryKey: keys.club })
  }

  const save = async () => {
    if (!preview) return
    const items: PlanItem[] = preview.lines.map((line) => ({
      slotNo: line.slotNo,
      playDate: line.playDate,
      startHour: line.startHour,
      endHour: line.endHour,
      courtPref: line.courtPref,
      assigneeMemberId: idByName.get(line.name) ?? null,
    }))
    const saved = await run(() => api.savePlan(board.round.id, items))
    if (!saved) return
    queryClient.setQueryData(keys.board(board.round.id), saved)
    toast(`계획 ${items.length}건을 저장했어요.`)
    setPreview(null)
  }

  const canSave = preview !== null && preview.errors.length === 0 && unknownNames.length === 0

  return (
    <section className="card" aria-label="계획">
      <div className="card-head">
        <h2>계획</h2>
        <span className="count">저장된 {board.slots.length}건</span>
      </div>
      <div className="stack">
        <p className="hint">
          카톡 공지에 쓰던 형식 그대로 붙여넣으면 돼요. 번호가 같은 줄은 고쳐지고, 여기 없는 번호는 지워져요. 이미 등록된 예약은 지워지지 않아요.
        </p>
        <textarea
          className="textarea"
          aria-label="계획"
          placeholder={'1. 이름 : [3번코트] 12/5(토) 16~18시\n2. 이름 : [아무코트] 12/27(일) 10~12시'}
          value={text}
          onChange={(event) => {
            setText(event.target.value)
            setPreview(null)
          }}
        />
        <button type="button" className="btn is-ghost is-block" onClick={() => setPreview(parsePlan(text, base))}>
          읽어 보기
        </button>

        <ErrorBox message={error} />

        {preview && (
          <>
            {preview.errors.length > 0 && (
              <div className="note-box is-danger" role="alert">
                <b>읽지 못한 줄이 {preview.errors.length}개 있어요.</b>
                {preview.errors.map((item) => (
                  <p key={item.lineNo}>
                    {item.lineNo}번째 줄: {item.reason}
                  </p>
                ))}
              </div>
            )}
            {unknownNames.length > 0 && (
              <div className="note-box is-danger" role="alert">
                <p>
                  <b>모임원에 없는 이름이에요: {unknownNames.join(', ')}</b>
                </p>
                <p>오타면 위에서 고치고, 새로 온 분이면 추가해 주세요.</p>
                <button type="button" className="btn is-small" style={{ marginTop: 8 }} disabled={pending} onClick={() => void addMembers()}>
                  {unknownNames.length}명을 모임원으로 추가
                </button>
              </div>
            )}
            <table className="table">
              <thead>
                <tr>
                  <th className="num">번호</th>
                  <th>시간</th>
                  <th>코트</th>
                  <th>담당</th>
                </tr>
              </thead>
              <tbody>
                {preview.lines.map((line) => (
                  <tr key={line.slotNo}>
                    <td className="num">{line.slotNo}</td>
                    <td>
                      {dateLabel(line.playDate)} {hoursLabel(line.startHour, line.endHour)}
                      {line.warnings.map((warning) => (
                        <p key={warning} style={{ color: 'var(--danger)' }}>
                          {warning}
                        </p>
                      ))}
                    </td>
                    <td>{courtPrefLabel(line.courtPref)}</td>
                    <td>{line.name === NO_ASSIGNEE_NAME ? '없음' : line.name}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="hint">
              {preview.lines.length}건 · 담당 {new Set(preview.lines.map((line) => line.name).filter((name) => name !== NO_ASSIGNEE_NAME)).size}명
            </p>
            <button type="button" className="btn is-point is-block" disabled={pending || !canSave} onClick={() => void save()}>
              이대로 저장
            </button>
          </>
        )}
      </div>
    </section>
  )
}
