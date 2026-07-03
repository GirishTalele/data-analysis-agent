# Agent

---

## Agent Architecture Pattern

| Pattern | Use when |
|---------|----------|
| **Single-agent loop** | One LLM drives a deterministic tool-call loop. No branches, no handoffs. |
| **Graph (LangGraph)** | Multi-step pipeline with conditional edges, checkpointing, or parallel nodes. |
| **Multi-agent** | Specialised sub-agents with distinct roles; orchestrator routes between them. |
| **Supervisor** | One supervisor LLM dispatches to worker agents based on task type. |
| **Human-in-the-loop** | Execution pauses at defined checkpoints for user review or approval. |

**Chosen:** **Graph (LangGraph)**, implementing a **ReAct-style loop** (`harness/patterns/agentic-ai.md` #17 + #5, composed with #22 LLM-Generated Code Execution): reason → generate code → act (execute) → observe → decide (answer / iterate / clarify / can't-answer). This is the correct floor per the agentic-ai catalogue for "arbitrary, open-ended questions about structured data" — a fixed op-list is explicitly the anti-pattern it warns against. Guardrails (#18, the raw-row boundary + AST sandbox check) and exception handling (#12) are always on. Planning (#6) and proactive suggestion/anomaly generation are folded into `compose_answer` in Phase 2 rather than a separate agent — a second agent isn't warranted for a single local user.

**Phase status:** the graph below is the **full design**. Phase 1 wires every node but activates only the single-pass path (`max_steps=1`, `check_clarity` stubbed to always "clear"). Phase 2 raises `max_steps` and activates `check_clarity` for real — no structural change to the graph, only to node behaviour and routing conditions. Each node/edge below is marked **[P1 active]** or **[P2 activates]**.

---

## LLM Provider & Model

| Agent / Node | Provider | Model ID | Rationale |
|-------------|----------|----------|-----------|
| `check_clarity` | Gemini | `gemini-3.1-pro-preview` (via `AGENT_LLM_MODEL`) | Small classification call; quality matters more than latency since a wrong "clear" verdict wastes a full code-gen/execute round trip. |
| `generate_code` | Gemini | `gemini-3.1-pro-preview` | Code generation needs the strongest available reasoning to write correct pandas against an arbitrary schema. |
| `compose_answer` | Gemini | `gemini-3.1-pro-preview` | Narration quality (correct numbers, clear language, Phase-2 follow-ups/anomalies) matters most here. |

**Fallback behaviour:** on a Gemini API error (rate limit, 5xx, timeout), the calling node catches the SDK exception, sets `state["error"]`, and routes to `handle_error`, which records `status=failed` with a human-readable `error_message` on the `QueryRun` row. No retry-with-backoff in Phase 1 (single local user, low volume); Phase 2 may add one retry with backoff for transient 5xx/timeout errors specifically — a permanent guardrail, not a test/offline stub path.

**Prompt strategy:** system/user split via `.md` templates in `src/prompts/`. `generate_code.md` (system) + a user message built from `schema_context` + `question` (+ prior `execution_error` on a retry). `compose_answer.md` (system, requests structured JSON: `{"answer": str, "key_numbers": {...}}` in Phase 1; `{"answer": str, "key_numbers": {...}, "follow_up_suggestions": [str], "anomalies": [str], "result_table": {"columns": [str], "rows": [[cell]]} | null}` in Phase 2) + a user message built from `schema_context` + the *summarized* execution result.

---

## Tools & Tool Calling

| Tool name | Description | Inputs | Output | Side-effects |
|-----------|-------------|--------|--------|--------------|
| `run_code` | Executes LLM-generated pandas code in a sandboxed subprocess against the locally stored dataset file. | `code: str`, `dataset_path: Path`, `file_type: str` | `ExecutionResult(result: Any \| None, stdout: str, error: str \| None)` | Spawns a subprocess; reads the local file; no network, no writes outside a temp dir. |
| `summarize_for_llm` | Enforces the raw-row privacy boundary — truncates/aggregates an execution result before it may enter any LLM prompt. | `result: Any` | JSON-safe `dict`/scalar, capped per `spec/architecture.md` | None (pure function). |

**Tool selection strategy:** not LLM-chosen — the graph always calls `run_code` on the code `generate_code` produced (forced single tool per turn), then always calls `summarize_for_llm` on the raw result before any further LLM call.

**Tool failure handling:** `run_code` never raises out of the node — subprocess timeout, non-zero exit, or an AST guardrail rejection are all captured into `ExecutionResult.error` and routed through `observe_result` → `decide_next` (see below), never crashing the process.

---

## Agent State

```python
class AgentState(TypedDict, total=False):
    # Identity
    run_id: str                          # QueryRun id, set at initialisation
    conversation_id: str
    dataset_id: str

    # Input
    question: str                        # the user's natural-language question
    schema_context: dict                 # columns/dtypes/stats from DatasetProfile — NEVER raw rows
    history_context: list[dict]          # prior {role, content} turns in this conversation, most-recent-first, capped

    # Control (iteration)
    step_count: int                      # attempts made so far at generate_code -> execute_code
    max_steps: int                       # AGENT_MAX_STEPS; 1 in Phase 1, configurable (default 5) in Phase 2

    # Clarification branch [P2 activates]
    clarity_checked: bool                # always True by the time generate_code runs
    needs_clarification: bool            # [P1: hardcoded False by the stub] [P2: real LLM classification]
    clarification_question: str | None

    # Code-gen / execution
    generated_code: str | None
    execution_result: dict | None        # summarized (never raw-row) result
    execution_error: str | None

    # Answer
    answer_text: str | None
    key_numbers: dict | None
    follow_up_suggestions: list[str]     # [P2 activates] always [] in Phase 1
    anomalies: list[str]                 # [P2 activates] always [] in Phase 1
    result_table: dict | None            # [P2 activates] {"columns":[...], "rows":[...]}; None in Phase 1 and for scalar-only answers

    # Cost / audit
    prompt_tokens: int
    completion_tokens: int
    estimated_cost_usd: float

    # Terminal status
    status: str                          # "success" | "execution_error" | "cannot_answer" | "clarification_needed" | "failed"
    error: str | None                    # set by any node on a fatal/unrecoverable failure
```

---

## Nodes / Steps

### `check_clarity` **[P1: stub — always returns `needs_clarification=False`] [P2: activates]**

**Reads from state:** `question`, `schema_context`
**Writes to state:** `clarity_checked`, `needs_clarification`, `clarification_question`
**LLM call:** Phase 1 — no. Phase 2 — yes; asks Gemini whether the question is answerable given the schema (e.g. a trend request with no date column) and, if not, what to ask the user.
**External calls:** Phase 2 only — Gemini (`handle_error` on failure).
**Behaviour:** Phase 1 always proceeds straight through so the mandatory Phase-1 scope (ask → answer, no clarification round-trip) is preserved. Phase 2 turns this into a real classification step.

### `generate_code` **[P1 active]**

**Reads from state:** `question`, `schema_context`, `history_context`, `execution_error` (on a retry)
**Writes to state:** `generated_code`, `prompt_tokens` (+=), `completion_tokens` (+=), `step_count` (+=1)
**LLM call:** yes — `src/prompts/generate_code.md` system prompt; output format: fenced pandas code block, parsed to plain text.
**External calls:** Gemini → `handle_error` on SDK exception.
**Behaviour:** Produces pandas code assigning its answer to a `result` variable, using only `df` (the loaded dataset) and `pd`. On a retry (Phase 2), the prior `execution_error` is included in the prompt so the model can self-correct.

### `execute_code` **[P1 active]**

**Reads from state:** `generated_code`, `dataset_id` (resolves to the stored file path)
**Writes to state:** `execution_result` (raw, pre-summary), `execution_error`
**LLM call:** no.
**External calls:**

| System | Operation | On Failure |
|--------|-----------|------------|
| Sandbox subprocess (`src/sandbox/executor.py::run_code`) | Runs the generated code against the real local file | Captured into `execution_error`; routes to `observe_result`, never crashes the API. A missing/corrupted dataset file is a fatal error → `handle_error`. |

**Behaviour:** Spawns the subprocess with a hard timeout, applies the AST guardrail, returns either a result or an error — see `spec/architecture.md` → Sandboxed Code Execution.

### `observe_result` **[P1 active]**

**Reads from state:** `execution_result`, `execution_error`
**Writes to state:** `execution_result` (replaced with `summarize_for_llm()`'s output)
**LLM call:** no.
**Behaviour:** Applies the raw-row privacy boundary (`summarize_for_llm`) to whatever the sandbox returned, so nothing downstream of this node can ever see raw rows.

### `decide_next` (router, not a state-mutating node) **[P1: iterate branch unreachable; P2 activates]**

Reads `needs_clarification`, `execution_error`, `step_count`, `max_steps` and returns one of: `"ask_clarification"`, `"generate_code"` (iterate), `"cannot_answer"`, `"compose_answer"`.

- `needs_clarification` is True → `"ask_clarification"` (Phase 1: never True, so unreachable).
- `execution_error` is set and `step_count < max_steps` → `"generate_code"` (loop-back; Phase 1: `max_steps=1` and `step_count` is already 1 after the first attempt, so this is always False — the edge exists in the compiled graph but is never taken).
- `execution_error` is set and `step_count >= max_steps` → `"cannot_answer"`.
- otherwise → `"compose_answer"`.

### `compose_answer` **[P1 active, minimal fields; P2 adds follow-ups/anomalies]**

**Reads from state:** `question`, `schema_context`, `execution_result` (summarized)
**Writes to state:** `answer_text`, `key_numbers`, `follow_up_suggestions` (Phase 1: `[]`), `anomalies` (Phase 1: `[]`), `result_table` (Phase 1: `None`), `prompt_tokens` (+=), `completion_tokens` (+=), `status="success"`
**LLM call:** yes — `src/prompts/compose_answer.md`, structured JSON output.
**External calls:** Gemini → `handle_error` on SDK exception.
**Behaviour:** Turns the summarized result into a plain-language answer naming the key number(s). Phase 2 additionally asks for 2-3 follow-up questions and any anomalies noticed in the schema/stats/result (e.g. a suspicious spike, a column that's mostly null). Phase 2 also emits `result_table` — a structured `{"columns": [...], "rows": [...]}` summary table derived from the *summarized* execution result (a dict/records or `.describe()` output) when the answer is a tabular/breakdown (e.g. a groupby), and `null` for scalar-only answers. `result_table` is built only from the already-summarized result — it reuses the existing raw-row privacy boundary and must never exceed `AGENT_MAX_SUMMARY_ROWS` rows (never bypasses `summarize_for_llm`; see `spec/architecture.md` → Raw-Row Privacy Boundary). Persisted to `QueryRun.result_table_json`.

### `ask_clarification` **[P1: wired but unreachable; P2 activates]**

**Reads from state:** `clarification_question`
**Writes to state:** `answer_text` = the clarification question, `status="clarification_needed"`
**LLM call:** no (the question was already produced by `check_clarity`).
**Behaviour:** Ends the turn by returning the clarifying question to the user instead of running code.

### `cannot_answer` **[P1 active]**

**Reads from state:** `execution_error`, `question`, `schema_context`
**Writes to state:** `answer_text` = a clear explanation of why the data can't answer the question, `status="cannot_answer"`
**LLM call:** no in Phase 1 (templated from `execution_error`); Phase 2 may route this through Gemini for a friendlier explanation once `check_clarity`/iteration are both active and the failure reason is more nuanced.
**Behaviour:** Guarantees the user never sees a raw stack trace — this is an error-resilience guard, always on, not a deferred feature.

### `handle_error` **[P1 active]**

**Reads from state:** `error`
**Writes to state:** `status="failed"`
**Behaviour:** Terminal node for fatal/unrecoverable failures (LLM API unreachable, dataset file missing). Mirrors the skeleton's existing `handle_error` node.

### `finalize` **[P1 active]**

**Reads from state:** everything above.
**Writes to state:** no further state changes — this node exists so every non-fatal terminal path (`compose_answer`, `cannot_answer`, `ask_clarification`) converges before `END`, matching the skeleton's existing `finalize` convention. The actual `QueryRun`/`ChatMessage` DB writes happen in `src/graph/runner.py` after `agentic_ai.invoke()` returns, exactly like the skeleton's existing `run_agent()`.

---

## Graph / Flow Topology

```
START
  │
  ▼
check_clarity ──(needs_clarification)──► ask_clarification ──► finalize ──► END
  │ (else)
  ▼
generate_code ──(LLM error)──► handle_error ──► END
  │
  ▼
execute_code ──(fatal: file missing)──► handle_error ──► END
  │
  ▼
observe_result
  │
  ▼
decide_next ──(execution_error & step_count < max_steps)──► generate_code   [loop-back; inert while max_steps=1]
  │
  ├──(execution_error & step_count >= max_steps)──► cannot_answer ──► finalize ──► END
  │
  └──(success)──► compose_answer ──► finalize ──► END
```

**Conditional edges:**

| Source node | Condition | Target |
|-------------|-----------|--------|
| `check_clarity` | `state["needs_clarification"]` is True | `ask_clarification` |
| `check_clarity` | else | `generate_code` |
| `generate_code` | `state["error"]` is not None (LLM call failed) | `handle_error` |
| `generate_code` | else | `execute_code` |
| `execute_code` | `state["error"]` is not None (fatal, e.g. file missing) | `handle_error` |
| `execute_code` | else | `observe_result` |
| `decide_next` (after `observe_result`) | `execution_error` set and `step_count < max_steps` | `generate_code` |
| `decide_next` | `execution_error` set and `step_count >= max_steps` | `cannot_answer` |
| `decide_next` | else (success) | `compose_answer` |

---

## Memory & Context

| Scope | Mechanism | What is stored |
|-------|-----------|----------------|
| **Within a run** | LangGraph state | All in-progress fields above |
| **Across runs** | SQLite (`query_runs` table) | Every question, generated code, summarized result, answer, tokens, cost, status, timestamp — the audit trail |
| **Conversation** | SQLite (`chat_messages` table), loaded into `history_context` at the start of each turn | Full message history for the conversation, capped to the most recent `AGENT_HISTORY_TURNS` (assumed default: 10) turns to bound prompt size |

**Context window management:** sliding window over the most recent N chat turns (assumed `AGENT_HISTORY_TURNS=10`); `schema_context` is always included in full since it is small (column-level, not row-level).

---

## Human-in-the-Loop Checkpoints

None. This is a single local user tool with no destructive/irreversible actions in Phase 1 or Phase 2 (exports write new files, they never overwrite the original upload) — no approval gate is warranted.

---

## Error Handling & Recovery

**Node-level:** each node that makes an external call (Gemini, subprocess) catches its own exceptions; fatal errors set `state["error"]` and route to `handle_error`. Non-fatal errors (e.g. `execute_code` failing because the generated code raised) are captured as `execution_error` and routed through the normal decision path (`cannot_answer`), not treated as a graph-level failure.

**Graph-level (`handle_error` node):**
- Reads: `state["error"]`, `state["run_id"]`
- The runner updates the `QueryRun` row: `execution_status="failed"`, `error_message=state["error"]`, `created_at` already set at creation.
- Logs the error via structlog with `run_id` context.
- Terminates the graph.

**Resume / retry strategy:** no resume — a failed run is terminal; the user re-asks the question, creating a new `QueryRun`. Phase 2 may add one automatic retry-with-backoff inside `generate_code`/`compose_answer` specifically for transient Gemini 5xx/timeout errors (a resilience upgrade, not a new capability).

**Partial failure:** if code execution fails but the LLM calls otherwise succeeded, the agent degrades to `cannot_answer` — the user still gets a clear, correctly-labelled response and the query is still fully recorded in the audit trail (not aborted).

---

## Observability

| Signal | What | Where |
|--------|------|-------|
| **Trace** | One trace per `run_id`, one span per node (`check_clarity`, `generate_code`, `execute_code`, `observe_result`, `compose_answer`/`cannot_answer`/`ask_clarification`, `handle_error`) | LangSmith (`LANGCHAIN_TRACING_V2=true`) |
| **LLM calls** | Prompt tokens, completion tokens, latency, model | Structured log (structlog) + `QueryRun.prompt_tokens`/`completion_tokens`/`estimated_cost_usd` |
| **Sandbox calls** | Code executed, exit status, latency, timeout hit y/n | Structured log |
| **Run outcome** | Status, total duration, error if any | `QueryRun` row + structured log |

Every log line includes `{trace_id: run_id, node, event, timestamp}` per `harness/patterns/engineering-practices.md`.

---

## Concurrency Model

- **Run isolation:** synchronous, one query processed per request — this is a single local user issuing a few queries a day, so no queue is needed. A simple in-memory per-`conversation_id` lock in `src/api/conversations.py` returns `409 Conflict` if a second question arrives for the same conversation while one is still running.
- **Parallel nodes within a run:** none — the loop is strictly sequential (each step needs the prior step's output).
- **Checkpointing:** none in Phase 1 (each turn runs to completion or failure within one HTTP request/response). Not required for a synchronous, single-step-limited local loop; revisit only if Phase 2's higher `max_steps` makes a single turn long enough to warrant resumability (not currently the case: even 5 steps against a ≤100MB file stays well under 30s).

---

## Graph Assembly (`src/graph/agent.py`)

```python
from langgraph.graph import StateGraph, END

from graph.state import AgentState
from graph.nodes import (
    check_clarity, generate_code, execute_code, observe_result,
    compose_answer, ask_clarification, cannot_answer, handle_error, finalize,
)
from graph.edges import after_clarity, after_generate_code, after_execute_code, after_observe_result


def _build_graph() -> StateGraph:
    g = StateGraph(AgentState)
    g.add_node("check_clarity", check_clarity)
    g.add_node("generate_code", generate_code)
    g.add_node("execute_code", execute_code)
    g.add_node("observe_result", observe_result)
    g.add_node("compose_answer", compose_answer)
    g.add_node("ask_clarification", ask_clarification)
    g.add_node("cannot_answer", cannot_answer)
    g.add_node("handle_error", handle_error)
    g.add_node("finalize", finalize)

    g.set_entry_point("check_clarity")

    g.add_conditional_edges(
        "check_clarity", after_clarity,
        {"ask_clarification": "ask_clarification", "generate_code": "generate_code"},
    )
    g.add_conditional_edges(
        "generate_code", after_generate_code,
        {"handle_error": "handle_error", "execute_code": "execute_code"},
    )
    g.add_conditional_edges(
        "execute_code", after_execute_code,
        {"handle_error": "handle_error", "observe_result": "observe_result"},
    )
    g.add_conditional_edges(
        "observe_result", after_observe_result,
        {
            "generate_code": "generate_code",     # loop-back — inert while max_steps=1
            "cannot_answer": "cannot_answer",
            "compose_answer": "compose_answer",
        },
    )

    g.add_edge("ask_clarification", "finalize")
    g.add_edge("compose_answer", "finalize")
    g.add_edge("cannot_answer", "finalize")
    g.add_edge("finalize", END)
    g.add_edge("handle_error", END)

    return g.compile()


agentic_ai = _build_graph()
```
