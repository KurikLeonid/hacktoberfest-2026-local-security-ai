import { useEffect, useState } from 'react'
import { api, type DlpEvent } from '../api'
import { Button, Card, FindingsList, Highlighted, PurposeTag, StatusText, TierBadge, fmtTime } from '../ui'

function Countdown({ ev, timeout }: { ev: DlpEvent; timeout: number }) {
  const [now, setNow] = useState(Date.now() / 1000)
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now() / 1000), 250)
    return () => clearInterval(t)
  }, [])
  const left = Math.max(0, Math.ceil(ev.created_at + timeout - now))
  const pct = (left / timeout) * 100
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-32 overflow-hidden rounded bg-slate-200">
        <div className="h-full bg-amber-500 transition-all" style={{ width: `${pct}%` }} />
      </div>
      <span className="font-mono text-xs text-amber-700">{left}s</span>
    </div>
  )
}

export type Thresholds = { review: number; block: number }

/** Model confidence vs the policy thresholds, so it is clear why the request got its tier. */
export function ScoreBar({ score, th }: { score: number; th: Thresholds }) {
  const pct = (v: number) => `${Math.round(v * 100)}%`
  return (
    <div className="mb-3 rounded bg-slate-50 p-2 text-xs">
      <div className="relative mb-1 h-2.5 overflow-hidden rounded">
        <div className="absolute inset-y-0 left-0 bg-emerald-300" style={{ width: pct(th.review) }} />
        <div className="absolute inset-y-0 bg-amber-300" style={{ left: pct(th.review), width: pct(th.block - th.review) }} />
        <div className="absolute inset-y-0 right-0 bg-rose-300" style={{ left: pct(th.block) }} />
        <div className="absolute inset-y-0 w-1 -translate-x-1/2 bg-slate-900" style={{ left: pct(Math.min(score, 0.995)) }} />
      </div>
      <span className="font-semibold">Уверенность модели в нарушении: {pct(score)}</span>
      <span className="text-slate-500">
        {' '}· пороги: REVIEW ≥ {pct(th.review)}, BLOCK ≥ {pct(th.block)}
      </span>
    </div>
  )
}

export function EventCard({
  ev,
  timeout,
  th,
  onDecided,
}: {
  ev: DlpEvent
  timeout: number
  th: Thresholds
  onDecided?: (n: number) => void
}) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const decide = async (d: 'approve' | 'reject') => {
    setBusy(true)
    setErr('')
    try {
      const r = await api.decide(ev.id, d)
      onDecided?.(r.dataset_rows_added)
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusy(false)
    }
  }
  const pending = ev.status === 'pending'
  const reviewable = pending || ev.status === 'blocked' || ev.status === 'expired'
  return (
    <Card className={pending ? 'border-amber-300 ring-2 ring-amber-200' : ''}>
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <TierBadge tier={ev.tier} />
        <span className="font-medium">{ev.host}</span>
        <span className="text-xs text-slate-500">
          {ev.adapter} · {fmtTime(ev.created_at)}
          {ev.latency_ms != null && ` · ${(ev.latency_ms / 1000).toFixed(1)}s`}
        </span>
        <StatusText status={ev.status} />
        <PurposeTag purpose={ev.purpose} />
        {pending && <Countdown ev={ev} timeout={timeout} />}
      </div>
      {ev.error ? (
        <p className="mb-2 rounded bg-rose-50 p-2 text-sm text-rose-700">Fail-closed: {ev.error}</p>
      ) : (
        <ScoreBar score={ev.score} th={th} />
      )}
      <Highlighted text={ev.text} findings={ev.findings} />
      <div className="mt-3">
        <FindingsList findings={ev.findings} />
      </div>
      {reviewable && (
        <div className="mt-4 flex items-center gap-2">
          {pending ? (
            <>
              <Button kind="success" disabled={busy} onClick={() => decide('approve')}>
                Approve: пропустить
              </Button>
              <Button kind="danger" disabled={busy} onClick={() => decide('reject')}>
                Reject: заблокировать
              </Button>
            </>
          ) : (
            <>
              <Button disabled={busy} onClick={() => decide('approve')}>
                False positive
              </Button>
              <Button kind="danger" disabled={busy} onClick={() => decide('reject')}>
                Подтвердить блок
              </Button>
            </>
          )}
          <span className="text-xs text-slate-500">решение попадёт в датасет</span>
          {err && <span className="text-xs text-rose-600">{err}</span>}
        </div>
      )}
    </Card>
  )
}

export default function Queue({ events, timeout, th }: { events: DlpEvent[]; timeout: number; th: Thresholds }) {
  const [toast, setToast] = useState('')
  const open = events.filter((e) => ['pending', 'blocked', 'expired'].includes(e.status))
  const pending = open.filter((e) => e.status === 'pending')
  const rest = open.filter((e) => e.status !== 'pending')
  const onDecided = (n: number) => {
    setToast(`В датасет добавлено примеров: ${n}`)
    setTimeout(() => setToast(''), 3000)
  }
  return (
    <div className="space-y-4">
      {toast && <div className="fixed right-6 bottom-6 rounded bg-slate-900 px-4 py-2 text-sm text-white shadow">{toast}</div>}
      <h2 className="text-lg font-semibold">Ждут решения ({pending.length})</h2>
      {pending.length === 0 && <p className="text-sm text-slate-500">Нет запросов на проверке.</p>}
      {pending.map((e) => (
        <EventCard key={e.id} ev={e} timeout={timeout} th={th} onDecided={onDecided} />
      ))}
      <h2 className="pt-4 text-lg font-semibold">Заблокировано, не разобрано ({rest.length})</h2>
      {rest.map((e) => (
        <EventCard key={e.id} ev={e} timeout={timeout} th={th} onDecided={onDecided} />
      ))}
    </div>
  )
}
