'use client'

// Labels for the reasoning steps the agent runs through. The backend runs
// synchronously and returns a step_count; we render one entry per step so the
// list reflects real work rather than invented stages.
const STEP_LABELS = ['Writing code…', 'Running code…', 'Refining…']

function labelForStep(index: number, total: number): string {
  // First step writes code, last step composes the answer; the middle steps
  // are refinement passes.
  if (index === 0) return 'Writing code…'
  if (index === total - 1) return total > 2 ? 'Refining…' : 'Running code…'
  return 'Running code…'
}

// While a request is in flight we show a live "working" animation. Once the
// answer returns, we render one completed step per returned step_count.
export default function StepList({
  stepCount,
  inFlight,
}: {
  stepCount?: number
  inFlight?: boolean
}) {
  if (inFlight) {
    return (
      <div
        className="flex flex-col gap-1.5 rounded-2xl border border-gray-200 bg-white px-4 py-3 text-sm shadow-sm"
        data-testid="step-list"
      >
        {STEP_LABELS.map((label, i) => (
          <div key={label} className="flex items-center gap-2 text-gray-600">
            <span
              className="h-3 w-3 animate-spin rounded-full border-2 border-blue-600 border-t-transparent"
              style={{ animationDelay: `${i * 120}ms` }}
              aria-hidden
            />
            {label}
          </div>
        ))}
      </div>
    )
  }

  if (!stepCount || stepCount < 1) return null

  const steps = Array.from({ length: stepCount }, (_, i) => labelForStep(i, stepCount))

  return (
    <div className="mt-2 flex flex-col gap-1" data-testid="step-list">
      {steps.map((label, i) => (
        <div key={i} className="flex items-center gap-2 text-xs text-gray-500">
          <span className="flex h-4 w-4 items-center justify-center rounded-full bg-green-100 text-[10px] text-green-700">
            ✓
          </span>
          <span>
            Step {i + 1}: {label.replace('…', '')}
          </span>
        </div>
      ))}
    </div>
  )
}
