# Architecture

---

## System Overview

A single-user, local-first FastAPI service backed by SQLite, with a LangGraph reasoning loop that answers natural-language questions about a locally-stored CSV/Excel file. The user interacts through a Next.js chat UI served by the same FastAPI process. When the user asks a question, the agent calls Gemini to generate pandas code, executes that code in a locked-down subprocess against the real local file, summarizes the (potentially large) result down to an aggregate the LLM is allowed to see, and calls Gemini again to compose a plain-language answer. Every step, the code, the result, and the token/cost accounting are persisted to SQLite for the audit trail.

## Component Map

```
Browser (Next.js static export, served at /app)
    │  fetch() → JSON
    ▼
FastAPI app (src/api)
    │
    ├── datasets router  ──►  ingestion + profiling (src/tools/storage.py, src/tools/profiling.py)
    │                              │
    │                              ▼
    │                    Local filesystem: ./data/datasets/<id>/...
    │
    └── conversations router ──► graph/runner.py ──► LangGraph analysis loop (src/graph)
                                        │                    │
                                        │                    ├─► LLMClient → GeminiProvider ──► Gemini API
                                        │                    └─► sandbox/executor.py ──► subprocess (pandas)
                                        ▼
                                  SQLite (src/db) — datasets, files, profiles,
                                  conversations, chat_messages, query_runs (audit trail)
```

## Layers

| Layer | Responsibility |
|-------|----------------|
| API (`src/api/`) | HTTP surface: file upload, profile retrieval, ask/answer, chat history. Validates input, returns `ok()`/`api_error()` envelopes. |
| Domain (`src/domain/`) | Pydantic request/response models per entity (`Dataset`, `Conversation`, `QueryRun`, etc.) |
| Graph (`src/graph/`) | The ReAct-style reasoning loop: generate code → execute → observe → decide → answer. See `spec/agent.md`. |
| Tools (`src/tools/`) | Pure functions: file storage layout, profiling, (Phase 2) joins and export. |
| Sandbox (`src/sandbox/`) | Executes LLM-generated pandas code against the real local file in an isolated subprocess; enforces the raw-row privacy boundary. |
| LLM (`src/llm/`) | Provider-agnostic `LLMClient`; `GeminiProvider` is the active provider for this project. |
| DB (`src/db/`) | SQLAlchemy models + session management against SQLite. |
| Observability (`src/observability/`) | Structured (structlog) request/response/node logging; LangSmith tracing via env vars. |

## Data Flow

1. Trigger: user uploads a file via the browser (`POST /datasets`).
2. The file is saved to `./data/datasets/<dataset_id>/original/<filename>` (never re-uploaded to any external service).
3. `src/tools/profiling.py` loads the file with pandas, computes column names/dtypes/missing counts/row count, and persists a `DatasetProfile` row. The profile (not the raw rows) is returned to the browser immediately.
4. The user asks a question (`POST /conversations/{id}/messages`). The API creates a `QueryRun` row (status `pending`) and invokes `graph/runner.py::run_agent()`.
5. The graph builds a `schema_context` (columns, dtypes, stats) from the stored `DatasetProfile` — **the raw file is never read into the LLM prompt**.
6. `generate_code` calls Gemini with `schema_context` + the question (+ prior chat turns) and gets back pandas code as text.
7. `execute_code` (`src/sandbox/executor.py`) runs that code in a subprocess with the real DataFrame loaded from the stored file, and returns either a result or an error — this is the **only** step that ever touches raw rows, and it never leaves the local machine.
8. `sandbox/executor.py::summarize_for_llm()` truncates/aggregates the result (see "Raw-Row Privacy Boundary" below) before it is allowed back into any subsequent LLM prompt.
9. `compose_answer` calls Gemini with the *summarized* result to produce the plain-language answer with key numbers.
10. `runner.py` persists the `QueryRun` (code, summarized result, answer, tokens, cost, status, timestamps) and appends a `ChatMessage`.
11. Output: JSON response to the browser containing the answer, the code, and the token/cost estimate; the browser renders it and shows the collapsible code view.

## External Dependencies

| Dependency | Purpose | Failure Mode |
|------------|---------|--------------|
| Gemini API (`google-genai`) | Code generation + answer composition | Node catches the SDK exception, sets `state["error"]`, routes to `handle_error`; the API returns a clear, actionable error (never a raw stack trace) and the query is recorded as `status=failed` in the audit trail. |
| Local filesystem (`./data/`) | Uploaded files, derived/exported files | Missing/unreadable file → `ingestion-profiling` returns 400 with a human message; a file that disappears between upload and query → `execute_code` reports `execution_error`, routed to `cannot_answer`. |
| SQLite (`./data/agent.db`) | All persistence: datasets, profiles, conversations, chat history, audit trail | Connection error fails the request loudly (500) — never a silent no-op; SQLAlchemy session rollback on any exception. |
| Python subprocess (sandbox) | Runs LLM-generated pandas code | Timeout (20s) or exception inside the subprocess is captured as `execution_error`, never crashes the API process. |

## Raw-Row Privacy Boundary (hard architectural rule)

