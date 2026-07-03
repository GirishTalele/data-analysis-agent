// Cost formatting helpers — single source of truth for how cost is shown.
// Per spec/capabilities/cost-and-audit-trail.md: cost is displayed in BOTH
// currencies everywhere it appears, formatted `$0.0021 (₹0.18)`.
//
// USD and INR values (and the rate) come from the backend API responses — the
// frontend NEVER computes the rate. `formatCostPair` takes the USD value and
// the INR value the API already returned.

// USD: rounded to 4 decimals, as the app did before INR was added.
export function formatUsd(usd: number): string {
  return `$${(usd ?? 0).toFixed(4)}`
}

// INR: 2-4 decimals so small values aren't shown as "0.00". We show 4 decimals
// for values under ₹1 (typical per-query cost), otherwise 2.
export function formatInr(inr: number): string {
  const value = inr ?? 0
  const decimals = Math.abs(value) < 1 ? 4 : 2
  return `₹${value.toFixed(decimals)}`
}

// The canonical `$X (₹Y)` pair rendered wherever a cost appears.
export function formatCostPair(usd: number, inr: number): string {
  return `${formatUsd(usd)} (${formatInr(inr)})`
}
