// Thin client for the backend API described in spec/api.md.
// All endpoints are relative to the same origin the static export is served
// from (FastAPI serves both the API and the /app static export on :8001),
// so plain relative fetch() calls (e.g. "/datasets") resolve correctly —
// mirrors the pattern already used by the skeleton's page.tsx.

export type ColumnProfile = {
  name: string
  dtype: string
  missing_count: number
  missing_pct: number
  unique_count?: number
  sample_values?: unknown[]
  min?: string | number | null
  max?: string | number | null
  mean?: number | null
}

export type DatasetProfile = {
  row_count: number
  column_count: number
  columns: ColumnProfile[]
  generated_at: string
}

export type Dataset = {
  id: string
  name: string
  kind: string
  status: string
  created_at: string
}

export type DatasetWithProfile = {
  dataset: Dataset
  profile: DatasetProfile
}

export type Conversation = {
  id: string
  dataset_id: string
  title: string
  created_at?: string
}

export type ResultTable = {
  columns: string[]
  rows: unknown[][]
}

export type QueryRun = {
  id: string
  execution_status: 'success' | 'failed' | 'cannot_answer'
  generated_code: string
  answer_text: string
  key_numbers: Record<string, unknown>
  follow_up_suggestions: string[]
  anomalies: unknown[]
  result_table: ResultTable | null
  step_count: number
  prompt_tokens: number
  completion_tokens: number
  estimated_cost_usd: number
  // Display-derived INR equivalent (estimated_cost_usd * usd_to_inr_rate),
  // computed by the API — never stored, never computed in the frontend.
  estimated_cost_inr: number
  latency_ms: number
  // Present on records returned by GET /query-runs (audit trail).
  conversation_id?: string
  dataset_id?: string
  created_at?: string
}

export type DerivedDataset = {
  id: string
  name: string
  row_count: number
  download_url: string
}

export type CostSummary = {
  scope: string
  date?: string
  total_tokens: number
  total_cost_usd: number
  // Display-derived INR total (total_cost_usd * usd_to_inr_rate) from the API.
  total_cost_inr: number
  usd_to_inr_rate: number
  query_count: number
}

export type ChatMessage = {
  id: string
  role: 'user' | 'assistant'
  content: string
  query_run_id?: string
  created_at: string
}

export type MessagesResponse = {
  conversation: Conversation
  messages: ChatMessage[]
  session_cost_total_usd: number
  // Display-derived INR session total from the API.
  session_cost_total_inr: number
  session_tokens_total: number
  usd_to_inr_rate: number
}

export type AskResponse = {
  message: ChatMessage
  query_run: QueryRun
  // Configured USD→INR rate echoed by the API (AGENT_USD_TO_INR).
  usd_to_inr_rate: number
}

type Envelope<T> = { data: T | null; error: { code: string; message: string } | null }

export class ApiError extends Error {
  status: number
  code?: string
  constructor(message: string, status: number, code?: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, init)
  } catch {
    throw new ApiError('Network error — is the server running?', 0)
  }

  let body: Envelope<T> | null = null
  try {
    body = await res.json()
  } catch {
    // fall through — no JSON body
  }

  if (!res.ok) {
    const message = body?.error?.message ?? `Request failed (${res.status})`
    throw new ApiError(message, res.status, body?.error?.code)
  }
  if (!body || body.data === null) {
    throw new ApiError('Unexpected empty response from server', res.status)
  }
  return body.data
}

export async function uploadDataset(file: File): Promise<DatasetWithProfile> {
  const form = new FormData()
  form.append('file', file)
  return request<DatasetWithProfile>('/datasets', { method: 'POST', body: form })
}

export async function getDataset(datasetId: string): Promise<DatasetWithProfile> {
  return request<DatasetWithProfile>(`/datasets/${datasetId}`)
}

export async function createConversation(datasetId: string): Promise<Conversation> {
  return request<Conversation>(`/datasets/${datasetId}/conversations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  })
}

export async function askQuestion(conversationId: string, question: string): Promise<AskResponse> {
  return request<AskResponse>(`/conversations/${conversationId}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question }),
  })
}

export async function getMessages(conversationId: string): Promise<MessagesResponse> {
  return request<MessagesResponse>(`/conversations/${conversationId}/messages`)
}

// --- Phase 2 endpoints ---

// Add another file to an existing dataset (folder-as-dataset). Returns the
// updated {dataset, profile} with the combined row count.
export async function addFileToDataset(
  datasetId: string,
  file: File,
): Promise<DatasetWithProfile> {
  const form = new FormData()
  form.append('file', file)
  return request<DatasetWithProfile>(`/datasets/${datasetId}/files`, {
    method: 'POST',
    body: form,
  })
}

// Export a cleaned/derived dataset produced by a prior QueryRun.
export async function exportDataset(
  datasetId: string,
  queryRunId: string,
  name?: string,
): Promise<{ derived_dataset: DerivedDataset }> {
  return request<{ derived_dataset: DerivedDataset }>(`/datasets/${datasetId}/export`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query_run_id: queryRunId, name: name ?? 'cleaned_data.csv' }),
  })
}

export type QueryRunFilters = {
  dataset_id?: string
  conversation_id?: string
  execution_status?: string
  from?: string
  to?: string
  limit?: number
  offset?: number
}

// Browse the full audit trail across all conversations/datasets.
export async function listQueryRuns(filters: QueryRunFilters = {}): Promise<QueryRun[]> {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== null && value !== '') {
      params.append(key, String(value))
    }
  }
  const qs = params.toString()
  const data = await request<{ query_runs: QueryRun[] }>(`/query-runs${qs ? `?${qs}` : ''}`)
  return data.query_runs
}

// Running cost/token totals for the dashboard.
export async function getCostSummary(
  scope: 'session' | 'day' | 'all' = 'day',
  conversationId?: string,
): Promise<CostSummary> {
  const params = new URLSearchParams({ scope })
  if (conversationId) params.append('conversation_id', conversationId)
  return request<CostSummary>(`/cost-summary?${params.toString()}`)
}
