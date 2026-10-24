import { Fragment, useState } from 'react'
import type { DlpEvent } from '../api'
import { StatusText, TierBadge, fmtTime } from '../ui'
import { EventCard } from './Queue'

export default function Log({ events, timeout }: { events: DlpEvent[]; timeout: number }) {
  const [open, setOpen] = useState<string | null>(null)
  return (
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
                <td className="px-3 py-2"><StatusText status={e.status} /></td>
                <td className="max-w-md truncate px-3 py-2 text-xs text-slate-500">{e.text}</td>
              </tr>
              {open === e.id && (
                <tr>
                  <td colSpan={7} className="bg-slate-50 p-3"><EventCard ev={e} timeout={timeout} /></td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
      {events.length === 0 && <p className="p-4 text-sm text-slate-500">Событий пока нет.</p>}
    </div>
  )
}
