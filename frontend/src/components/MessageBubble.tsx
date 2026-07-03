'use client'

import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { ChatMessage, QueryRun } from '@/lib/api'
import { formatCostPair } from '@/lib/cost'
import SummaryTable from './SummaryTable'
import Chart from './Chart'
import StepList from './StepList'

function CostBadge({ queryRun }: { queryRun: QueryRun }) {
  const tokens = queryRun.prompt_tokens + queryRun.completion_tokens
  return (
    <span
      className="inline-block rounded-full bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-500"
      data-testid="cost-badge"
    >
      {tokens.toLocaleString()} tokens ·{' '}
      {formatCostPair(queryRun.estimated_cost_usd, queryRun.estimated_cost_inr)}
    </span>
  )
}

function CodeToggle({ code }: { code: string }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="mt-2">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="text-xs font-medium text-blue-600 hover:underline"
        data-testid="view-code-toggle"
      >
        {open ? 'Hide code' : 'View code'}
      </button>
      {open && (
        <pre className="mt-2 overflow-x-auto rounded-md bg-gray-900 p-3 text-xs text-gray-100">
          <code>{code}</code>
        </pre>
      )}
    </div>
  )
}

function AnomalyBanner({ anomalies }: { anomalies: unknown[] }) {
  if (!anomalies?.length) return null
  return (
    <div
      className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800"
      data-testid="anomaly-banner"
    >
      <div className="mb-1 font-semibold">Data-quality note</div>
      <ul className="list-disc space-y-0.5 pl-4">
        {anomalies.map((a, i) => (
          <li key={i}>{typeof a === 'string' ? a : JSON.stringify(a)}</li>
        ))}
      </ul>
    </div>
  )
}

function FollowUpChips({
  suggestions,
  onFollowUp,
}: {
  suggestions: string[]
  onFollowUp?: (question: string) => void
}) {
  if (!suggestions?.length) return null
  return (
    <div className="mt-3 flex flex-wrap gap-2" data-testid="follow-up-chips">
      {suggestions.map((s, i) => (
        <button
          key={i}
          type="button"
          onClick={() => onFollowUp?.(s)}
          disabled={!onFollowUp}
          className="rounded-full border border-blue-200 bg-blue-50 px-3 py-1 text-xs text-blue-700 hover:bg-blue-100 disabled:cursor-not-allowed disabled:opacity-60"
          data-testid="follow-up-chip"
        >
          {s}
        </button>
      ))}
    </div>
  )
}

export default function MessageBubble({
  message,
  queryRun,
  onFollowUp,
}: {
  message: ChatMessage
  queryRun?: QueryRun
  onFollowUp?: (question: string) => void
}) {
  const isUser = message.role === 'user'
  const isErrorRun = queryRun && queryRun.execution_status !== 'success'

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm shadow-sm ${
          isUser
            ? 'bg-blue-600 text-white'
            : isErrorRun
              ? 'border border-amber-200 bg-amber-50 text-amber-900'
              : 'border border-gray-200 bg-white text-gray-900'
        }`}
        data-testid={isUser ? 'user-message' : 'assistant-message'}
      >
        <div className="prose prose-sm max-w-none prose-p:my-1 prose-headings:my-2">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
        </div>

        {queryRun && queryRun.execution_status === 'success' && (
          <>
            <StepList stepCount={queryRun.step_count} />
            {/* Order per spec/ui.md: key numbers (in prose) -> table -> chart -> code. */}
            <SummaryTable table={queryRun.result_table} />
            <Chart queryRun={queryRun} />
            {queryRun.generated_code && <CodeToggle code={queryRun.generated_code} />}
            <AnomalyBanner anomalies={queryRun.anomalies} />
            <FollowUpChips
              suggestions={queryRun.follow_up_suggestions}
              onFollowUp={onFollowUp}
            />
            <div className="mt-2">
              <CostBadge queryRun={queryRun} />
            </div>
          </>
        )}
      </div>
    </div>
  )
}
