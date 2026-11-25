import { useEffect, useRef, type ReactNode } from 'react'

interface SheetProps {
  title: string
  subtitle?: string
  onClose: () => void
  children: ReactNode
}

/**
 * 아래에서 올라오는 창. 브라우저의 dialog를 써서 뒤 화면이 눌리지 않고, 뒤로가기·Esc로 닫힌다.
 * 열려 있을 때만 그려서, 닫았다 열면 안의 입력값이 처음으로 돌아간다.
 */
export function Sheet({ title, subtitle, onClose, children }: SheetProps) {
  const ref = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    const dialog = ref.current
    if (dialog && !dialog.open) dialog.showModal()
  }, [])

  return (
    <dialog
      ref={ref}
      className="sheet"
      aria-label={title}
      onClose={onClose}
      onClick={(event) => {
        // 창 바깥(어두운 부분)을 누르면 닫는다.
        if (event.target === ref.current) onClose()
      }}
    >
      <div className="sheet-body">
        <div className="sheet-head">
          <div>
            <h2>{title}</h2>
            {subtitle && <p className="lead">{subtitle}</p>}
          </div>
          <button type="button" className="link-btn" onClick={onClose}>
            닫기
          </button>
        </div>
        {children}
      </div>
    </dialog>
  )
}
