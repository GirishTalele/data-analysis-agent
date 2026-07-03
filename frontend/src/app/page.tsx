'use client'

import { useRef, useState } from 'react'

type SendResultData = {
  status: 'sent'
  source_filename: string
  period: string
  recipients_sent: string[]
  recipients_rejected: string[]
  warnings: string[]
}

type ErrorInfo = {
  code: string
  message: string
}

type UiState = 'idle' | 'loading' | 'success' | 'error'

const ERROR_HINTS: Record<string, string> = {
  UNSUPPORTED_FILE_TYPE: 'Only .csv and .qvd files are supported — check the file type and try again.',
  FILE_UNREADABLE: 'The file could not be read — check that it is not corrupt or empty.',
  GR_VALUE_COLUMN_MISSING: 'Check that the file has Plant, Buyer, and GR Value columns.',
  GR_VALUE_UNPARSABLE: 'Check that the GR Value column contains numeric values.',
  NO_GROUPING_COLUMN: 'Check that the file has Plant, Buyer, and GR Value columns.',
  NO_VALID_RECIPIENTS: 'Enter at least one valid email address.',
  SMTP_SEND_FAILED: 'The mail server may be unreachable — contact IT.',
  INTERNAL_ERROR: 'An unexpected error occurred — try again, and contact support if it persists.',
  NETWORK_ERROR: 'Could not reach the server — confirm it is running and try again.',
}

function errorHint(code: string): string {
  return ERROR_HINTS[code] ?? 'Fix the issue above and try again.'
}

function hasAtLeastOneRecipientLine(recipients: string): boolean {
  return recipients
    .split(/[,\n]/)
    .some(line => line.trim().length > 0)
}

export default function Home() {
  const [file, setFile] = useState<File | null>(null)
  const [recipients, setRecipients] = useState('')
  const [uiState, setUiState] = useState<UiState>('idle')
  const [result, setResult] = useState<SendResultData | null>(null)
  const [errorInfo, setErrorInfo] = useState<ErrorInfo | null>(null)
  const [isDragging, setIsDragging] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const canSubmit = file !== null && hasAtLeastOneRecipientLine(recipients) && uiState !== 'loading'

  function chooseFile(next: File | null) {
    setFile(next)
  }

  function onDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault()
    setIsDragging(false)
    const dropped = e.dataTransfer.files?.[0]
    if (dropped) chooseFile(dropped)
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!canSubmit || !file) return

    // Loading: only the button changes — the previous status panel (if any)
    // stays put until the new outcome is known, per spec/ui.md's Loading state.
    setUiState('loading')

    try {
      const formData = new FormData()
      formData.append('file', file)
      formData.append('recipients', recipients)

      const res = await fetch('/reports/send', {
        method: 'POST',
        body: formData,
      })

      const body = await res.json().catch(() => null)

      if (!res.ok) {
        const detail = body?.detail
        setResult(null)
        setErrorInfo({
          code: detail?.code ?? 'INTERNAL_ERROR',
          message: detail?.message ?? `Request failed (${res.status})`,
        })
        setUiState('error')
        return
      }

      setErrorInfo(null)
      setResult(body?.data as SendResultData)
      setUiState('success')
    } catch {
      setResult(null)
      setErrorInfo({
        code: 'NETWORK_ERROR',
        message: 'Network error — is the server running?',
      })
      setUiState('error')
    }
  }

  const isLoading = uiState === 'loading'

  return (
    <main className="mx-auto max-w-2xl px-4 py-16">
      <h1 className="mb-2 text-3xl font-bold tracking-tight">GR Report Agent</h1>
      <p className="mb-8 text-sm text-gray-500">
        Upload your GR export (CSV or QVD) to email a plant-wise and Top-10-Buyer GR value report.
      </p>

      <form onSubmit={handleSubmit} className="space-y-6">
        {/* File input — drag & drop or click to browse */}
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">GR data file</label>
          <div
            onClick={() => fileInputRef.current?.click()}
            onDragOver={e => {
              e.preventDefault()
              setIsDragging(true)
            }}
            onDragLeave={() => setIsDragging(false)}
            onDrop={onDrop}
            role="button"
            tabIndex={0}
            aria-label="Choose or drop a CSV or QVD file"
            className={`cursor-pointer rounded-lg border-2 border-dashed p-6 text-center transition-colors ${
              isDragging ? 'border-blue-500 bg-blue-50' : 'border-gray-300 bg-white hover:border-gray-400'
            }`}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".csv,.qvd"
              className="hidden"
              onChange={e => chooseFile(e.target.files?.[0] ?? null)}
              disabled={isLoading}
            />
            {file ? (
              <p className="text-sm font-medium text-gray-800">{file.name}</p>
            ) : (
              <>
                <p className="text-sm text-gray-600">Drag and drop a .csv or .qvd file here, or click to browse.</p>
                <p className="mt-1 text-xs text-gray-400">Accepted formats: .csv, .qvd</p>
              </>
            )}
          </div>
        </div>

        {/* Recipients */}
        <div>
          <label htmlFor="recipients" className="mb-1 block text-sm font-medium text-gray-700">
            Recipients
          </label>
          <textarea
            id="recipients"
            className="w-full rounded-lg border border-gray-300 p-3 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            rows={4}
            placeholder="jane.doe@company.com, plant.head@company.com"
            value={recipients}
            onChange={e => setRecipients(e.target.value)}
            disabled={isLoading}
          />
          <p className="mt-1 text-xs text-gray-500">
            One or more email addresses, separated by commas or new lines.
          </p>
        </div>

        <button
          type="submit"
          disabled={!canSubmit}
          className="rounded-lg bg-blue-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isLoading ? 'Generating & sending report…' : 'Send Report'}
        </button>
      </form>

      {/* Status / result area. During loading, whatever panel was already
          showing stays put — only the button above changes — so the user
          is never confused about what's happening. */}
      <div className="mt-8">
        {!result && !errorInfo && (
          <p className="rounded-lg border border-gray-200 bg-white p-4 text-sm text-gray-500 shadow-sm">
            Choose a GR export and enter at least one recipient to send the plant-wise and Top-10-Buyer GR value
            report.
          </p>
        )}

        {result && (
          <div className="space-y-3">
            <div className="rounded-lg border border-green-200 bg-green-50 p-4 text-sm text-green-800 shadow-sm">
              <p className="font-medium">
                Report sent to {result.recipients_sent.length} recipient{result.recipients_sent.length === 1 ? '' : 's'}.
              </p>
              <p className="mt-1 text-green-700">Source file: {result.source_filename}</p>
              <p className="text-green-700">Reporting period: {result.period}</p>
            </div>

            {result.warnings.length > 0 && (
              <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800 shadow-sm">
                <p className="font-medium">Warnings</p>
                <ul className="mt-1 list-disc space-y-1 pl-5">
                  {result.warnings.map((warning, i) => (
                    <li key={i}>{warning}</li>
                  ))}
                </ul>
              </div>
            )}

            {result.recipients_rejected.length > 0 && (
              <div className="rounded-lg border border-gray-200 bg-white p-4 text-sm text-gray-600 shadow-sm">
                <p className="font-medium text-gray-700">Skipped invalid addresses</p>
                <p className="mt-1">{result.recipients_rejected.join(', ')}</p>
              </div>
            )}
          </div>
        )}

        {errorInfo && (
          <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800 shadow-sm">
            <p className="font-medium">{errorInfo.message}</p>
            <p className="mt-1 text-red-700">{errorHint(errorInfo.code)}</p>
          </div>
        )}
      </div>
    </main>
  )
}
