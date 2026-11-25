import { useEffect } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { session } from '../lib/session'

/**
 * 카톡방에 올린 모임 링크(/g/토큰)의 도착점.
 * 토큰을 이 기기에 저장하고 주소창에서 지운 뒤 현황판으로 보낸다.
 * 주소에 토큰이 남아 있으면 화면을 캡처하거나 주소를 복사할 때 같이 퍼진다.
 */
export function JoinPage() {
  const { token } = useParams()
  const navigate = useNavigate()

  useEffect(() => {
    if (token) session.setClubToken(token)
    navigate('/', { replace: true })
  }, [token, navigate])

  return null
}
