import { useEffect, useState } from 'react'
import { api, type PolicyRaw } from '../api'
import { Button, Card } from '../ui'

export default function Policies({ onSaved }: { onSaved: () => void }) {
  const [raw, setRaw] = useState<PolicyRaw | null>(null)
  const [yaml, setYaml] = useState('')
  const [mode, setMode] = useState<'form' | 'yaml'>('form')
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [newDomain, setNewDomain] = useState('')

  const load = () => api.policies().then((p) => { setRaw(p.raw); setYaml(p.yaml) })
  useEffect(() => { load() }, [])
  if (!raw) return null

  const done = async (p: Promise<{ restart_proxy: boolean }>) => {
    try {
      const r = await p
      setMsg({ ok: true, text: r.restart_proxy ? 'Сохранено. Список inspect-доменов изменился: перезапустите прокси.' : 'Сохранено, прокси подхватит без рестарта.' })
      await load()
      onSaved()
    } catch (e) {
      setMsg({ ok: false, text: String(e) })
    }
  }

  const toggle = (domain: string, cat: string) => {
    const cur = raw.domains[domain] ?? []
    const next = cur.includes(cat) ? cur.filter((c) => c !== cat) : [...cur, cat]
    setRaw({ ...raw, domains: { ...raw.domains, [domain]: next } })
  }
  const setInspect = (domain: string, on: boolean) =>
    setRaw({ ...raw, inspect_domains: on ? [...new Set([...raw.inspect_domains, domain])] : raw.inspect_domains.filter((d) => d !== domain) })
  const addDomain = () => {
    const d = newDomain.trim().toLowerCase()
    if (!d) return
    setRaw({ ...raw, domains: { ...raw.domains, [d]: raw.domains[d] ?? [] }, inspect_domains: [...new Set([...raw.inspect_domains, d])] })
    setNewDomain('')
  }
  const removeDomain = (d: string) => {
    const domains = { ...raw.domains }
    delete domains[d]
    setRaw({ ...raw, domains, inspect_domains: raw.inspect_domains.filter((x) => x !== d) })
  }
  const allDomains = [...new Set([...Object.keys(raw.domains), ...raw.inspect_domains])]

  const importFile = async (f: File | undefined) => {
    if (!f) return
    setYaml(await f.text())
    setMode('yaml')
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Button kind={mode === 'form' ? 'primary' : 'default'} onClick={() => setMode('form')}>Форма</Button>
        <Button kind={mode === 'yaml' ? 'primary' : 'default'} onClick={() => setMode('yaml')}>YAML</Button>
        <a className="text-sm text-indigo-600 underline" href="/api/policies/export">Экспорт YAML</a>
        <label className="cursor-pointer text-sm text-indigo-600 underline">
          Импорт YAML
          <input type="file" accept=".yaml,.yml" className="hidden" onChange={(e) => importFile(e.target.files?.[0])} />
        </label>
        {msg && <span className={`text-sm ${msg.ok ? 'text-emerald-700' : 'text-rose-600'}`}>{msg.text}</span>}
      </div>

      {mode === 'yaml' ? (
        <Card>
          <textarea className="h-[60vh] w-full rounded border border-slate-300 p-2 font-mono text-xs" value={yaml} onChange={(e) => setYaml(e.target.value)} />
          <div className="mt-2"><Button kind="primary" onClick={() => done(api.savePoliciesYaml(yaml))}>Проверить и сохранить</Button></div>
        </Card>
      ) : (
        <>
          <Card>
            <h2 className="mb-1 font-semibold">Whitelist: какие категории можно отправлять на домен</h2>
            <p className="mb-3 text-xs text-slate-500">
              Домен без галочек ничего чувствительного не принимает. «Проверять» означает расшифровку TLS и анализ моделью.
              Категории из never_allowed ({raw.never_allowed.join(', ')}) запрещены везде.
            </p>
            <div className="overflow-x-auto">
              <table className="text-sm">
                <thead>
                  <tr className="text-xs text-slate-500">
                    <th className="px-2 py-1 text-left">Домен</th>
                    <th className="px-2 py-1">Проверять</th>
                    {raw.categories.map((c) => <th key={c} className="px-2 py-1">{c}</th>)}
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {allDomains.map((d) => (
                    <tr key={d} className="border-t border-slate-100">
                      <td className="px-2 py-1 font-medium">{d}</td>
                      <td className="px-2 py-1 text-center">
                        <input type="checkbox" checked={raw.inspect_domains.includes(d)} onChange={(e) => setInspect(d, e.target.checked)} />
                      </td>
                      {raw.categories.map((c) => {
                        const never = raw.never_allowed.includes(c)
                        return (
                          <td key={c} className="px-2 py-1 text-center">
                            <input type="checkbox" disabled={never} checked={!never && (raw.domains[d] ?? []).includes(c)} onChange={() => toggle(d, c)} />
                          </td>
                        )
                      })}
                      <td className="px-2"><button className="text-xs text-rose-600" onClick={() => removeDomain(d)}>удалить</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="mt-3 flex gap-2">
              <input className="rounded border border-slate-300 px-2 py-1 text-sm" placeholder="example.com" value={newDomain} onChange={(e) => setNewDomain(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && addDomain()} />
              <Button onClick={addDomain}>Добавить домен</Button>
            </div>
          </Card>

          <Card>
            <h2 className="mb-3 font-semibold">Пороги</h2>
            {(['review', 'block'] as const).map((k) => (
              <div key={k} className="mb-2 flex items-center gap-3 text-sm">
                <span className="w-56">{k === 'review' ? 'REVIEW, если score ≥' : 'BLOCK, если score ≥'}</span>
                <input type="range" min={0} max={1} step={0.05} value={raw.thresholds[k]} onChange={(e) => setRaw({ ...raw, thresholds: { ...raw.thresholds, [k]: Number(e.target.value) } })} />
                <span className="font-mono">{raw.thresholds[k].toFixed(2)}</span>
              </div>
            ))}
            <div className="mt-2 flex h-3 overflow-hidden rounded text-[0px]">
              <div className="bg-emerald-400" style={{ width: `${raw.thresholds.review * 100}%` }} />
              <div className="bg-amber-400" style={{ width: `${(raw.thresholds.block - raw.thresholds.review) * 100}%` }} />
              <div className="flex-1 bg-rose-400" />
            </div>
            <div className="mt-4 flex flex-wrap gap-6 text-sm">
              <label>Таймаут решения security, с <input type="number" className="ml-1 w-20 rounded border px-1" value={raw.review_timeout_s} onChange={(e) => setRaw({ ...raw, review_timeout_s: Number(e.target.value) })} /></label>
              <label>Таймаут модели, с <input type="number" className="ml-1 w-20 rounded border px-1" value={raw.model_timeout_s} onChange={(e) => setRaw({ ...raw, model_timeout_s: Number(e.target.value) })} /></label>
              <label>Модель <input className="ml-1 w-36 rounded border px-1" value={raw.models.llm} onChange={(e) => setRaw({ ...raw, models: { ...raw.models, llm: e.target.value } })} /></label>
            </div>
          </Card>
          <Button kind="primary" onClick={() => done(api.savePolicies(raw))}>Сохранить политики</Button>
        </>
      )}
    </div>
  )
}
