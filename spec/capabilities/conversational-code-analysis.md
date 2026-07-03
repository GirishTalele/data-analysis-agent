# Capability: Conversational Code-Gen Analysis

## What It Does

Answers a natural-language question about an uploaded dataset by having the LLM write real pandas code, executing that code locally against the real data, and composing a plain-language answer from the (summarized) result — Phase 1 as a single generate→execute→answer pass, Phase 2 as a full iterative ReAct loop (write → run → inspect → refine, up to a step limit) with proactive follow-up suggestions and anomaly flagging.

## Inputs

| Input | Type | Source | Required |
|-------|------|--------|----------|
| `question` | text | `POST /conversations/{id}/messages` | yes |
| `schema_context` | JSON (columns/dtypes/stats) | latest `DatasetProfile` for the conversation's dataset | yes |
| `history_context` | list of prior turns | `chat_messages` for the conversation | no (empty on first turn) |

## Outputs

| Output | Type | Destination |
|--------|------|-------------|
| `answer_text` + `key_numbers` | text + JSON | `ChatMessage` (assistant) + `QueryRun.answer_text`/`key_numbers` |
| `generated_code` | text | `QueryRun.generated_code`, shown to the user in a collapsible view |
| `prompt_tokens` / `completion_tokens` / `estimated_cost_usd` | numeric | `QueryRun`, shown per-query and rolled into the session total |
| `follow_up_suggestions` (Phase 2) | list[str] | `QueryRun.follow_up_suggestions_json`, rendered as clickable chips |
| `anomalies` (Phase 2) | list[str] | `QueryRun.anomalies_json`, rendered as a banner |

## External Calls

| System | Operation | On Failure |
|--------|-----------|------------|
| Gemini (`generate_code`, `compose_answer`, and Phase-2 `check_clarity`) | LLM calls per `spec/agent.md` | SDK exception → `handle_error` node → `QueryRun.execution_status="failed"` with a human `error_message`; never a raw stack trace to the user |
| Sandbox subprocess (`src/sandbox/executor.py`) | Executes generated pandas code against the real local file | Captured as `execution_error`, routed to `cannot_answer` (Phase 1) or a retry (Phase 2, up to `max_steps`) |

## Business Rules

- The LLM never receives raw row-level data at any step — only schema/stats (`schema_context`), generated code, and `summarize_for_llm()`-truncated results. This is enforced in code, not just prompted for (`spec/architecture.md`).
- Phase 1: exactly one generate→execute attempt per question (`max_steps=1`); a code execution failure goes straight to a clear "can't answer, here's why" response, never a raw error.
- Phase 2: up to `AGENT_MAX_STEPS` (default 5) generate→execute attempts per question, with the failed code's error fed back into the next `generate_code` call; a live step list is shown in the UI while this runs.
- Phase 2: when the question is genuinely ambiguous or unanswerable given the schema (e.g. a trend request with no date column), the agent asks a clarifying question or explains why, before/instead of running code.
- Phase 2: after every successful answer, the agent proposes 2-3 follow-up questions and flags any data-quality anomalies it noticed in the schema/stats/result — these are generated from the same `compose_answer` call, not a separate round trip.
- Every attempt, successful or not, is recorded as exactly one `QueryRun` row (the audit trail) — see the `cost-and-audit-trail` capability.

## Success Criteria

- [ ] Given a fixture CSV with a precomputed answer (e.g. a known mean), asking the corresponding question returns that exact numeric answer (within floating-point tolerance) in `key_numbers`, not just a non-empty response.
- [ ] The literal prompt string sent to `LLMClient.call_model()` in `compose_answer` never contains more than `AGENT_MAX_SUMMARY_ROWS` distinct row-like records — verified by an automated test that inspects the outbound prompt.
- [ ] Asking a question whose generated code references a nonexistent column returns a `cannot_answer` response naming the problem in plain language, with `QueryRun.execution_status="execution_error"` or `"cannot_answer"` recorded — never an unhandled exception surfaced to the API caller.
- [ ] (Phase 2) A question requiring at least 2 refinement attempts (verified via a fixture that trips a fixable code error on the first attempt) succeeds by the second attempt, with `QueryRun.step_count >= 2`.
- [ ] (Phase 2) Every successful answer includes 2-3 non-empty `follow_up_suggestions`.
