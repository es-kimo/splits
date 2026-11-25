import { useState } from 'react'
import { api } from '../lib/api'
import { bookingLinkFor, type SlotView } from '../lib/boardView'
import { COURTS, SLOT_HOURS, START_HOURS } from '../lib/config'
import { courtPrefLabel, dateLabel, hoursLabel } from '../lib/dates'
import { useBoardAction } from '../lib/queries'
import type { Board, Member, Reservation } from '../lib/types'
import { useClubContext, useMe } from './ClubGate'
import { Sheet } from './Sheet'
import { useToast } from './Toast'

export type SlotSheetMode = 'menu' | 'secure' | 'fail'

interface SlotSheetProps {
  board: Board
  slot: SlotView
  initialMode?: SlotSheetMode
  onClose: () => void
}

function courtOptions(extra: number | null): number[] {
  const set = new Set<number>(COURTS)
  if (extra !== null) set.add(extra)
  return [...set].sort((a, b) => a - b)
}

function CourtPicker({ value, options, onChange }: { value: number; options: number[]; onChange: (court: number) => void }) {
  return (
    <div className="field">
      <span>어느 코트를 잡았나요?</span>
      <div className="chip-row">
        {options.map((court) => (
          <button
            key={court}
            type="button"
            className={`chip${court === value ? ' is-active' : ''}`}
            aria-pressed={court === value}
            onClick={() => onChange(court)}
          >
            {court}번
          </button>
        ))}
      </div>
    </div>
  )
}

function BookerPicker({ value, members, onChange }: { value: number; members: Member[]; onChange: (id: number) => void }) {
  return (
    <label className="field">
      <span>누구 이름으로 예약했나요?</span>
      <select className="select" value={value} onChange={(event) => onChange(Number(event.target.value))}>
        {members.map((member) => (
          <option key={member.id} value={member.id}>
            {member.name}
          </option>
        ))}
      </select>
    </label>
  )
}

/** 슬롯 하나를 눌렀을 때 뜨는 창. 예약 보고, 실패 보고, 담당 넘겨받기, 취소 표시를 여기서 한다. */
export function SlotSheet({ board, slot, initialMode = 'menu', onClose }: SlotSheetProps) {
  const { club, memberName } = useClubContext()
  const me = useMe()
  const toast = useToast()
  const { run, pending, error } = useBoardAction(board.round.id)
  const [mode, setMode] = useState<SlotSheetMode>(initialMode)
  const [courtNo, setCourtNo] = useState<number>(slot.courtPref ?? COURTS[0])
  const [bookerId, setBookerId] = useState<number>(me.id)

  const roundId = board.round.id
  const link = bookingLinkFor(board, slot.courtPref)
  const activeMembers = club.members.filter((member) => member.active)
  const title = `${dateLabel(slot.playDate)} ${hoursLabel(slot.startHour, slot.endHour)}`
  const subtitle = `계획 ${slot.slotNo}번 · ${courtPrefLabel(slot.courtPref)} · 담당 ${memberName(slot.assigneeMemberId)}`

  const finish = async (action: () => Promise<Board>, message: string) => {
    if (await run(action)) {
      toast(message)
      onClose()
    }
  }

  const secure = () =>
    finish(
      () =>
        api.createReservation(roundId, {
          slotId: slot.id,
          playDate: slot.playDate,
          startHour: slot.startHour,
          endHour: slot.endHour,
          courtNo,
          bookerMemberId: bookerId,
        }),
      '확보로 등록했어요.',
    )

  const cancel = (reservation: Reservation) => {
    const ok = window.confirm('예약 사이트에서 실제로 취소한 뒤에 눌러 주세요.\n이 예약을 취소로 표시할까요?')
    if (ok) void finish(() => api.cancelReservation(roundId, reservation.id), '취소로 표시했어요.')
  }

  return (
    <Sheet title={title} subtitle={subtitle} onClose={onClose}>
      {error && (
        <div className="note-box is-danger" role="alert">
          {error}
        </div>
      )}

      {slot.reservation ? (
        <>
          <div className="note-box">
            <b>{memberName(slot.reservation.bookerMemberId)}</b>님이 <b>{slot.reservation.courtNo}번 코트</b>를 잡았어요.
            {slot.reservation.reportedByMemberId !== slot.reservation.bookerMemberId && (
              <> ({memberName(slot.reservation.reportedByMemberId)}님이 대신 입력)</>
            )}
          </div>
          <button type="button" className="btn is-danger is-block" disabled={pending} onClick={() => cancel(slot.reservation as Reservation)}>
            예약을 취소했어요
          </button>
        </>
      ) : mode === 'secure' ? (
        <>
          <CourtPicker value={courtNo} options={courtOptions(slot.courtPref)} onChange={setCourtNo} />
          <BookerPicker value={bookerId} members={activeMembers} onChange={setBookerId} />
          <button type="button" className="btn is-point is-block" disabled={pending} onClick={() => void secure()}>
            확보로 등록하기
          </button>
          <button type="button" className="btn is-ghost is-block" disabled={pending} onClick={() => setMode('menu')}>
            뒤로
          </button>
        </>
      ) : mode === 'fail' ? (
        <>
          <p className="lead">어떤 상황인지 알려 주세요.</p>
          <button
            type="button"
            className="btn is-block"
            disabled={pending}
            onClick={() => void finish(() => api.reportFail(roundId, slot.id, 'CLOSED'), '마감으로 표시했어요.')}
          >
            이미 마감됐어요
          </button>
          <button
            type="button"
            className="btn is-ghost is-block"
            disabled={pending}
            onClick={() => void finish(() => api.reportFail(roundId, slot.id, 'NEED_HELP'), '도움 필요로 올렸어요.')}
          >
            아직 열려 있는데 제가 못 해요
          </button>
          <button type="button" className="btn is-ghost is-block" disabled={pending} onClick={() => setMode('menu')}>
            뒤로
          </button>
        </>
      ) : (
        <>
          {link && (
            <a className="btn is-ghost is-block" href={link} target="_blank" rel="noopener noreferrer">
              예약 페이지 열기
            </a>
          )}
          <button type="button" className="btn is-point is-block" disabled={pending} onClick={() => setMode('secure')}>
            예약했어요
          </button>
          <button type="button" className="btn is-ghost is-block" disabled={pending} onClick={() => setMode('fail')}>
            못 잡았어요
          </button>
          {slot.assigneeMemberId !== me.id && (
            <button
              type="button"
              className="btn is-ghost is-block"
              disabled={pending}
              onClick={() => void finish(() => api.setAssignee(roundId, slot.id, me.id), '담당을 넘겨받았어요.')}
            >
              제가 맡을게요
            </button>
          )}
          {(slot.state === 'CLOSED' || slot.state === 'NEED_HELP') && (
            <button
              type="button"
              className="btn is-ghost is-block"
              disabled={pending}
              onClick={() => void finish(() => api.clearFail(roundId, slot.id), '보고를 되돌렸어요.')}
            >
              {slot.state === 'CLOSED' ? '마감 표시 되돌리기' : '도움 요청 되돌리기'}
            </button>
          )}
        </>
      )}
    </Sheet>
  )
}

