'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import Link from 'next/link'
import ProfileCard from '@/components/ProfileCard'
import MessageBubble from '@/components/MessageBubble'
import StepList from '@/components/StepList'
import {
  ApiError,
  addFileToDataset,
  askQuestion,
  createConversation,
  exportDataset,
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
  const [addingFile, setAddingFile] = useState(false)

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
  const [exporting, setExporting] = useState(false)
  const [exportMessage, setExportMessage] = useState<string | null>(null)

  const fileInputRef = useRef<HTMLInputElement>(null)
  const addFileInputRef = useRef<HTMLInputElement>(null)
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

  // Add another file to the current dataset and refresh the profile card
  // to reflect the combined row count.
  async function handleAddFile(file: File) {
    if (!datasetInfo) return
    if (!validExtension(file.name)) {
      setUploadError("Couldn't read this file — make sure it's a valid CSV or Excel file under 100MB")
      return
    }
    setAddingFile(true)
    setUploadError(null)
    try {
      const result = await addFileToDataset(datasetInfo.dataset.id, file)
      setDatasetInfo(result)
    } catch (err) {
      if (err instanceof ApiError && err.status === 0) {
        setUploadError(err.message)
      } else {
        setUploadError("Couldn't add this file — make sure it's a valid CSV or Excel file under 100MB")
      }
    } finally {
      setAddingFile(false)
    }
  }

  function onFileInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (file) handleFile(file)
    e.target.value = ''
  }

  function onAddFileInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (file) handleAddFile(file)
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

  async function submitQuestion(text: string) {
    const trimmed = text.trim()
    if (!trimmed || asking || !datasetInfo) return

    setAsking(true)
    setAskError(null)
    setExportMessage(null)
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

  function handleAsk(e: React.FormEvent) {
    e.preventDefault()
    submitQuestion(question)
  }

  // The most recent successful query run backs the "Export cleaned data" action.
  const lastSuccessfulRun = useMemo(() => {
    const runs = Object.values(queryRuns).filter(r => r.execution_status === 'success')
    return runs.length ? runs[runs.length - 1] : null
  }, [queryRuns])

  async function handleExport() {
    if (!datasetInfo || !lastSuccessfulRun || exporting) return
    setExporting(true)
    setExportMessage(null)
    try {
      const { derived_dataset } = await exportDataset(
        datasetInfo.dataset.id,
        lastSuccessfulRun.id,
      )
      // Trigger a browser download from the returned download_url.
      const a = document.createElement('a')
      a.href = derived_dataset.download_url
      a.download = derived_dataset.name
      document.body.appendChild(a)
      a.click()
      a.remove()
      setExportMessage(`Exported ${derived_dataset.name} (${derived_dataset.row_count.toLocaleString()} rows)`)
    } catch (err) {
      setExportMessage(
        err instanceof ApiError ? err.message : 'Export failed — is the server running?',
      )
    } finally {
      setExporting(false)
    }
  }

  const hasDataset = !!datasetInfo
  const canExport = hasDataset && !!lastSuccessfulRun

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
          <Link
            href="/audit"
            className="rounded-md border border-gray-300 px-2 py-1 text-xs text-gray-700 hover:bg-gray-100"
            data-testid="audit-nav-link"
          >
            View audit trail
          </Link>
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
          {(uploading || addingFile) && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 rounded-lg bg-white/80 text-sm text-gray-600">
              <span
                className="h-5 w-5 animate-spin rounded-full border-2 border-blue-600 border-t-transparent"
                aria-hidden
              />
              {addingFile ? 'Adding file and re-profiling…' : 'Profiling your data…'}
            </div>
          )}

          {restoring ? (
            <p className="text-sm text-gray-400">Loading…</p>
          ) : !hasDataset ? (
            <p className="text-sm text-gray-500">Upload a CSV or Excel file to get started</p>
          ) : (
            <p className="text-sm text-gray-500">
              Loaded <span className="font-medium text-gray-800">{datasetInfo.dataset.name}</span>
              {datasetInfo.dataset.kind === 'multi_file' && (
                <span className="ml-1 rounded bg-gray-100 px-1.5 py-0.5 text-[11px] text-gray-500">
                  multi-file
                </span>
              )}
            </p>
          )}

          <div className="mt-3 flex items-center justify-center gap-3">
            <input
              ref={fileInputRef}
              type="file"
              accept=".csv,.xlsx,.xls"
              className="hidden"
              onChange={onFileInputChange}
              disabled={uploading || addingFile}
              data-testid="file-input"
            />
            <input
              ref={addFileInputRef}
              type="file"
              accept=".csv,.xlsx,.xls"
              className="hidden"
              onChange={onAddFileInputChange}
              data-testid="add-file-input"
            />
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading || addingFile}
              className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              Choose file
            </button>
            <button
              type="button"
              onClick={() => addFileInputRef.current?.click()}
              disabled={!hasDataset || uploading || addingFile}
              title="Add another file to this dataset"
              className="rounded-lg border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-50"
              data-testid="add-file-button"
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
              <MessageBubble
                key={m.id}
                message={m}
                queryRun={queryRuns[m.id]}
                onFollowUp={submitQuestion}
              />
            ))}

            {asking && (
              <div className="flex justify-start">
                <StepList inFlight />
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

          <div className="mt-2 flex items-center gap-3">
            <button
              type="button"
              onClick={handleExport}
              disabled={!canExport || exporting}
              title={
                canExport
                  ? 'Export the cleaned/derived data from the latest answer'
                  : 'Ask a question first to produce data to export'
              }
              className="text-xs font-medium text-blue-600 underline decoration-dotted hover:text-blue-800 disabled:cursor-not-allowed disabled:text-gray-300"
              data-testid="export-button"
            >
              {exporting ? 'Exporting…' : 'Export cleaned data'}
            </button>
            {exportMessage && (
              <span className="text-xs text-gray-500" data-testid="export-message">
                {exportMessage}
              </span>
            )}
          </div>
        </section>
      )}
    </main>
  )
}
