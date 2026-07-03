'use client'

import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { QueryRun } from '@/lib/api'

type ChartPoint = { label: string; value: number }

function isNumeric(v: unknown): v is number {
  return typeof v === 'number' && Number.isFinite(v)
}

// Derives chart data for an answer, preferring a 2-column result_table
// (one categorical + one numeric) and falling back to numeric key_numbers.
// Returns null when the answer has nothing chartable.
export function deriveChartData(queryRun: QueryRun): {
  points: ChartPoint[]
  valueLabel: string
} | null {
  const table = queryRun.result_table
  if (table && table.columns?.length === 2 && table.rows?.length) {
    // Find which of the two columns is numeric (based on the first row).
    const first = table.rows[0]
    const numericIdx = isNumeric(first[1]) ? 1 : isNumeric(first[0]) ? 0 : -1
    if (numericIdx !== -1) {
      const labelIdx = numericIdx === 1 ? 0 : 1
      const points = table.rows
        .filter(r => isNumeric(r[numericIdx]))
        .map(r => ({ label: String(r[labelIdx]), value: r[numericIdx] as number }))
      if (points.length) {
        return { points, valueLabel: table.columns[numericIdx] }
      }
    }
  }

  // Fallback: numeric key_numbers.
  const entries = Object.entries(queryRun.key_numbers ?? {}).filter(([, v]) => isNumeric(v))
  if (entries.length >= 2) {
    return {
      points: entries.map(([k, v]) => ({ label: k, value: v as number })),
      valueLabel: 'value',
    }
  }

  return null
}

export default function Chart({ queryRun }: { queryRun: QueryRun }) {
  const data = deriveChartData(queryRun)
  if (!data) return null

  return (
    <div className="mt-3 rounded-md border border-gray-200 bg-white p-2" data-testid="answer-chart">
      <div className="h-64 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data.points} margin={{ top: 8, right: 8, left: 0, bottom: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#eee" />
            <XAxis dataKey="label" tick={{ fontSize: 11 }} interval={0} angle={-15} height={50} />
            <YAxis tick={{ fontSize: 11 }} />
            <Tooltip />
            <Bar dataKey="value" name={data.valueLabel} fill="#2563eb" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