/** 계획에 없는 예약을 잡았을 때 넣는 창. */
export function ExtraReservationSheet({ board, onClose }: { board: Board; onClose: () => void }) {
  const { club } = useClubContext()
  const me = useMe()
  const toast = useToast()
  const { run, pending, error } = useBoardAction(board.round.id)
  const [playDate, setPlayDate] = useState('')
  const [startHour, setStartHour] = useState<number>(START_HOURS[0])
  const [courtNo, setCourtNo] = useState<number>(COURTS[0])
  const [bookerId, setBookerId] = useState<number>(me.id)

  const submit = async () => {
    const ok = await run(() =>
      api.createReservation(board.round.id, {
        slotId: null,
        playDate,
        startHour,
        endHour: startHour + SLOT_HOURS,
        courtNo,
        bookerMemberId: bookerId,
      }),
    )
    if (ok) {
      toast('예약을 등록했어요.')
      onClose()
    }
  }

  return (
    <Sheet title="다른 예약 넣기" subtitle="계획에 없는 시간을 잡았을 때 넣어 주세요." onClose={onClose}>
      {error && (
        <div className="note-box is-danger" role="alert">
          {error}
        </div>
      )}
      <label className="field">
        <span>날짜</span>
        <input className="input" type="date" value={playDate} onChange={(event) => setPlayDate(event.target.value)} />
      </label>
      <div className="field">
        <span>시간</span>
        <div className="chip-row">
          {START_HOURS.map((hour) => (
            <button
              key={hour}
              type="button"
              className={`chip${hour === startHour ? ' is-active' : ''}`}
              aria-pressed={hour === startHour}
              onClick={() => setStartHour(hour)}
            >
              {hour}~{hour + SLOT_HOURS}시
            </button>
          ))}
        </div>
      </div>
      <CourtPicker value={courtNo} options={courtOptions(null)} onChange={setCourtNo} />
      <BookerPicker value={bookerId} members={club.members.filter((member) => member.active)} onChange={setBookerId} />
      <button type="button" className="btn is-point is-block" disabled={pending || playDate === ''} onClick={() => void submit()}>
        등록하기
      </button>
    </Sheet>
  )
}

/** 계획 외 예약 하나를 눌렀을 때. 취소 표시만 할 수 있다. */
export function ExtraReservationDetailSheet({ board, reservation, onClose }: { board: Board; reservation: Reservation; onClose: () => void }) {
  const { memberName } = useClubContext()
  const toast = useToast()
  const { run, pending, error } = useBoardAction(board.round.id)

  const cancel = async () => {
    if (!window.confirm('예약 사이트에서 실제로 취소한 뒤에 눌러 주세요.\n이 예약을 취소로 표시할까요?')) return
    if (await run(() => api.cancelReservation(board.round.id, reservation.id))) {
      toast('취소로 표시했어요.')
      onClose()
    }
  }

  return (
    <Sheet
      title={`${dateLabel(reservation.playDate)} ${hoursLabel(reservation.startHour, reservation.endHour)}`}
      subtitle={`${reservation.courtNo}번 코트 · 예약 ${memberName(reservation.bookerMemberId)}`}
      onClose={onClose}
    >
      {error && (
        <div className="note-box is-danger" role="alert">
          {error}
        </div>
      )}
      <div className="note-box">계획에 없던 예약이에요. 쓰지 않을 예약이면 예약 사이트에서 취소해 다른 분이 쓸 수 있게 해 주세요.</div>
      <button type="button" className="btn is-danger is-block" disabled={pending} onClick={() => void cancel()}>
        예약을 취소했어요
      </button>
    </Sheet>
  )
}
