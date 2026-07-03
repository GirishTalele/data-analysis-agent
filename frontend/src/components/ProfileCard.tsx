import type { DatasetProfile } from '@/lib/api'

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (Array.isArray(value)) return value.map(String).join(', ')
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(2)
  return String(value)
}

export default function ProfileCard({ profile }: { profile: DatasetProfile }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm" data-testid="profile-card">
      <div className="mb-3 flex flex-wrap gap-4 text-sm text-gray-600">
        <span>
          <span className="font-semibold text-gray-900">{profile.row_count.toLocaleString()}</span> rows
        </span>
        <span>
          <span className="font-semibold text-gray-900">{profile.column_count}</span> columns
        </span>
      </div>
      <div className="max-h-72 overflow-auto rounded border border-gray-100">
        <table className="w-full min-w-[640px] text-left text-xs">
          <thead className="sticky top-0 bg-gray-50 text-gray-500">
            <tr>
              <th className="px-3 py-2 font-medium">Column</th>
              <th className="px-3 py-2 font-medium">Type</th>
              <th className="px-3 py-2 font-medium">Missing %</th>
              <th className="px-3 py-2 font-medium">Unique</th>
              <th className="px-3 py-2 font-medium">Min</th>
              <th className="px-3 py-2 font-medium">Max</th>
              <th className="px-3 py-2 font-medium">Sample</th>
            </tr>
          </thead>
          <tbody>
            {profile.columns.map(col => (
              <tr key={col.name} className="border-t border-gray-100">
                <td className="px-3 py-2 font-medium text-gray-900">{col.name}</td>
                <td className="px-3 py-2 text-gray-600">{col.dtype}</td>
                <td className="px-3 py-2 text-gray-600">{col.missing_pct.toFixed(1)}%</td>
                <td className="px-3 py-2 text-gray-600">{formatCell(col.unique_count)}</td>
                <td className="px-3 py-2 text-gray-600">{formatCell(col.min)}</td>
                <td className="px-3 py-2 text-gray-600">{formatCell(col.max)}</td>
                <td className="px-3 py-2 text-gray-600">{formatCell(col.sample_values)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
