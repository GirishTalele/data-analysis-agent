# Capability: Cost & Audit Trail

## What It Does

Tracks the token usage and estimated cost of every query (Phase 1: per-query + running session total; Phase 2: day/all-time rollups) and persists every query, the code executed, and the result together with timestamps so the full history is queryable later.

## Inputs

| Input | Type | Source | Required |
|-------|------|--------|----------|
| `prompt_tokens`/`completion_tokens` per LLM call | integer | Gemini API response usage metadata, summed across all calls in a turn | yes |
| Configured per-token prices | numeric | `Settings` (`AGENT_GEMINI_INPUT_PRICE_PER_1M` / `..._OUTPUT_PRICE_PER_1M`) | yes |
| Every `QueryRun`'s full record | see `spec/data.md` | written by `src/graph/runner.py` after each turn | yes |

## Outputs

| Output | Type | Destination |
|--------|------|-------------|
| Per-query cost/token badge | JSON field on the `messages` response | `POST /conversations/{id}/messages` response, rendered in the UI |
| Running session total | JSON | `GET /conversations/{id}/messages` response (`session_cost_total_usd`, `session_tokens_total`) |
| Day/all-time rollup (Phase 2) | JSON | `GET /cost-summary` |
| Full audit trail (Phase 2 browsing UI; Phase 1 already stored) | list of `QueryRun` | `GET /query-runs` |

## External Calls

None beyond what `conversational-code-analysis` already makes — this capability is a persistence/aggregation layer over its outputs, not an independent external call.

## Business Rules

- Every turn — success, execution error, cannot-answer, clarification-needed, or fatal failure — produces exactly one `QueryRun` row. Nothing is skipped from the audit trail because it "didn't work."
- Cost is computed deterministically from recorded token counts and the configured prices — never estimated from prose or guessed.
- The audit trail is append-only: no `QueryRun` row is ever updated or deleted after it's written (a re-ask creates a new row).
- Session total (Phase 1) is scoped to one `Conversation`; day/all-time totals (Phase 2) aggregate across all conversations for the local user.

## Success Criteria

- [ ] After N questions in one conversation, `GET /conversations/{id}/messages` returns a `session_tokens_total` equal to the sum of each individual `QueryRun.prompt_tokens + completion_tokens` in that conversation.
- [ ] Every one of N consecutive questions (mix of successful and deliberately-failing ones, e.g. one referencing a bad column) produces exactly N `QueryRun` rows, each with the correct `execution_status`.
- [ ] Restarting the app process and re-querying `GET /conversations/{id}/messages` returns the same history and the same `session_cost_total_usd` as before the restart (SQLite persistence survives a restart).
- [ ] (Phase 2) `GET /cost-summary?scope=day` returns a `total_cost_usd` equal to the sum of `estimated_cost_usd` for all `QueryRun`s created on the current date, across all conversations.
