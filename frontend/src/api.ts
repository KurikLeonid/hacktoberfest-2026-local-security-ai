export type Finding = {
  span: string
  category: string
  reason: string
  allowed: boolean
  is_sensitive?: boolean
  confidence?: number
  verify_reason?: string
  start: number | null
  end: number | null
}

export type Tier = 'ALLOW' | 'REVIEW' | 'BLOCK'
export type Status = 'allowed' | 'pending' | 'blocked' | 'approved' | 'rejected' | 'expired'

export type DlpEvent = {
  id: string
  created_at: number
  host: string
  path: string
  adapter: string
  text: string
  tier: Tier
  score: number
  findings: Finding[]
  status: Status
  error: string | null
  latency_ms: number | null
  decided_at: number | null
  purpose: Purpose | null
}

export type Purpose = { work: boolean; topic: string; confidence: number }

export type PurposeStats = {
  domains: { host: string; total: number; non_work: number }[]
  topics: { topic: string; n: number }[]
}

export type PolicyRaw = {
  categories: string[]
  never_allowed: string[]
  thresholds: { review: number; block: number }
  review_timeout_s: number
  model_timeout_s: number
  models: { llm: string; fallback: string }
  inspect_domains: string[]
  domains: Record<string, string[]>
  skip_paths: string[]
  min_text_chars: number
}

export type DatasetRow = {
  id: number
  text: string
  span: string | null
  category: string
  label: 'sensitive' | 'not_sensitive'
  source: string
  created_at: number
}

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init)
  if (!r.ok) {
    let msg = r.statusText
    try {
      msg = (await r.json()).detail ?? msg
    } catch {
      /* not json */
    }
    throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg))
  }
  return r.json()
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const api = {
  events: (status?: string) => req<DlpEvent[]>(`/api/events${status ? `?status=${status}` : ''}`),
  decide: (id: string, decision: 'approve' | 'reject') =>
    req<{ event: DlpEvent; dataset_rows_added: number }>(`/api/events/${id}/decision`, json('POST', { decision })),
  classify: (text: string, host: string) =>
    req<{ tier: Tier; score: number; findings: Finding[]; latency_ms?: number; error?: string }>(
      '/api/classify',
      json('POST', { text, host }),
    ),
  stats: (hours = 24) => req<PurposeStats>(`/api/stats?hours=${hours}`),
  policies: () =>
    req<{ raw: PolicyRaw; yaml: string; runtime: { provider: string; model: string; local: boolean } }>('/api/policies'),
  savePolicies: (raw: PolicyRaw) => req<{ restart_proxy: boolean }>('/api/policies', json('PUT', raw)),
  savePoliciesYaml: (yaml: string) => req<{ restart_proxy: boolean }>('/api/policies/yaml', json('PUT', { yaml })),
  dataset: (offset = 0, category = '') =>
    req<{ rows: DatasetRow[]; total: number; stats: { category: string; label: string; source: string; n: number }[] }>(
      `/api/dataset?limit=50&offset=${offset}${category ? `&category=${category}` : ''}`,
    ),
  sources: () => req<{ id: string; description: string }[]>('/api/dataset/sources'),
  importHf: (dataset_id: string) => req<{ imported: number }>('/api/dataset/import-hf', json('POST', { dataset_id })),
  upload: (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return req<{ imported: number }>('/api/dataset/upload', { method: 'POST', body: fd })
  },
  clearDataset: (source?: string) =>
    req<{ deleted: number }>(`/api/dataset${source ? `?source=${encodeURIComponent(source)}` : ''}`, { method: 'DELETE' }),
}
