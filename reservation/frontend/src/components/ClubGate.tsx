import { createContext, useContext, useMemo, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, errorMessage } from '../lib/api'
import { useClub } from '../lib/queries'
import { session, useSession } from '../lib/session'
import type { Club, Member } from '../lib/types'

interface ClubContextValue {
  club: Club
  /** 번호로 이름을 찾는다. 담당이 없으면 "없음". */
  memberName: (memberId: number | null) => string
}

const ClubContext = createContext<ClubContextValue | null>(null)
const MeContext = createContext<Member | null>(null)

export function useClubContext(): ClubContextValue {
  const value = useContext(ClubContext)
  if (!value) throw new Error('ClubGate 안에서만 쓸 수 있어요.')
  return value
}

export function useMe(): Member {
  const value = useContext(MeContext)
  if (!value) throw new Error('MemberGate 안에서만 쓸 수 있어요.')
  return value
}

function Message({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <main className="page">
      <div className="center-screen">
        <h1 style={{ fontSize: 27, fontWeight: 800, letterSpacing: '-0.03em', lineHeight: 1.34 }}>{title}</h1>
        {children}
      </div>
    </main>
  )
}

/** 모임 링크로 들어온 사람에게만 안쪽 화면을 보여준다. */
export function ClubGate({ children }: { children: ReactNode }) {
  const { clubToken } = useSession()
  const query = useClub(clubToken !== null)

  const value = useMemo<ClubContextValue | null>(() => {
    if (!query.data) return null
    const names = new Map(query.data.members.map((member) => [member.id, member.name]))
    return {
      club: query.data,
      memberName: (memberId) => (memberId === null ? '없음' : (names.get(memberId) ?? '알 수 없음')),
    }
  }, [query.data])

  if (clubToken === null) {
    return (
      <Message title="모임 링크로 들어와 주세요">
        <p className="lead">카톡방 공지에 올라온 링크를 누르면 바로 열려요.</p>
      </Message>
    )
  }
  if (value) return <ClubContext.Provider value={value}>{children}</ClubContext.Provider>

  if (query.error) {
    const invalid = query.error instanceof ApiError && query.error.code === 'CLUB_TOKEN_INVALID'
    return (
      <Message title={invalid ? '링크가 맞지 않아요' : '불러오지 못했어요'}>
        <p className="lead">{invalid ? '카톡방 공지의 링크를 다시 눌러 주세요.' : errorMessage(query.error)}</p>
        {!invalid && (
          <button type="button" className="btn" onClick={() => void query.refetch()}>
            다시 시도
          </button>
        )}
      </Message>
    )
  }
  return (
    <Message title="불러오는 중이에요">
      <p className="lead">잠시만 기다려 주세요.</p>
    </Message>
  )
}

/** 이름을 고른 사람에게만 안쪽 화면을 보여준다. 고른 이름이 빠졌으면 다시 고르게 한다. */
export function MemberGate({ children }: { children: ReactNode }) {
  const { club } = useClubContext()
  const { memberId } = useSession()
  const me = club.members.find((member) => member.id === memberId && member.active) ?? null

  if (me) return <MeContext.Provider value={me}>{children}</MeContext.Provider>
  return <NamePicker />
}

export function NamePicker() {
  const { club } = useClubContext()
  const active = club.members.filter((member) => member.active)

  return (
    <main className="page">
      <header className="page-head">
        <p className="hint">{club.name}</p>
        <h1>이름을 골라 주세요</h1>
        <p className="lead">한 번만 고르면 다음부터는 바로 열려요.</p>
      </header>
      {active.length > 0 ? (
        <div className="name-grid">
          {active.map((member) => (
            <button key={member.id} type="button" className="name-btn" onClick={() => session.setMemberId(member.id)}>
              {member.name}
            </button>
          ))}
        </div>
      ) : (
        <div className="note-box">아직 등록된 이름이 없어요. 총무가 이름을 넣으면 여기에 보여요.</div>
      )}
      <p className="hint">내 이름이 없으면 총무에게 알려 주세요.</p>
      <Link to="/admin" className="link-btn" style={{ alignSelf: 'flex-start' }}>
        총무 관리 화면
      </Link>
    </main>
  )
}