**The LLM (Gemini) never receives raw row-level data.** It only ever receives:
- Schema: column names, dtypes, row/column counts (`DatasetProfile.columns_json`).
- Column statistics: missing counts, min/max/mean for numeric columns, cardinality for categorical columns (also part of `DatasetProfile.columns_json`).
- Generated code (round-tripped for iterative refinement).
- Aggregated/truncated execution results, produced only by `src/sandbox/executor.py::summarize_for_llm()`.

**Enforcement point:** `src/sandbox/executor.py::summarize_for_llm(result)` is the single function through which every execution result must pass before it can appear in any prompt built by `src/graph/nodes.py::compose_answer` (or `generate_code` on a retry). Rules it enforces:
- Scalars (`int`, `float`, `str`, `bool`, `None`) pass through unchanged.
- `dict`/`list` results are size-capped at `AGENT_MAX_SUMMARY_ITEMS` (assumed default: 50 items); beyond that, truncated with an explicit `"truncated": true, "total_items": N` marker.
- `pandas.DataFrame`/`Series` results are **never** passed through as full row data. If the row count is ≤ `AGENT_MAX_SUMMARY_ROWS` (assumed default: 20) it is converted to a dict via `.to_dict(orient="records")`; above that threshold, only `.describe()` (or `.value_counts().head(N)` for categoricals) is returned, plus the true row count, and a `"truncated": true` marker.
- When a returned frame's row count equals the full dataset's row count and no aggregation function was detected in the executed code (the "just return the raw frame" case, common for legitimate cleaning questions), `summarize_for_llm` does **not** raise — it aggregates/head-sample-caps the frame at `AGENT_MAX_SUMMARY_ROWS` and marks it `"truncated": true`. (The earlier hard rejection was removed because it forced a costly retry loop on valid cleaning queries.) The privacy boundary still holds unconditionally: no more than `AGENT_MAX_SUMMARY_ROWS` rows ever surface to the LLM.

> **Assumed:** `AGENT_MAX_SUMMARY_ITEMS=50` and `AGENT_MAX_SUMMARY_ROWS=20` — reasonable defaults for keeping a summary genuinely aggregated while remaining useful for narration; both configurable via `.env`.

This boundary is directly testable: a unit test asserts `summarize_for_llm()` never returns more than the configured caps, and an integration test inspects the literal prompt string sent to `LLMClient.call_model()` in `compose_answer` and asserts it does not contain more than `AGENT_MAX_SUMMARY_ROWS` distinct row-like records.

## Sandboxed Code Execution

- `src/sandbox/executor.py::run_code(code: str, dataset_path: Path, file_type: str) -> ExecutionResult` spawns a fresh Python subprocess (`subprocess.run`, `timeout=AGENT_SANDBOX_TIMEOUT_SECONDS`, assumed default 20s) running a small runner script.
- The runner script loads the dataset once (`pandas.read_csv`/`pandas.read_excel`) into `df`, then `exec()`s the generated code in a restricted namespace exposing only `pd`, `df`, and a `result` variable the code must assign.
- Before `exec()`, the code is parsed with `ast.parse()` and rejected (execution error surfaced back through the graph, never crashes the API) if it references `os`, `sys`, `subprocess`, `socket`, `open`, `__import__`, or any dunder attribute access — a guardrail against LLM mistakes, not a hardened multi-tenant sandbox (this is a trusted single local user; see `spec/roadmap.md` → Out of Scope).
- stdout/stderr from the subprocess are captured for the "view code" disclosure (shown to the user, never sent back to the LLM as raw output — only `summarize_for_llm(result)` is).
- On subprocess timeout or non-zero exit, `run_code` returns `ExecutionResult(error=...)`, which routes the graph to `cannot_answer` (or a retry, once Phase 2 raises `max_steps`).

## Local File Storage Layout

```
data/
  agent.db                              # SQLite database
  datasets/
    <dataset_id>/
      original/
        <original_filename>             # exactly as uploaded, one file in Phase 1; folder-as-dataset (Phase 2) allows many
      derived/
        <derived_dataset_id>.csv        # Phase 2 — exported/cleaned outputs
```

`data/` is created on first run if absent and is gitignored in its entirety.

## Stack

> This project's concrete technology choices. Generic rules (model-naming, DB driver, dev port, real-key test rule) live in `harness/patterns/tech-stack.md`.

