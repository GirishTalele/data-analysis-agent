'use client'

import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { ChatMessage, QueryRun } from '@/lib/api'

function formatCost(usd: number): string {
  return `$${usd.toFixed(4)}`
}

function CostBadge({ queryRun }: { queryRun: QueryRun }) {
  const tokens = queryRun.prompt_tokens + queryRun.completion_tokens
  return (
    <span
      className="inline-block rounded-full bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-500"
      data-testid="cost-badge"
    >
      {tokens.toLocaleString()} tokens · {formatCost(queryRun.estimated_cost_usd)}
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

function ChartStub() {
  return (
    <div className="mt-3 rounded-md border border-dashed border-gray-300 bg-gray-50 p-3 text-center text-xs text-gray-400">
      Interactive charts — coming in a future update
    </div>
  )
}

export default function MessageBubble({
  message,
  queryRun,
}: {
  message: ChatMessage
  queryRun?: QueryRun
}) {
  const isUser = message.role === 'user'
  const isErrorRun = queryRun && queryRun.execution_status !== 'success'
  const hasKeyNumbers = queryRun && Object.keys(queryRun.key_numbers ?? {}).length > 0

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
            {queryRun.generated_code && <CodeToggle code={queryRun.generated_code} />}
            {hasKeyNumbers && <ChartStub />}
            <div className="mt-2">
              <CostBadge queryRun={queryRun} />
            </div>
          </>
        )}
      </div>
    </div>
  )
}
