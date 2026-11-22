import { useEffect } from 'react'
import { X } from 'lucide-react'

/**
 * Accessible modal overlay matching the dashboard's dark theme.
 * Renders nothing until `open` is true. Closes on Escape or when clicking the
 * backdrop (outside the panel). Optionally calls onClose via a close button.
 */
const Modal = ({ open, onClose, title, subtitle, children, footer }) => {
  useEffect(() => {
    if (!open) return
    const onKey = (e) => {
      if (e.key === 'Escape') onClose?.()
    }
    document.addEventListener('keydown', onKey)
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = ''
    }
  }, [open, onClose])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-950/70 p-4 backdrop-blur-sm lg:p-8"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={title}
    >
      <div
        className="modal-panel my-auto w-full max-w-2xl rounded-3xl border border-slate-800/80 shadow-2xl shadow-slate-950/70"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4 border-b border-slate-800/80 px-6 py-5">
          <div>
            {title && <h3 className="text-lg font-semibold text-slate-100">{title}</h3>}
            {subtitle && <p className="mt-1 text-sm text-slate-400">{subtitle}</p>}
          </div>
          <button
            className="rounded-xl border border-slate-800 bg-slate-950/70 p-2 text-slate-300 transition hover:bg-slate-800"
            onClick={onClose}
            aria-label="Close"
          >
            <X size={18} />
          </button>
        </div>

        <div className="max-h-[70vh] overflow-y-auto px-6 py-5">{children}</div>

        {footer && <div className="border-t border-slate-800/80 px-6 py-4">{footer}</div>}
      </div>
    </div>
  )
}

export default Modal
