import { Fragment, useEffect, useState } from 'react'
import { api, type DlpEvent, type PurposeStats } from '../api'
import { Card, PurposeTag, StatusText, TierBadge, fmtTime } from '../ui'
import { EventCard, type Thresholds } from './Queue'

export default function Log({ events, timeout, th }: { events: DlpEvent[]; timeout: number; th: Thresholds }) {
  const [open, setOpen] = useState<string | null>(null)
  const [stats, setStats] = useState<PurposeStats | null>(null)
  useEffect(() => {
    api.stats().then(setStats)
  }, [events.length])
  return (
    <div className="space-y-4">
    {stats && <StatsPanel stats={stats} />}
    <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
      <table className="w-full text-sm">
        <thead className="bg-slate-50 text-left text-xs text-slate-500 uppercase">
          <tr>
            <th className="px-3 py-2">Время</th>
            <th className="px-3 py-2">Уровень</th>
            <th className="px-3 py-2">Домен</th>
            <th className="px-3 py-2">Score</th>
            <th className="px-3 py-2">Категории</th>
            <th className="px-3 py-2">Статус</th>
            <th className="px-3 py-2">Текст</th>
          </tr>
        </thead>
        <tbody>
          {events.map((e) => (
            <Fragment key={e.id}>
              <tr className="cursor-pointer border-t border-slate-100 hover:bg-slate-50" onClick={() => setOpen(open === e.id ? null : e.id)}>
                <td className="px-3 py-2 whitespace-nowrap">{fmtTime(e.created_at)}</td>
                <td className="px-3 py-2"><TierBadge tier={e.tier} /></td>
                <td className="px-3 py-2">{e.host}</td>
                <td className="px-3 py-2 font-mono">{e.score.toFixed(2)}</td>
                <td className="px-3 py-2 text-xs">{[...new Set(e.findings.filter((f) => !f.allowed && f.is_sensitive).map((f) => f.category))].join(', ') || '—'}</td>
                <td className="px-3 py-2"><StatusText status={e.status} /> <PurposeTag purpose={e.purpose} /></td>
                <td className="max-w-md truncate px-3 py-2 text-xs text-slate-500">{e.text}</td>
              </tr>
              {open === e.id && (
                <tr>
                  <td colSpan={7} className="bg-slate-50 p-3"><EventCard ev={e} timeout={timeout} th={th} /></td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
      {events.length === 0 && <p className="p-4 text-sm text-slate-500">Событий пока нет.</p>}
    </div>
    </div>
  )
}

function StatsPanel({ stats }: { stats: PurposeStats }) {
  const total = stats.domains.reduce((a, d) => a + d.total, 0)
  const nonWork = stats.domains.reduce((a, d) => a + d.non_work, 0)
  return (
    <Card>
      <div className="flex flex-wrap items-start gap-8">
        <div>
          <div className="text-xs text-slate-500">Нецелевые запросы за 24 ч</div>
          <div className="text-2xl font-semibold">
            {nonWork} <span className="text-sm font-normal text-slate-500">из {total} ({total ? Math.round((nonWork / total) * 100) : 0}%)</span>
          </div>
        </div>
        <div className="text-sm">
          <div className="mb-1 text-xs text-slate-500">По доменам</div>
          {stats.domains.map((d) => (
            <div key={d.host} className="flex items-center gap-2">
              <span className="w-28">{d.host}</span>
              <div className="h-2 w-32 overflow-hidden rounded bg-slate-200">
                <div className="h-full bg-sky-500" style={{ width: `${d.total ? (d.non_work / d.total) * 100 : 0}%` }} />
              </div>
              <span className="text-xs text-slate-500">{d.non_work}/{d.total}</span>
            </div>
          ))}
        </div>
        <div className="text-sm">
          <div className="mb-1 text-xs text-slate-500">Топ тем</div>
          {stats.topics.length === 0 && <span className="text-xs text-slate-400">нет</span>}
          {stats.topics.map((t) => (
            <div key={t.topic}>{t.topic} <span className="text-xs text-slate-500">× {t.n}</span></div>
          ))}
        </div>
      </div>
    </Card>
  )
}
