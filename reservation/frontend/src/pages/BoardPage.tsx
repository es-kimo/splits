import { Fragment, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useClubContext, useMe } from '../components/ClubGate'
import { ExtraReservationDetailSheet, ExtraReservationSheet, SlotSheet, type SlotSheetMode } from '../components/SlotSheet'
import { useToast } from '../components/Toast'
import { errorMessage, serverNow } from '../lib/api'
import { bookingLinkFor, buildBoardView, type SlotView } from '../lib/boardView'
import { copyText } from '../lib/clipboard'
import { countdownLabel, courtPrefLabel, dateLabel, hoursLabel, kstTimeLabel } from '../lib/dates'
import { useBoard, useEvents, useServerNow } from '../lib/queries'
import { session } from '../lib/session'
import { buildShareText } from '../lib/shareText'
import type { Board, Reservation, SlotState } from '../lib/types'

const STATE_BADGE: Record<SlotState, { text: string; className: string }> = {
  SECURED: { text: '확보', className: 'badge is-solid' },
  NEED_HELP: { text: '도움 필요', className: 'badge is-danger' },
  CLOSED: { text: '놓침', className: 'badge is-mute' },
  PLANNED: { text: '대기', className: 'badge' },
}

type OpenSheet =
  | { kind: 'slot'; slotId: number; mode: SlotSheetMode }
  | { kind: 'extra' }
  | { kind: 'extraDetail'; reservationId: number }
  | null

export function BoardPage() {
  const { club } = useClubContext()
  const me = useMe()
  const [roundId, setRoundId] = useState<number | null>(club.currentRoundId)
  const activeRoundId = club.rounds.some((round) => round.id === roundId) ? roundId : club.currentRoundId
  const query = useBoard(activeRoundId)

  return (
    <>
      <div className="topbar">
        <div className="topbar-inner">
          <span className="topbar-title">{club.name}</span>
          <button
            type="button"
            className="link-btn"
            onClick={() => {
              if (window.confirm(`${me.name}님이 아니신가요? 이름을 다시 고를게요.`)) session.setMemberId(null)
            }}
          >
            {me.name}님
          </button>
        </div>
      </div>
      <main className="page">
        {club.rounds.length > 1 && (
          <label className="field" style={{ marginTop: 10 }}>
            <span>회차</span>
            <select className="select" value={activeRoundId ?? ''} onChange={(event) => setRoundId(Number(event.target.value))}>
              {club.rounds.map((round) => (
                <option key={round.id} value={round.id}>
                  {round.title}
                </option>
              ))}
            </select>
          </label>
        )}

        {activeRoundId === null ? (
          <div className="center-screen">
            <h1 style={{ fontSize: 27, fontWeight: 800, letterSpacing: '-0.03em' }}>아직 예약 회차가 없어요</h1>
            <p className="lead">총무가 회차와 계획을 넣으면 여기에 보여요.</p>
            <Link to="/admin" className="btn is-ghost">
              총무 관리 화면
            </Link>
          </div>
        ) : query.data ? (
          <BoardContent board={query.data} stale={query.isError} />
        ) : query.error ? (
          <div className="center-screen">
            <h1 style={{ fontSize: 27, fontWeight: 800, letterSpacing: '-0.03em' }}>현황을 불러오지 못했어요</h1>
            <p className="lead">{errorMessage(query.error)}</p>
            <button type="button" className="btn" onClick={() => void query.refetch()}>
              다시 시도
            </button>
          </div>
        ) : (
          <div className="center-screen">
            <p className="lead">현황을 불러오는 중이에요.</p>
          </div>
        )}
      </main>
    </>
  )
}

