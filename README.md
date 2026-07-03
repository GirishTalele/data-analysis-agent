> **All commands below run from the repo root** (this directory), unless a step explicitly says `cd frontend`. Every Python command is prefixed with `uv run`.

# Data Analysis Agent

A local-first agent for asking natural-language questions about your CSV/Excel files. Upload a file, get an instant auto-profile, then chat with the agent — it writes and runs real pandas code (via Gemini) to answer your questions. Your raw data never leaves your machine; only schema, statistics, generated code, and aggregated results are ever sent to the LLM.

## Setup

Copy the example env file and set your Gemini API key:

```bash
cp .env.example .env
```

Edit `.env` and set `AGENT_GEMINI_API_KEY=<your key>` — this is the only required key for this project.

Optional cost-display setting:

- `AGENT_USD_TO_INR` — fixed USD→INR rate used to show every cost in both currencies (e.g. `$0.0016 (₹0.14)`). Default `88.0`. USD stays the canonical, stored value; INR is display-derived in API responses (`cost_inr = cost_usd * AGENT_USD_TO_INR`) — no external FX API, no DB migration.

## Install

```bash
uv sync --extra dev
cd frontend && pnpm install && cd ..
```

## Database

Run migrations from the repo root:

```bash
uv run alembic upgrade head
uv run alembic current
```

`uv run alembic current` must print a non-blank revision hash (e.g. `33897bde32dc (head)`). Blank output means the migration silently failed.

## Build the frontend

```bash
cd frontend && pnpm build && cd ..
```

## Run

```bash
uv run python -m src
```

This starts the server on `http://localhost:8001`.

## Use it

1. Open `http://localhost:8001/app/`.
2. Upload a CSV or Excel file — a profile card appears immediately showing columns, dtypes, row count, and missing-value counts.
3. Type a natural-language question about the data (e.g. "what's the average of column X") and submit.
4. Within ~30 seconds, a plain-language answer appears. Click "View code" to see the exact pandas code that ran, and check the token/cost badge for that query.
5. Reload the page — the question and answer persist (loaded from SQLite).

## Testing

Backend (requires `AGENT_GEMINI_API_KEY` set in `.env` — integration and e2e tests hit the real Gemini API):

```bash
uv run pytest tests/unit tests/integration tests/e2e -q
```

Frontend end-to-end (requires the backend server running via `uv run python -m src`):

```bash
cd frontend && npx playwright test tests/e2e/ --reporter=line
```

## What's real vs. stub in Phase 1

Per `spec/roadmap.md`'s Phase 1 scope:

- **Real:** single-file CSV/Excel upload, auto-profiling, one natural-language question per turn answered with real pandas execution via the real Gemini API, visible generated code, per-query token/cost estimate, and chat history persisted across restarts in SQLite.
- **Labelled non-functional stubs (visibly marked "coming soon", Phase 2):** a chart placeholder area below answers, a disabled "Export cleaned data" button, a disabled "+ Add another file" control, and a disabled "View audit trail" link. Multi-file datasets and iterative multi-step refinement are also Phase 2.

## Full spec

See `spec/` for the complete specification — `spec/roadmap.md` (phases), `spec/architecture.md` (stack), `spec/data.md` (data model), `spec/api.md` (API contract), `spec/ui.md` (UI/UX), and `spec/agent.md` (agent graph).
