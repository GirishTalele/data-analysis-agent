import type { ResultTable } from '@/lib/api'

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'number') {
    return Number.isInteger(value) ? value.toLocaleString() : value.toFixed(2)
  }
  return String(value)
}

// Renders query_run.result_table ({columns, rows}) as a plain HTML table,
// positioned between the key numbers and the chart in the answer bubble
// (per spec/ui.md). Returns null when there is no tabular data.
export default function SummaryTable({ table }: { table: ResultTable | null | undefined }) {
  if (!table || !table.columns?.length || !table.rows?.length) return null

  return (
    <div
      className="mt-3 max-h-72 overflow-auto rounded-md border border-gray-200"
      data-testid="summary-table"
    >
      <table className="w-full text-left text-xs">
        <thead className="sticky top-0 bg-gray-50 text-gray-500">
          <tr>
            {table.columns.map(col => (
              <th key={col} className="px-3 py-2 font-medium">
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row, i) => (
            <tr key={i} className="border-t border-gray-100">
              {row.map((cell, j) => (
                <td key={j} className="px-3 py-2 text-gray-700">
                  {formatCell(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