- **Language:** Python 3.12+ (backend/agent), TypeScript (frontend) — matches the existing skeleton.
- **Agent framework:** LangGraph — a ReAct-style loop (see `spec/agent.md`); the skeleton's `StateGraph` wiring is extended in place, not replaced.
- **LLM provider + model:** Google Gemini via `google-genai`, model `gemini-3.1-pro-preview` (the live-verified model id; already wired as `GeminiProvider.DEFAULT_MODEL` in `src/llm/providers/gemini.py`; the default provider is auto-selected from `AGENT_GEMINI_API_KEY` being set, per `src/llm/client.py`'s existing `_make_provider()`). Configurable via `AGENT_LLM_MODEL`.
- **Backend:** FastAPI (existing skeleton), served at port 8001.
- **Database + ORM:** SQLite (`data/agent.db`) + SQLAlchemy 2.0 declarative models + Alembic migrations. SQLite is the correct choice here (not an assumption to override) because this is an explicitly local, single-user tool per `spec/roadmap.md`.
- **Frontend:** Next.js 15 + React 19, static export served by FastAPI at `/app` (existing skeleton pattern) — Tailwind for styling.
- **Dependency management:** uv (Python, `pyproject.toml`), pnpm (frontend).
- **Data processing:** pandas (already implied by the sandbox design) — added to `[project.dependencies]` (never dev-only, since the sandbox runner script needs it at runtime) along with `openpyxl` for `.xlsx` support and (Phase 3) `pyqvd` for `.qvd` support.
- **QVD (QlikView Data) support (Phase 3):** `pyqvd` — a pure-Python reader that parses the proprietary QVD binary columnar format directly into a `pandas.DataFrame`, with no Qlik runtime and no external service (satisfies the local-first / raw-row privacy constraints). Declared as a **normal (non-dev) `[project.dependencies]` entry**, not a dev-only extra, because `src/sandbox/runner.py` runs in an isolated subprocess (`sys.executable src/sandbox/runner.py …`) and must be able to `import pyqvd` there to load a QVD-backed dataset at query time — the same reason `pandas`/`openpyxl` are runtime deps. Chosen over alternatives because it is pip-installable, pure-Python (no native/Qlik dependency), and yields a DataFrame that flows unchanged through the existing profiling/sandbox/join/export code paths. If `pyqvd` proves unworkable at build time, substitute another pure-Python QVD→DataFrame reader under the same constraints (no external service, no Qlik runtime).
- **Observability:** structlog (existing `src/observability/events.py`) extended so every graph node logs `{trace_id=run_id, node, latency_ms, tokens, error}`; LangSmith tracing enabled via `LANGCHAIN_TRACING_V2=true` + `LANGCHAIN_API_KEY` (+ `LANGCHAIN_PROJECT`) env vars — LangGraph auto-traces through `langchain-core` callbacks when these are set, no code change required beyond declaring the settings and documenting them in `.env.example`.

| Key library | Version | Purpose |
|-------------|---------|---------|
| `pandas` | >=2.2 | Profiling + sandboxed code execution |
| `openpyxl` | >=3.1 | `.xlsx` read support for pandas |
| `pyqvd` | >=1.0 | `.qvd` (QlikView) → `pandas.DataFrame` read support (Phase 3); pure-Python, must import in the sandbox subprocess |
| `google-genai` | >=2.9.0 (existing) | Gemini SDK |
| `langgraph` | >=0.1 (existing) | Reasoning-loop graph |
| `python-multipart` | >=0.0.9 | FastAPI file upload parsing |

**Avoid:** a hardcoded op-list ("if question contains 'average' → run `.mean()`") — always generate executable code (per `harness/patterns/agentic-ai.md` #22); a global in-memory result cache that could leak one conversation's data into another; sending the pandas `.to_string()`/`.to_json()` of a full DataFrame to the LLM under any circumstance.

## New Settings (added to `src/config/settings.py`)

| Setting | Env var | Default | Purpose |
|---------|---------|---------|---------|
| `data_dir` | `AGENT_DATA_DIR` | `./data` | Root for `datasets/` storage |
| `max_upload_mb` | `AGENT_MAX_UPLOAD_MB` | `100` | Reject uploads above this size |
| `sandbox_timeout_seconds` | `AGENT_SANDBOX_TIMEOUT_SECONDS` | `20` | Subprocess wall-clock limit |
| `max_summary_rows` | `AGENT_MAX_SUMMARY_ROWS` | `20` | Raw-row privacy boundary cap (rows) |
| `max_summary_items` | `AGENT_MAX_SUMMARY_ITEMS` | `50` | Raw-row privacy boundary cap (list/dict items) |
| `max_steps` | `AGENT_MAX_STEPS` | `1` (Phase 1) / `5` (Phase 2) | Iterative-refinement step limit |
| `gemini_input_price_per_1m` | `AGENT_GEMINI_INPUT_PRICE_PER_1M` | `1.25` (assumed, USD) | Cost estimation |
| `gemini_output_price_per_1m` | `AGENT_GEMINI_OUTPUT_PRICE_PER_1M` | `5.00` (assumed, USD) | Cost estimation |
| `langchain_tracing_v2` | `LANGCHAIN_TRACING_V2` | `false` | LangSmith tracing toggle |
| `langchain_api_key` | `LANGCHAIN_API_KEY` | `""` | LangSmith key (optional) |

> **Assumed:** Gemini per-token prices above are placeholders pending verification against current Gemini pricing docs — they only affect the *displayed estimate*, not correctness of the analysis; they are configurable via `.env` so the user can correct them.

## Deployment Model

Long-running local process: `uv run python -m src` starts uvicorn on port 8001, serving both the API and the built Next.js static export at `/app`. No containerization or cloud deployment in scope — this is a tool the user runs on their own machine.
