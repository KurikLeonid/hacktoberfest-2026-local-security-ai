import { useEffect, useState } from 'react'
import { api, type DatasetRow } from '../api'
import { Button, Card } from '../ui'

export default function Dataset({ categories }: { categories: string[] }) {
  const [rows, setRows] = useState<DatasetRow[]>([])
  const [total, setTotal] = useState(0)
  const [stats, setStats] = useState<{ category: string; label: string; source: string; n: number }[]>([])
  const [offset, setOffset] = useState(0)
  const [category, setCategory] = useState('')
  const [sources, setSources] = useState<{ id: string; description: string }[]>([])
  const [busy, setBusy] = useState('')
  const [msg, setMsg] = useState('')

  const load = () =>
    api.dataset(offset, category).then((d) => { setRows(d.rows); setTotal(d.total); setStats(d.stats) })
  useEffect(() => { load() }, [offset, category])
  useEffect(() => { api.sources().then(setSources) }, [])

  const run = async (label: string, p: () => Promise<{ imported?: number; deleted?: number }>) => {
    setBusy(label)
    setMsg('')
    try {
      const r = await p()
      setMsg(r.imported != null ? `Импортировано: ${r.imported}` : `Удалено: ${r.deleted}`)
      setOffset(0)
      await load()
    } catch (e) {
      setMsg(String(e))
    } finally {
      setBusy('')
    }
  }

  const bySource: Record<string, number> = {}
  for (const s of stats) {
    const key = s.source.startsWith('upload:') ? 'upload' : s.source
    bySource[key] = (bySource[key] ?? 0) + s.n
  }
  const byCat = categories.map((c) => ({
    c,
    pos: stats.filter((s) => s.category === c && s.label === 'sensitive').reduce((a, s) => a + s.n, 0),
    neg: stats.filter((s) => s.category === c && s.label === 'not_sensitive').reduce((a, s) => a + s.n, 0),
  }))

  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <h2 className="mb-2 font-semibold">Импорт с Hugging Face</h2>
          <p className="mb-3 text-xs text-slate-500">Качается один раз и хранится локально. Повторный импорт заменяет данные этого источника.</p>
          {sources.map((s) => (
            <div key={s.id} className="mb-3">
              <div className="text-sm font-medium break-all">{s.id}</div>
              <div className="mb-1 text-xs text-slate-500">{s.description}</div>
              <Button disabled={!!busy} onClick={() => run(s.id, () => api.importHf(s.id))}>{busy === s.id ? 'Импорт…' : 'Импортировать'}</Button>
            </div>
          ))}
        </Card>
        <Card>
          <h2 className="mb-2 font-semibold">Загрузить свой датасет</h2>
          <p className="mb-3 text-xs text-slate-500">
            JSONL или CSV с полями <code>text, category, label</code> (sensitive | not_sensitive) и необязательным <code>span</code>.
          </p>
          <input type="file" accept=".jsonl,.json,.csv" disabled={!!busy} onChange={(e) => e.target.files?.[0] && run('upload', () => api.upload(e.target.files![0]))} className="text-sm" />
          <div className="mt-4 flex flex-wrap gap-2">
            <a href="/api/dataset/export"><Button kind="primary">Экспорт JSONL для LoRA</Button></a>
            <Button kind="danger" disabled={!!busy} onClick={() => confirm('Удалить весь датасет?') && run('clear', () => api.clearDataset())}>Очистить</Button>
          </div>
          {msg && <p className="mt-2 text-sm text-slate-700">{msg}</p>}
        </Card>
        <Card>
          <h2 className="mb-2 font-semibold">Состав</h2>
          <table className="w-full text-sm">
            <thead><tr className="text-xs text-slate-500"><th className="text-left">категория</th><th>sensitive</th><th>not_sensitive</th></tr></thead>
            <tbody>
              {byCat.map((r) => (
                <tr key={r.c}><td>{r.c}</td><td className="text-center text-rose-700">{r.pos}</td><td className="text-center text-emerald-700">{r.neg}</td></tr>
              ))}
            </tbody>
          </table>
          <div className="mt-3 space-y-0.5 text-xs text-slate-500">
            {Object.entries(bySource).map(([s, n]) => <div key={s}>{s}: {n}</div>)}
          </div>
        </Card>
      </div>

      <Card>
        <div className="mb-2 flex items-center gap-3">
          <h2 className="font-semibold">Примеры ({total})</h2>
          <select className="rounded border px-1 text-sm" value={category} onChange={(e) => { setCategory(e.target.value); setOffset(0) }}>
            <option value="">все категории</option>
            {categories.map((c) => <option key={c}>{c}</option>)}
          </select>
          <div className="ml-auto flex gap-2">
            <Button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))}>←</Button>
            <span className="text-sm">{offset + 1}–{Math.min(offset + 50, total)}</span>
            <Button disabled={offset + 50 >= total} onClick={() => setOffset(offset + 50)}>→</Button>
          </div>
        </div>
        <table className="w-full table-fixed text-sm">
          <thead className="text-left text-xs text-slate-500">
            <tr><th className="w-28">категория</th><th className="w-28">метка</th><th className="w-48">фрагмент</th><th>контекст</th><th className="w-40">источник</th></tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="border-t border-slate-100 align-top">
                <td className="py-1">{r.category}</td>
                <td className={r.label === 'sensitive' ? 'text-rose-700' : 'text-emerald-700'}>{r.label}</td>
                <td className="truncate font-mono text-xs">{r.span ?? '—'}</td>
                <td className="truncate text-xs text-slate-600">{r.text}</td>
                <td className="truncate text-xs text-slate-500">{r.source}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  )
}
