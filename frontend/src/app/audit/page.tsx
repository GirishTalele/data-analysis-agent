'use client'

import { useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import {
  getCostSummary,
  listQueryRuns,
  type CostSummary,
  type QueryRun,
} from '@/lib/api'

const STATUS_OPTIONS = ['', 'success', 'failed', 'cannot_answer'] as const

export default function AuditPage() {
  const [runs, setRuns] = useState<QueryRun[]>([])
  const [costToday, setCostToday] = useState<CostSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<string>('')

  useEffect(() => {
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const [runList, summary] = await Promise.all([
          listQueryRuns({ limit: 200 }),
          getCostSummary('day'),
        ])
        setRuns(runList)
        setCostToday(summary)
      } catch {
        setError('Could not load the audit trail — is the server running?')
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return runs.filter(r => {
      if (statusFilter && r.execution_status !== statusFilter) return false
      if (!q) return true
      return (
        (r.answer_text ?? '').toLowerCase().includes(q) ||
        (r.generated_code ?? '').toLowerCase().includes(q)
      )
    })
  }, [runs, search, statusFilter])

  return (
    <main className="mx-auto max-w-5xl px-4 py-10">
      <header className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Audit trail &amp; cost</h1>
          <p className="text-sm text-gray-500">Every past query, its code, result, and cost.</p>
        </div>
        <Link
          href="/"
          className="rounded-md border border-gray-300 px-3 py-1.5 text-xs text-gray-700 hover:bg-gray-100"
          data-testid="back-link"
        >
          ← Back to chat
        </Link>
      </header>

      {/* Today's running cost total */}
      <div
        className="mb-6 flex flex-wrap gap-6 rounded-lg border border-gray-200 bg-white p-4 shadow-sm"
        data-testid="cost-summary"
      >
        <div>
          <div className="text-xs uppercase tracking-wide text-gray-400">Cost today</div>
          <div className="text-xl font-bold text-gray-900">
            ${(costToday?.total_cost_usd ?? 0).toFixed(4)}
          </div>
        </div>
        <div>
          <div className="text-xs uppercase tracking-wide text-gray-400">Tokens today</div>
          <div className="text-xl font-bold text-gray-900">
            {(costToday?.total_tokens ?? 0).toLocaleString()}
          </div>
        </div>
        <div>
          <div className="text-xs uppercase tracking-wide text-gray-400">Queries today</div>
          <div className="text-xl font-bold text-gray-900">{costToday?.query_count ?? 0}</div>
        </div>
      </div>

      {/* Search + filter */}
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <input
          type="text"
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Search code or answer text…"
          className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          data-testid="audit-search"
        />
        <select
          value={statusFilter}
          onChange={e => setStatusFilter(e.target.value)}
          className="rounded-lg border border-gray-300 px-3 py-2 text-sm shadow-sm"
          data-testid="audit-status-filter"
        >
          {STATUS_OPTIONS.map(s => (
            <option key={s} value={s}>
              {s === '' ? 'All statuses' : s}
            </option>
          ))}
        </select>
      </div>

      {loading ? (
        <p className="text-sm text-gray-400">Loading audit trail…</p>
      ) : error ? (
        <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      ) : filtered.length === 0 ? (
        <p className="text-sm text-gray-400" data-testid="audit-empty">
          {runs.length === 0
            ? 'No queries yet — ask a question on the chat page to populate the audit trail.'
            : 'No queries match your search/filter.'}
        </p>
      ) : (
        <div className="overflow-hidden rounded-lg border border-gray-200" data-testid="audit-list">
          <table className="w-full text-left text-xs">
            <thead className="bg-gray-50 text-gray-500">
              <tr>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 font-medium">Answer</th>
                <th className="px-3 py-2 font-medium">Code</th>
                <th className="px-3 py-2 font-medium">Tokens</th>
                <th className="px-3 py-2 font-medium">Cost</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map(r => (
                <tr key={r.id} className="border-t border-gray-100 align-top" data-testid="audit-row">
                  <td className="px-3 py-2">
                    <span
                      className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${
                        r.execution_status === 'success'
                          ? 'bg-green-100 text-green-700'
                          : 'bg-amber-100 text-amber-700'
                      }`}
                    >
                      {r.execution_status}
                    </span>
                  </td>
                  <td className="max-w-xs px-3 py-2 text-gray-700">{r.answer_text}</td>
                  <td className="max-w-sm px-3 py-2">
                    <pre className="overflow-x-auto whitespace-pre-wrap rounded bg-gray-900 p-2 text-[11px] text-gray-100">
                      <code>{r.generated_code}</code>
                    </pre>
                  </td>
                  <td className="px-3 py-2 text-gray-600">
                    {(r.prompt_tokens + r.completion_tokens).toLocaleString()}
                  </td>
                  <td className="px-3 py-2 text-gray-600">${r.estimated_cost_usd.toFixed(4)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  )
}
