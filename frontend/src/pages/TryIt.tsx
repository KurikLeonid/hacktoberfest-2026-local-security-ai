import { useState } from 'react'
import { api, type Finding, type Tier } from '../api'
import { Button, Card, FindingsList, Highlighted, TierBadge } from '../ui'

const SAMPLES = [
  'How do I reverse a linked list in Python?',
  'Please fix this config:\nAWS_ACCESS_KEY_ID=AKIAZ7Q4M2LXR9TB3KUP\nAWS_SECRET_ACCESS_KEY=w9Jx3pQ+r7Lk2mN8vB5cT1yH6dF4gS0aZ/eU2iO8',
  'Draft a polite reply to our customer John Peterson (john.peterson@gmail.com, +1 415 555 0187) about the refund for card 4532 7612 9981 0042.',
  'Review this function from our billing service:\ndef apply_discount(invoice, tier):\n    if tier == "gold":\n        return invoice.total * 0.82\n    return invoice.total',
]

export default function TryIt({ domains }: { domains: string[] }) {
  const [text, setText] = useState(SAMPLES[1])
  const [host, setHost] = useState(domains[0] ?? 'chatgpt.com')
  const [busy, setBusy] = useState(false)
  const [res, setRes] = useState<{ tier: Tier; score: number; findings: Finding[]; latency_ms?: number; error?: string; text: string } | null>(null)
  const run = async () => {
    setBusy(true)
    try {
      setRes({ ...(await api.classify(text, host)), text })
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <h2 className="mb-2 font-semibold">Проверить текст без прокси</h2>
        <div className="mb-2 flex flex-wrap gap-1">
          {SAMPLES.map((s, i) => (
            <button key={i} className="rounded bg-slate-100 px-2 py-0.5 text-xs hover:bg-slate-200" onClick={() => setText(s)}>
              пример {i + 1}
            </button>
          ))}
        </div>
        <textarea className="h-48 w-full rounded border border-slate-300 p-2 font-mono text-xs" value={text} onChange={(e) => setText(e.target.value)} />
        <div className="mt-2 flex items-center gap-2">
          <span className="text-sm">Куда:</span>
          <input list="domains" className="rounded border border-slate-300 px-2 py-1 text-sm" value={host} onChange={(e) => setHost(e.target.value)} />
          <datalist id="domains">{domains.map((d) => <option key={d} value={d} />)}</datalist>
          <Button kind="primary" disabled={busy} onClick={run}>{busy ? 'Gemma думает…' : 'Проверить'}</Button>
        </div>
      </Card>
      {res && (
        <Card>
          <div className="mb-2 flex items-center gap-2">
            <TierBadge tier={res.tier} />
            <span className="text-sm">score {res.score.toFixed(2)}</span>
            {res.latency_ms != null && <span className="text-xs text-slate-500">{(res.latency_ms / 1000).toFixed(1)}s</span>}
          </div>
          {res.error && <p className="mb-2 text-sm text-rose-600">Fail-closed: {res.error}</p>}
          <Highlighted text={res.text} findings={res.findings} />
          <div className="mt-3"><FindingsList findings={res.findings} /></div>
        </Card>
      )}
    </div>
  )
}
