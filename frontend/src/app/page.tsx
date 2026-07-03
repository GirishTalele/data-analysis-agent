'use client'

import { useEffect, useRef, useState } from 'react'
import ProfileCard from '@/components/ProfileCard'
import MessageBubble from '@/components/MessageBubble'
import {
  ApiError,
  askQuestion,
  createConversation,
  getDataset,
  getMessages,
  uploadDataset,
  type ChatMessage,
  type DatasetWithProfile,
  type QueryRun,
} from '@/lib/api'

const DATASET_KEY = 'agent.datasetId'
const CONVERSATION_KEY = 'agent.conversationId'

const ACCEPTED_EXTENSIONS = ['.csv', '.xlsx', '.xls']

export default function Home() {
  // --- Upload / profile state ---
  const [datasetInfo, setDatasetInfo] = useState<DatasetWithProfile | null>(null)
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [restoring, setRestoring] = useState(true)

  // --- Conversation / chat state ---
  const [conversationId, setConversationId] = useState<string | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [queryRuns, setQueryRuns] = useState<Record<string, QueryRun>>({})
  const [sessionTotals, setSessionTotals] = useState<{ tokens: number; cost: number }>({
    tokens: 0,
    cost: 0,
  })
  const [question, setQuestion] = useState('')
  const [asking, setAsking] = useState(false)
  const [askError, setAskError] = useState<string | null>(null)

  const fileInputRef = useRef<HTMLInputElement>(null)
  const threadEndRef = useRef<HTMLDivElement>(null)

  // Restore dataset/conversation from localStorage on load.
  useEffect(() => {
    const storedDatasetId = window.localStorage.getItem(DATASET_KEY)
    const storedConversationId = window.localStorage.getItem(CONVERSATION_KEY)

    async function restore() {
      if (!storedDatasetId) {
        setRestoring(false)
        return
      }
      try {
        const dataset = await getDataset(storedDatasetId)
        setDatasetInfo(dataset)
        if (storedConversationId) {
          setConversationId(storedConversationId)
          const history = await getMessages(storedConversationId)
          setMessages(history.messages)
          setSessionTotals({
            tokens: history.session_tokens_total,
            cost: history.session_cost_total_usd,
          })
        }
      } catch {
        // Stale/invalid ids — clear them and let the user start fresh.
        window.localStorage.removeItem(DATASET_KEY)
        window.localStorage.removeItem(CONVERSATION_KEY)
      } finally {
        setRestoring(false)
      }
    }
    restore()
  }, [])

  useEffect(() => {
    threadEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, asking])

  function validExtension(name: string): boolean {
    const lower = name.toLowerCase()
    return ACCEPTED_EXTENSIONS.some(ext => lower.endsWith(ext))
  }

  async function handleFile(file: File) {
    if (!validExtension(file.name)) {
      setUploadError("Couldn't read this file — make sure it's a valid CSV or Excel file under 100MB")
      return
    }
    setUploading(true)
    setUploadError(null)
    try {
      const result = await uploadDataset(file)
      setDatasetInfo(result)
      window.localStorage.setItem(DATASET_KEY, result.dataset.id)
      // Start a fresh conversation for the newly uploaded dataset.
      window.localStorage.removeItem(CONVERSATION_KEY)
      setConversationId(null)
      setMessages([])
      setQueryRuns({})
      setSessionTotals({ tokens: 0, cost: 0 })
    } catch (err) {
      if (err instanceof ApiError) {
        setUploadError(
          err.status === 0
            ? err.message
            : "Couldn't read this file — make sure it's a valid CSV or Excel file under 100MB",
        )
      } else {
        setUploadError("Couldn't read this file — make sure it's a valid CSV or Excel file under 100MB")
      }
    } finally {
      setUploading(false)
    }
  }

  function onFileInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (file) handleFile(file)
    e.target.value = ''
  }

  function onDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault()
    const file = e.dataTransfer.files?.[0]
    if (file) handleFile(file)
  }

  async function ensureConversation(): Promise<string> {
    if (conversationId) return conversationId
    if (!datasetInfo) throw new Error('No dataset loaded')
    const conversation = await createConversation(datasetInfo.dataset.id)
    setConversationId(conversation.id)
    window.localStorage.setItem(CONVERSATION_KEY, conversation.id)
    return conversation.id
  }

  async function handleAsk(e: React.FormEvent) {
    e.preventDefault()
    const trimmed = question.trim()
    if (!trimmed || asking || !datasetInfo) return

    setAsking(true)
    setAskError(null)
    const pendingUserMessage: ChatMessage = {
      id: `pending-${Date.now()}`,
      role: 'user',
      content: trimmed,
      created_at: new Date().toISOString(),
    }
    setMessages(prev => [...prev, pendingUserMessage])
    setQuestion('')

    try {
      const convoId = await ensureConversation()
      const response = await askQuestion(convoId, trimmed)
      setQueryRuns(prev => ({ ...prev, [response.message.id]: response.query_run }))

      // Refresh full history + running totals from the server (source of truth).
      const history = await getMessages(convoId)
      setMessages(history.messages)
      setSessionTotals({
        tokens: history.session_tokens_total,
        cost: history.session_cost_total_usd,
      })

      if (response.query_run.execution_status !== 'success') {
        setAskError(null) // rendered inline via the assistant bubble instead
      }
    } catch (err) {
      // Remove the optimistic user bubble and surface the error inline.
      setMessages(prev => prev.filter(m => m.id !== pendingUserMessage.id))
      if (err instanceof ApiError) {
        setAskError(err.message)
      } else {
        setAskError('Network error — is the server running?')
      }
    } finally {
      setAsking(false)
    }
  }

  const hasDataset = !!datasetInfo

  return (
    <main className="mx-auto max-w-3xl px-4 py-10">
      <header className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-bold tracking-tight">Data Analysis Agent</h1>
        <div className="flex items-center gap-3">
          {(sessionTotals.tokens > 0 || sessionTotals.cost > 0) && (
            <span
              className="rounded-full bg-gray-900 px-3 py-1 text-xs font-medium text-white"
              data-testid="session-total-badge"
            >
              Session: {sessionTotals.tokens.toLocaleString()} tokens · $
              {sessionTotals.cost.toFixed(4)}
            </span>
          )}
          <button
            type="button"
            disabled
            title="Audit trail — coming soon"
            className="cursor-not-allowed rounded-md border border-gray-200 px-2 py-1 text-xs text-gray-300"
          >
            Audit trail
          </button>
        </div>
      </header>

      {/* --- Upload & Profile section --- */}
      <section className="mb-8">
        <div
          onDrop={onDrop}
          onDragOver={e => e.preventDefault()}
          className="relative rounded-lg border-2 border-dashed border-gray-300 bg-white p-6 text-center"
          data-testid="dropzone"
        >
          {uploading && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 rounded-lg bg-white/80 text-sm text-gray-600">
              <span
                className="h-5 w-5 animate-spin rounded-full border-2 border-blue-600 border-t-transparent"
                aria-hidden
              />
              Profiling your data…
            </div>
          )}

          {restoring ? (
            <p className="text-sm text-gray-400">Loading…</p>
          ) : !hasDataset ? (
            <p className="text-sm text-gray-500">Upload a CSV or Excel file to get started</p>
          ) : (
            <p className="text-sm text-gray-500">
              Loaded <span className="font-medium text-gray-800">{datasetInfo.dataset.name}</span>
            </p>
          )}

          <div className="mt-3 flex items-center justify-center gap-3">
            <input
              ref={fileInputRef}
              type="file"
              accept=".csv,.xlsx,.xls"
              className="hidden"
              onChange={onFileInputChange}
              disabled={uploading}
              data-testid="file-input"
            />
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
              className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              Choose file
            </button>
            <button
              type="button"
              disabled
              title="Multi-file datasets — coming soon"
              className="cursor-not-allowed rounded-lg border border-gray-200 px-4 py-2 text-sm text-gray-300"
            >
              + Add another file
            </button>
          </div>
        </div>

        {uploadError && (
          <div className="mt-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
            {uploadError}
          </div>
        )}

        {datasetInfo && (
          <div className="mt-4">
            <ProfileCard profile={datasetInfo.profile} />
          </div>
        )}
      </section>

      {/* --- Chat / Analysis section --- */}
      {hasDataset && (
        <section>
          <div className="mb-3 flex flex-col gap-3" data-testid="chat-thread">
            {messages.length === 0 && !asking && (
              <p className="text-center text-sm text-gray-400">
                Ask a question about your data — e.g. &ldquo;What&apos;s the average of column X?&rdquo;
              </p>
            )}
            {messages.map(m => (
              <MessageBubble key={m.id} message={m} queryRun={queryRuns[m.id]} />
            ))}

            {asking && (
              <div className="flex justify-start">
                <div className="flex items-center gap-2 rounded-2xl border border-gray-200 bg-white px-4 py-2.5 text-sm text-gray-500 shadow-sm">
                  <span
                    className="h-3 w-3 animate-spin rounded-full border-2 border-blue-600 border-t-transparent"
                    aria-hidden
                  />
                  Running analysis…
                </div>
              </div>
            )}

            {askError && (
              <div className="flex justify-start">
                <div className="max-w-[85%] rounded-2xl border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700">
                  {askError}
                </div>
              </div>
            )}
            <div ref={threadEndRef} />
          </div>

          <form onSubmit={handleAsk} className="flex gap-2">
            <input
              type="text"
              value={question}
              onChange={e => setQuestion(e.target.value)}
              disabled={asking}
              placeholder="Ask a question about your data — e.g. 'What's the average of column X?'"
              className="flex-1 rounded-lg border border-gray-300 px-3 py-2.5 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50"
              data-testid="question-input"
            />
            <button
              type="submit"
              disabled={asking || !question.trim()}
              className="rounded-lg bg-blue-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              data-testid="send-button"
            >
              {asking ? 'Running…' : 'Send'}
            </button>
          </form>

          <div className="mt-2">
            <button
              type="button"
              disabled
              title="Export cleaned data — coming soon"
              className="cursor-not-allowed text-xs text-gray-300 underline decoration-dotted"
            >
              Export cleaned data
            </button>
          </div>
        </section>
      )}
    </main>
  )
}
