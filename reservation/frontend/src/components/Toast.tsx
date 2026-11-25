import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

type Tone = 'info' | 'error'

interface ToastState {
  id: number
  message: string
  tone: Tone
}

type ShowToast = (message: string, tone?: Tone) => void

const ToastContext = createContext<ShowToast>(() => {})

/** 화면 아래에 잠깐 뜨는 한 줄 알림. 열린 창(dialog) 위로는 올라오지 못하므로, 창 안의 오류는 창 안에 적는다. */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<ToastState | null>(null)

  const show = useCallback<ShowToast>((message, tone = 'info') => {
    setToast({ id: Date.now(), message, tone })
  }, [])

  useEffect(() => {
    if (!toast) return
    const timer = window.setTimeout(() => setToast(null), toast.tone === 'error' ? 5000 : 2800)
    return () => window.clearTimeout(timer)
  }, [toast])

  const value = useMemo(() => show, [show])

  return (
    <ToastContext.Provider value={value}>
      {children}
      {toast && (
        <div key={toast.id} className={`toast${toast.tone === 'error' ? ' is-error' : ''}`} role="status" aria-live="polite">
          {toast.message}
        </div>
      )}
    </ToastContext.Provider>
  )
}

export function useToast(): ShowToast {
  return useContext(ToastContext)
}
