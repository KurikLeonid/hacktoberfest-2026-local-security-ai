import type { ReactNode } from 'react'
import type { Finding, Tier, Status } from './api'

const tierStyle: Record<Tier, string> = {
  ALLOW: 'bg-emerald-100 text-emerald-800 ring-emerald-300',
  REVIEW: 'bg-amber-100 text-amber-800 ring-amber-300',
  BLOCK: 'bg-rose-100 text-rose-800 ring-rose-300',
}

export function TierBadge({ tier }: { tier: Tier }) {
  return <span className={`rounded px-2 py-0.5 text-xs font-semibold ring-1 ${tierStyle[tier]}`}>{tier}</span>
}

const statusLabel: Record<Status, string> = {
  allowed: 'пропущен',
  pending: 'ждёт решения',
  blocked: 'заблокирован',
  approved: 'одобрен',
  rejected: 'отклонён',
  expired: 'истёк таймаут',
}

export function StatusText({ status }: { status: Status }) {
  return <span className="text-xs text-slate-500">{statusLabel[status]}</span>
}

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <div className={`rounded-lg border border-slate-200 bg-white p-4 shadow-sm ${className}`}>{children}</div>
}

export function Button({
  children,
  onClick,
  kind = 'default',
  disabled,
}: {
  children: ReactNode
  onClick?: () => void
  kind?: 'default' | 'primary' | 'danger' | 'success'
  disabled?: boolean
}) {
  const styles = {
    default: 'bg-white text-slate-700 ring-1 ring-slate-300 hover:bg-slate-50',
    primary: 'bg-indigo-600 text-white hover:bg-indigo-500',
    danger: 'bg-rose-600 text-white hover:bg-rose-500',
    success: 'bg-emerald-600 text-white hover:bg-emerald-500',
  }[kind]
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`rounded-md px-3 py-1.5 text-sm font-medium disabled:opacity-50 ${styles}`}
    >
      {children}
    </button>
  )
}

function findingClass(f: Finding) {
  if (f.allowed) return 'bg-emerald-200/70'
  if (f.is_sensitive === false) return 'bg-slate-200 line-through decoration-slate-400'
  return 'bg-rose-200 font-semibold text-rose-900'
}

/** Text with detected spans highlighted: red = violation, green = allowed for domain, grey = dismissed by verifier. */
export function Highlighted({ text, findings }: { text: string; findings: Finding[] }) {
  const spans = findings
    .filter((f) => f.start != null && f.end != null)
    .sort((a, b) => a.start! - b.start!)
  const parts: ReactNode[] = []
  let pos = 0
  spans.forEach((f, i) => {
    if (f.start! < pos) return
    parts.push(text.slice(pos, f.start!))
    parts.push(
      <mark key={i} className={`rounded px-0.5 ${findingClass(f)}`} title={`${f.category}: ${f.verify_reason || f.reason}`}>
        {text.slice(f.start!, f.end!)}
      </mark>,
    )
    pos = f.end!
  })
  parts.push(text.slice(pos))
  return <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded bg-slate-50 p-3 font-mono text-xs leading-5">{parts}</pre>
}

export function FindingsList({ findings }: { findings: Finding[] }) {
  if (!findings.length) return <p className="text-sm text-slate-500">Модель не нашла чувствительных данных.</p>
  return (
    <ul className="space-y-1 text-sm">
      {findings.map((f, i) => (
        <li key={i} className="flex flex-wrap items-baseline gap-2">
          <span className="rounded bg-slate-100 px-1.5 text-xs font-medium">{f.category}</span>
          <code className="text-xs">{f.span.length > 60 ? f.span.slice(0, 60) + '…' : f.span}</code>
          {f.allowed ? (
            <span className="text-xs text-emerald-700">разрешено для домена</span>
          ) : (
            <span className={`text-xs ${f.is_sensitive ? 'text-rose-700' : 'text-slate-500'}`}>
              {f.is_sensitive ? 'нарушение' : 'отклонено верификатором'} · {((f.confidence ?? 0) * 100).toFixed(0)}%
            </span>
          )}
          <span className="w-full pl-1 text-xs text-slate-500">{f.verify_reason || f.reason}</span>
        </li>
      ))}
    </ul>
  )
}

export const fmtTime = (t: number) => new Date(t * 1000).toLocaleTimeString()
