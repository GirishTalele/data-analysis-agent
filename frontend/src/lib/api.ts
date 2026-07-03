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

export type QueryRun = {
  id: string
  execution_status: 'success' | 'failed' | 'cannot_answer'
  generated_code: string
  answer_text: string
  key_numbers: Record<string, unknown>
  follow_up_suggestions: string[]
  anomalies: unknown[]
  step_count: number
  prompt_tokens: number
  completion_tokens: number
  estimated_cost_usd: number
  latency_ms: number
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
  session_tokens_total: number
}

export type AskResponse = {
  message: ChatMessage
  query_run: QueryRun
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
