# Capability: Cost & Audit Trail

## What It Does

Tracks the token usage and estimated cost of every query (Phase 1: per-query + running session total; Phase 2: day/all-time rollups) and persists every query, the code executed, and the result together with timestamps so the full history is queryable later.

## Inputs

| Input | Type | Source | Required |
|-------|------|--------|----------|
| `prompt_tokens`/`completion_tokens` per LLM call | integer | Gemini API response usage metadata, summed across all calls in a turn | yes |
| Configured per-token prices | numeric | `Settings` (`AGENT_GEMINI_INPUT_PRICE_PER_1M` / `..._OUTPUT_PRICE_PER_1M`) | yes |
| Configured USD→INR exchange rate | numeric | `Settings` (`AGENT_USD_TO_INR`, default `88.0`) | yes |
| Every `QueryRun`'s full record | see `spec/data.md` | written by `src/graph/runner.py` after each turn | yes |

## Outputs

| Output | Type | Destination |
|--------|------|-------------|
| Per-query cost/token badge (USD + INR) | JSON field on the `messages` response (`estimated_cost_usd`, `estimated_cost_inr`) | `POST /conversations/{id}/messages` response, rendered in the UI |
| Running session total (USD + INR) | JSON | `GET /conversations/{id}/messages` response (`session_cost_total_usd`, `session_cost_total_inr`, `session_tokens_total`) |
| Day/all-time rollup (Phase 2, USD + INR) | JSON | `GET /cost-summary` (`total_cost_usd`, `total_cost_inr`, `usd_to_inr_rate`) |
| Full audit trail (Phase 2 browsing UI; Phase 1 already stored) | list of `QueryRun` | `GET /query-runs` |

## External Calls

None beyond what `conversational-code-analysis` already makes — this capability is a persistence/aggregation layer over its outputs, not an independent external call.

## Business Rules

- Every turn — success, execution error, cannot-answer, clarification-needed, or fatal failure — produces exactly one `QueryRun` row. Nothing is skipped from the audit trail because it "didn't work."
- Cost is computed deterministically from recorded token counts and the configured prices — never estimated from prose or guessed.
- USD is the canonical, stored value (`QueryRun.estimated_cost_usd`); INR is a pure display-derived value computed as `cost_inr = cost_usd * usd_to_inr_rate` in the backend API response layer (one source of truth for both chat badges and the audit dashboard) — it is **never** stored and requires **no DB migration**. The rate is a fixed, configurable local setting (`AGENT_USD_TO_INR`) — there is no external FX API call.
- Cost is displayed in both currencies everywhere it appears, formatted `$0.0021 (₹0.18)` — USD rounded as today, INR to 2–4 decimals as appropriate for small values.
- The audit trail is append-only: no `QueryRun` row is ever updated or deleted after it's written (a re-ask creates a new row).
- Session total (Phase 1) is scoped to one `Conversation`; day/all-time totals (Phase 2) aggregate across all conversations for the local user.

## Success Criteria

- [ ] After N questions in one conversation, `GET /conversations/{id}/messages` returns a `session_tokens_total` equal to the sum of each individual `QueryRun.prompt_tokens + completion_tokens` in that conversation.
- [ ] Every one of N consecutive questions (mix of successful and deliberately-failing ones, e.g. one referencing a bad column) produces exactly N `QueryRun` rows, each with the correct `execution_status`.
- [ ] Restarting the app process and re-querying `GET /conversations/{id}/messages` returns the same history and the same `session_cost_total_usd` as before the restart (SQLite persistence survives a restart).
- [ ] (Phase 2) `GET /cost-summary?scope=day` returns a `total_cost_usd` equal to the sum of `estimated_cost_usd` for all `QueryRun`s created on the current date, across all conversations.
- [ ] Every response carrying a cost also carries the INR equivalent: `estimated_cost_inr == round(estimated_cost_usd * usd_to_inr_rate, ...)`, `session_cost_total_inr == round(session_cost_total_usd * usd_to_inr_rate, ...)`, and (Phase 2) `total_cost_inr == round(total_cost_usd * usd_to_inr_rate, ...)`, using the configured `AGENT_USD_TO_INR` rate which is echoed back as `usd_to_inr_rate`.