function BoardContent({ board, stale }: { board: Board; stale: boolean }) {
  const { club, memberName } = useClubContext()
  const me = useMe()
  const toast = useToast()
  const [sheet, setSheet] = useState<OpenSheet>(null)
  const view = useMemo(() => buildBoardView(board, club.members, me.id), [board, club.members, me.id])
  const { summary } = board

  const allSlots = view.byDate.flatMap((group) => group.slots)
  const openSlot = sheet?.kind === 'slot' ? allSlots.find((slot) => slot.id === sheet.slotId) : undefined
  const openReservation =
    sheet?.kind === 'extraDetail' ? board.reservations.find((reservation) => reservation.id === sheet.reservationId) : undefined

  const share = async () => {
    const text = buildShareText({ board, memberName, link: window.location.origin, nowMs: serverNow() })
    if (await copyText(text)) toast('복사했어요. 카톡방에 붙여넣어 주세요.')
    else toast('복사하지 못했어요. 다시 눌러 주세요.', 'error')
  }

  return (
    <>
      <header className="page-head">
        <h1>{board.round.title}</h1>
      </header>

      {stale && <div className="note-box is-danger">연결이 불안정해요. 마지막으로 받은 현황을 보여주고 있어요.</div>}

      <CountdownCard board={board} />

      <section className="card" aria-label="요약">
        <div className="metric-grid">
          <div className="metric is-point">
            <b>
              {summary.secured}/{summary.total}
            </b>
            <span>확보</span>
          </div>
          <div className={`metric${summary.needHelp > 0 ? ' is-danger' : ''}`}>
            <b>{summary.needHelp}</b>
            <span>도움 필요</span>
          </div>
          <div className="metric">
            <b>{summary.closed}</b>
            <span>놓침</span>
          </div>
          <div className="metric">
            <b>{summary.planned}</b>
            <span>대기</span>
          </div>
        </div>
      </section>

      {view.mine.length > 0 && (
        <section className="card is-point" aria-label="내 할 일">
          <div className="card-head">
            <h2>내가 맡은 시간</h2>
            <span className="count">{view.mine.length}건</span>
          </div>
          <div className="stack">
            {view.mine.map((slot) => (
              <TaskCard key={slot.id} board={board} slot={slot} onOpen={(mode) => setSheet({ kind: 'slot', slotId: slot.id, mode })} />
            ))}
          </div>
        </section>
      )}

      {view.needHelp.length > 0 && (
        <section className="card" aria-label="도움 필요">
          <div className="card-head">
            <h2>도와주세요</h2>
            <span className="count">{view.needHelp.length}건</span>
          </div>
          <p className="hint" style={{ marginBottom: 6 }}>
            맡은 분이 못 잡는 시간이에요. 여유가 있으면 대신 잡아 주세요.
          </p>
          <div className="slot-list">
            {view.needHelp.map((slot) => (
              <SlotRow key={slot.id} slot={slot} onOpen={() => setSheet({ kind: 'slot', slotId: slot.id, mode: 'menu' })} />
            ))}
          </div>
        </section>
      )}

      <section className="card" aria-label="전체 계획">
        <div className="card-head">
          <h2>전체 계획</h2>
          <span className="count">{summary.total}건</span>
        </div>
        {view.byDate.length === 0 ? (
          <div className="note-box">아직 계획이 없어요. 총무가 계획을 넣으면 여기에 보여요.</div>
        ) : (
          <div className="slot-list">
            {view.byDate.map((group) => (
              <Fragment key={group.playDate}>
                <h3 className="date-head">{dateLabel(group.playDate)}</h3>
                {group.slots.map((slot) => (
                  <SlotRow key={slot.id} slot={slot} hideDate onOpen={() => setSheet({ kind: 'slot', slotId: slot.id, mode: 'menu' })} />
                ))}
              </Fragment>
            ))}
          </div>
        )}
      </section>

      <section className="card" aria-label="계획에 없던 예약">
        <div className="card-head">
          <h2>계획에 없던 예약</h2>
          <span className="count">{view.unplanned.length}건</span>
        </div>
        {view.unplanned.length > 0 && (
          <div className="slot-list" style={{ marginBottom: 12 }}>
            {view.unplanned.map((reservation) => (
              <ExtraRow
                key={reservation.id}
                reservation={reservation}
                onOpen={() => setSheet({ kind: 'extraDetail', reservationId: reservation.id })}
              />
            ))}
          </div>
        )}
        <button type="button" className="btn is-ghost is-block" onClick={() => setSheet({ kind: 'extra' })}>
          다른 시간을 잡았어요
        </button>
      </section>

      <section className="card" aria-label="사람별 예약">
        <details>
          <summary>사람별 예약 건수</summary>
          <table className="table">
            <thead>
              <tr>
                <th>이름</th>
                <th className="num">주말</th>
                <th className="num">주중</th>
              </tr>
            </thead>
            <tbody>
              {view.people.map((person) => (
                <tr key={person.memberId}>
                  <td>{person.name}</td>
                  <td className="num">{person.weekend}건</td>
                  <td className="num">{person.weekday}건</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="hint" style={{ marginTop: 10 }}>
            예약 사이트에서 예약한 사람 기준이에요.
          </p>
        </details>
      </section>

      <EventsCard roundId={board.round.id} version={board.round.version} />

      <Link to="/admin" className="link-btn" style={{ alignSelf: 'center' }}>
        총무 관리 화면
      </Link>

      <div className="dock">
        <div className="dock-inner">
          <button type="button" className="btn is-block" onClick={() => void share()}>
            카톡에 올릴 결과 복사
          </button>
        </div>
      </div>

      {sheet?.kind === 'slot' && openSlot && (
        <SlotSheet key={`${openSlot.id}-${sheet.mode}`} board={board} slot={openSlot} initialMode={sheet.mode} onClose={() => setSheet(null)} />
      )}
      {sheet?.kind === 'extra' && <ExtraReservationSheet board={board} onClose={() => setSheet(null)} />}
      {sheet?.kind === 'extraDetail' && openReservation && (
        <ExtraReservationDetailSheet board={board} reservation={openReservation} onClose={() => setSheet(null)} />
      )}
    </>
  )
}

function CountdownCard({ board }: { board: Board }) {
  const now = useServerNow()
  const opensAt = Date.parse(board.round.opensAt)
  const remaining = opensAt - now
  const link = board.round.bookingUrl

  // 열린 지 하루가 지나면 더 보여줄 필요가 없다.
  if (remaining < -24 * 60 * 60 * 1000) return null

  return (
    <section className="card" aria-label="예약 시작 시각">
      <div className="stack">
        {remaining > 0 ? (
          <>
            <p className="hint">예약 시작까지 · {kstTimeLabel(opensAt)}</p>
            <p className="countdown" aria-live="off">
              {countdownLabel(remaining)}
            </p>
            <p className="hint">미리 로그인해 두고, 시작 시각에 새로 고침하면 예약 버튼이 보여요.</p>
          </>
        ) : (
          <>
            <p className="countdown">예약이 열렸어요</p>
            <p className="hint">잡았으면 바로 아래에서 알려 주세요. 다른 분들이 같은 시간을 또 잡지 않아요.</p>
          </>
        )}
        {link && (
          <a className="btn is-ghost is-block" href={link} target="_blank" rel="noopener noreferrer">
            예약 사이트 열기
          </a>
        )}
      </div>
    </section>
  )
}

function TaskCard({ board, slot, onOpen }: { board: Board; slot: SlotView; onOpen: (mode: SlotSheetMode) => void }) {
  const link = bookingLinkFor(board, slot.courtPref)
  return (
    <div className="task">
      <div>
        <p className="task-when">
          {dateLabel(slot.playDate)} {hoursLabel(slot.startHour, slot.endHour)}
        </p>
        <p className="slot-sub">
          {/* "3번"만 쓰면 슬롯 번호인지 코트 번호인지 헷갈린다. */}
          계획 {slot.slotNo}번 · {courtPrefLabel(slot.courtPref)}
          {slot.state === 'NEED_HELP' && ' · 도움 요청 중'}
        </p>
      </div>
      {link && (
        <a className="btn is-ghost is-block" href={link} target="_blank" rel="noopener noreferrer">
          {slot.courtPref !== null && board.round.courtLinks[String(slot.courtPref)] ? `${slot.courtPref}번 코트 예약 페이지 열기` : '예약 사이트 열기'}
        </a>
      )}
      <div className="btn-pair">
        <button type="button" className="btn is-point" onClick={() => onOpen('secure')}>
          예약했어요
        </button>
        <button type="button" className="btn is-ghost" onClick={() => onOpen('fail')}>
          못 잡았어요
        </button>
      </div>
    </div>
  )
}

function SlotRow({ slot, hideDate = false, onOpen }: { slot: SlotView; hideDate?: boolean; onOpen: () => void }) {
  const { memberName } = useClubContext()
  const badge = STATE_BADGE[slot.state]
  const when = `${hideDate ? '' : `${dateLabel(slot.playDate)} `}${hoursLabel(slot.startHour, slot.endHour)}`

  return (
    <button type="button" className="slot-row" onClick={onOpen}>
      <span className="slot-no" aria-label={`${slot.slotNo}번`}>
        {slot.slotNo}
      </span>
      <span className="slot-main">
        <span className="slot-when">{when}</span>
        <br />
        <span className="slot-sub">
          {slot.reservation ? (
            <>
              <b>{memberName(slot.reservation.bookerMemberId)}</b> · {slot.reservation.courtNo}번 코트
              {slot.assigneeMemberId !== slot.reservation.bookerMemberId && <> (담당 {memberName(slot.assigneeMemberId)})</>}
            </>
          ) : (
            <>
              {courtPrefLabel(slot.courtPref)} · 담당 {memberName(slot.assigneeMemberId)}
            </>
          )}
        </span>
      </span>
      <span className={badge.className}>{badge.text}</span>
    </button>
  )
}

function ExtraRow({ reservation, onOpen }: { reservation: Reservation; onOpen: () => void }) {
  const { memberName } = useClubContext()
  return (
    <button type="button" className="slot-row" onClick={onOpen}>
      <span className="slot-main">
        <span className="slot-when">
          {dateLabel(reservation.playDate)} {hoursLabel(reservation.startHour, reservation.endHour)}
        </span>
        <br />
        <span className="slot-sub">
          <b>{memberName(reservation.bookerMemberId)}</b> · {reservation.courtNo}번 코트
        </span>
      </span>
      <span className="badge is-point">계획 외</span>
    </button>
  )
}

function EventsCard({ roundId, version }: { roundId: number; version: number }) {
  const [open, setOpen] = useState(false)
  const query = useEvents(roundId, open)

  return (
    <section className="card" aria-label="변경 기록">
      <details
        onToggle={(event) => {
          const next = event.currentTarget.open
          setOpen(next)
          if (next) void query.refetch()
        }}
      >
        <summary>변경 기록</summary>
        {/* 현황판 버전이 바뀌면 key가 바뀌어 목록을 다시 그린다. */}
        <div key={version} className="event-list">
          {query.data?.length === 0 && <p className="hint">아직 기록이 없어요.</p>}
          {query.data?.map((event) => (
            <div key={event.id}>
              <time>{kstTimeLabel(Date.parse(event.createdAt))}</time> · <b>{event.actorName}</b>
              <br />
              {event.detail}
            </div>
          ))}
          {query.isLoading && <p className="hint">불러오는 중이에요.</p>}
          {query.isError && <p className="hint">기록을 불러오지 못했어요.</p>}
        </div>
      </details>
    </section>
  )
}
