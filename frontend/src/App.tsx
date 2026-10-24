import { useCallback, useEffect, useState } from 'react'
import { api, type DlpEvent, type PolicyRaw } from './api'
import Dataset from './pages/Dataset'
import Log from './pages/Log'
import Policies from './pages/Policies'
import Queue from './pages/Queue'
import TryIt from './pages/TryIt'

const TABS = [
  ['queue', 'Очередь'],
  ['log', 'Журнал'],
  ['try', 'Проверить текст'],
  ['policies', 'Политики'],
  ['dataset', 'Датасет'],
] as const
type Tab = (typeof TABS)[number][0]

const tabFromHash = (): Tab => {
  const h = location.hash.slice(1)
  return (TABS.find(([k]) => k === h)?.[0] ?? 'queue') as Tab
}

export default function App() {
  const [tab, setTab] = useState<Tab>(tabFromHash)
  const [events, setEvents] = useState<DlpEvent[]>([])
  const [policy, setPolicy] = useState<PolicyRaw | null>(null)
  const [live, setLive] = useState(false)
  const [runtime, setRuntime] = useState<{ provider: string; model: string; local: boolean } | null>(null)

  const loadPolicy = useCallback(
    () =>
      api.policies().then((p) => {
        setPolicy(p.raw)
        setRuntime(p.runtime)
      }),
    [],
  )

  useEffect(() => {
    const onHash = () => setTab(tabFromHash())
    addEventListener('hashchange', onHash)
    return () => removeEventListener('hashchange', onHash)
  }, [])

  useEffect(() => {
    loadPolicy()
    api.events().then(setEvents)
    const es = new EventSource('/api/stream')
    es.onopen = () => {
      setLive(true)
      api.events().then(setEvents) // catch up after reconnects
    }
    es.onerror = () => setLive(false)
    es.addEventListener('event', (m) => {
      const ev: DlpEvent = JSON.parse((m as MessageEvent).data)
      setEvents((prev) => [ev, ...prev.filter((e) => e.id !== ev.id)].sort((a, b) => b.created_at - a.created_at))
    })
    return () => es.close()
  }, [loadPolicy])

  const pending = events.filter((e) => e.status === 'pending').length
  const timeout = policy?.review_timeout_s ?? 60
  const th = policy?.thresholds ?? { review: 0.5, block: 0.9 }

  return (
    <div className="min-h-screen bg-slate-100 text-slate-900">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-4 px-4 py-3">
          <div className="flex items-center gap-2">
            <img src="/logo.svg" alt="Local DLP Guard" className="h-10 w-auto" />
            <span className="font-semibold">Local DLP Guard</span>
            {runtime && !runtime.local ? (
              <span className="rounded bg-rose-600 px-2 py-0.5 text-xs font-semibold text-white">
                ⚠ {runtime.model} через Gemini API: проверяемый текст уходит в Google
              </span>
            ) : (
              <span className="text-xs text-slate-500">{runtime?.model ?? '…'} · Ollama · всё локально</span>
            )}
          </div>
          <nav className="flex gap-1">
            {TABS.map(([k, label]) => (
              <a
                key={k}
                href={`#${k}`}
                className={`rounded-md px-3 py-1.5 text-sm ${tab === k ? 'bg-indigo-600 text-white' : 'text-slate-600 hover:bg-slate-100'}`}
              >
                {label}
                {k === 'queue' && pending > 0 && <span className="ml-1.5 rounded-full bg-amber-500 px-1.5 text-xs text-white">{pending}</span>}
              </a>
            ))}
          </nav>
          <span className={`ml-auto text-xs ${live ? 'text-emerald-600' : 'text-rose-600'}`}>● {live ? 'live' : 'нет связи'}</span>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6">
        {tab === 'queue' && <Queue events={events} timeout={timeout} th={th} />}
        {tab === 'log' && <Log events={events} timeout={timeout} th={th} />}
        {tab === 'try' && <TryIt domains={Object.keys(policy?.domains ?? {})} th={th} />}
        {tab === 'policies' && <Policies onSaved={loadPolicy} />}
        {tab === 'dataset' && <Dataset categories={policy?.categories ?? []} />}
      </main>
    </div>
  )
}
