# Architecture

---

## System Overview

The GR (Goods Receipt) Report Agent is a local, single-user tool for a packaging manufacturer. A user opens a single web page, uploads one QVD (Qlik/SAP BI export) or CSV (ERP flat-file export) containing GR transaction line items, enters one or more recipient email addresses, and clicks **Send Report**. The backend loads the file, aggregates GR value by Plant and by Buyer, renders two bar charts and one HTML table, composes an HTML email with the charts embedded as inline images (`cid:`), and sends it immediately through the company's on-prem SMTP server. There is no LLM anywhere in this system and no persistence layer — every run is a single, stateless HTTP request that either fully succeeds (report sent, possibly with flagged gaps) or fully fails (nothing sent, error shown in the browser).

## Component Map

```
Browser (Next.js static page, single screen)
   │  multipart/form-data: file + recipients
   ▼
FastAPI app (:8001)  ──serves──▶  /app/  (built Next.js static export)
   │
   ▼
POST /reports/send
   │
   ▼
Ingestion (ingestion/loader.py, ingestion/columns.py)
   │  DataFrame + ColumnMapping
   ▼
Reporting (reporting/aggregate.py, reporting/charts.py)
   │  plant/buyer totals (₹ Cr), period label, chart PNG bytes
   ▼
Email composition (reporting/email_body.py)
   │  MIME multipart/related message
   ▼
Mailer (reporting/mailer.py)  ──SMTP (Logix, on-prem)──▶  Recipients' inboxes
   │
   ▼
JSON result  ──▶  Browser renders success/error panel
```

## Layers

| Layer | Responsibility |
|-------|----------------|
| API (`src/api/`) | HTTP surface: accepts the upload, calls the pipeline, maps outcomes to HTTP status + JSON envelope |
| Ingestion (`src/ingestion/`) | Parses QVD/CSV bytes into a DataFrame; detects Plant/Buyer/GR Value/period columns by alias matching |
| Reporting (`src/reporting/`) | Aggregation, ₹-Crore conversion, period derivation, chart rendering, HTML email composition, SMTP send |
| Domain (`src/domain/`) | Typed Pydantic models that cross module boundaries (`ColumnMapping`, `ReportBundle`, `SendResult`, …) |
| Frontend (`frontend/`) | The single upload/send page and its states (empty, loading, success, error) |

## Data Flow

1. **Trigger:** the user, looking at the web page, chooses a file, types/pastes recipient addresses, and clicks **Send Report**.
2. The browser POSTs `multipart/form-data` to `POST /reports/send`.
3. Ingestion loads the file into a DataFrame and detects the Plant, Buyer, GR Value, and period columns (see `spec/data.md` for the exact matching rule).
4. If GR Value is undetectable/unusable, or neither Plant nor Buyer is detectable, the pipeline stops here — **fatal**, nothing downstream runs (see `## Error Handling & Reliability Model` below).
5. Reporting aggregates GR Value by Plant and by Buyer (top 10), converts to ₹ Crores, derives the reporting period, and renders the plant chart, plant table, and buyer chart — skipping only the specific section(s) whose input column is missing.
6. Email composition builds one HTML email (charts as inline `cid:` images, table as real HTML) stating the source filename, the reporting period, and any skipped-section warnings.
7. The mailer sends the email via the configured SMTP server to every syntactically-valid recipient. If the send itself fails, nothing was delivered — fatal.
8. **Output:** a real email in the recipients' inboxes, and a JSON result returned to the browser that renders as a success panel (with any warnings) or an error panel.

## External Dependencies

| Dependency | Purpose | Failure Mode |
|------------|---------|--------------|
| Company SMTP server (Logix, on-prem, via `.env` `AGENT_SMTP_*`) | Delivers the report email | Connection/auth/timeout failure → fatal (`SMTP_SEND_FAILED`, HTTP 502); no retry; nothing was sent; error shown in the UI |
| `pyqvd` (QVD reader) | Parses `.qvd` files into a pandas-compatible table | Corrupt/unreadable QVD → fatal (`FILE_UNREADABLE`, HTTP 422) |

No other external services. No LLM provider, no database.

---

## Deliberate Deviations From the Boilerplate Default

This project intentionally departs from the boilerplate's default stack (FastAPI + LangGraph + SQLite/Alembic + Anthropic). Each deviation is confirmed by the build brief, not a guess:

1. **No LLM, no agent framework, no `spec/agent.md`.** The pipeline is a fixed, deterministic sequence of pure-code transformations (load → detect columns → aggregate → render → compose → send) with no branching driven by a model and no tool-calling loop. Per `harness/patterns/agentic-ai.md`, a graph/loop is justified when there is branching or tool-use driven by an LLM; here there is neither — it is a **prompt-chain-shaped pipeline with zero prompts**. Forcing a LangGraph `StateGraph` around five deterministic function calls would add ceremony with no behavioural benefit, so **`spec/agent.md` does not apply and has been overwritten with an explicit not-applicable notice** (the spec-writer has no file-delete capability in this session; `agent-builder`/a human should physically remove `spec/agent.md` when convenient — its content is unambiguous that it is N/A). The equivalent of "the graph" is the plain function pipeline documented in `## Data Flow` above and implemented in `src/reporting/pipeline.py`.
2. **No database, no Alembic, no persistence layer at all.** Confirmed twice by the user: no run history, no audit log, nothing survives past the HTTP response. This removes `src/db/`, `alembic/`, `alembic.ini`, and the `alembic upgrade head` step from every phase gate in `harness/patterns/phases.md` — those DB-specific gate items (driver in `[project.dependencies]`, `alembic upgrade head`, `alembic current`) **do not apply to this project** and are replaced by the gate defined in `spec/roadmap.md`.
3. **Zero LLM usage.** No `AGENT_ANTHROPIC_API_KEY`/`AGENT_GEMINI_API_KEY`, no `llm/` package, no prompts. Confirmed twice by the user. Correctness is proven by independent pandas recomputation (see `spec/roadmap.md` gate), not by model evaluation.

---

## Stack

- **Language:** Python 3.12+ (backend), TypeScript (frontend) — unchanged from the boilerplate default.
- **Agent framework:** **None.** See deviation #1 above.
- **LLM provider + model:** **None.** Zero LLM usage anywhere in this system (confirmed twice).
- **Backend:** FastAPI, served single-origin on **`:8001`** exactly as the boilerplate skeleton already does (`src/api/__init__.py` mounts the built Next.js export at `/app`). Routes are defined as plain `def` (not `async def`) so FastAPI offloads the blocking pandas/matplotlib/smtplib work to its threadpool instead of stalling the event loop.
- **Database + ORM:** **None.** See deviation #2 above. All state is in-memory for the lifetime of one `POST /reports/send` request.
- **Frontend:** Next.js 15 + React 19, static export (`output: 'export'`, `basePath: '/app'`) served by FastAPI — unchanged from the boilerplate convention. Tailwind v4 via the existing `postcss.config.mjs` / `@source "../"` setup — do not touch the first two lines of `globals.css`.
- **Dependency management:** `uv` (Python, `pyproject.toml`), `pnpm` (frontend).

| Key library | Version | Purpose |
|-------------|---------|---------|
| `fastapi` | `>=0.115` | HTTP API, single-origin serving |
| `uvicorn[standard]` | `>=0.30` | ASGI server |
| `pydantic` (extra: `email`) | `>=2.7` | Typed domain models + `EmailStr` recipient validation |
| `pydantic-settings` | `>=2.3` | `.env`-backed settings |
| `structlog` | `>=24.1` | Structured logging (kept from the skeleton) |
| `pandas` | `>=2.2` | DataFrame load, group-by aggregation |
| `pyqvd` | `>=2.3.2` | Read `.qvd` files into a pandas-compatible table |
| `matplotlib` | `>=3.9` | Renders the two bar charts to PNG bytes (Agg backend, headless) |
| `jinja2` | `>=3.1` | Renders the HTML email body template |
| `python-multipart` | `>=0.0.9` | Required by FastAPI to parse the `multipart/form-data` upload |
| `pytest`, `httpx` | `>=8.2`, `>=0.27` | Test runner + `TestClient` (dev-only) |

**Removed from the skeleton's default dependency set** (and must be removed from `pyproject.toml`): `sqlalchemy`, `alembic`, `anthropic`, `langgraph`, `google-genai`. Also remove `alembic/` and `alembic.ini` from the repo, and `src/db/`, `src/graph/`, `src/llm/`, `src/prompts/`, `src/domain/run.py`, `src/api/runs.py` (superseded by the modules listed in `## Module Layout` below).

**Avoid:**
- Any LLM/agent SDK call anywhere in `src/` — this agent is pure code end-to-end.
- Writing the uploaded file or any intermediate DataFrame to disk except a short-lived temp file strictly needed to hand a filesystem path to `pyqvd` (deleted in a `finally` block before the request returns) — see `## pyqvd Integration` below.
- A background job queue / async task runner — a single synchronous request/response is correct for a single local user and keeps the "no rough edges" bar achievable in Phase 1.

## Deployment Model

A single local process on the user's machine: `uv run python -m src` after `cd frontend && pnpm build`. No containerization, no cloud deployment, no multi-user concerns — this is an internal, single-operator tool that runs on demand.

> **Assumed:** no authentication layer — the tool is local-only (bound to `localhost:8001`), single-user, and the brief specifies no login/approval step. If this is ever exposed beyond localhost, authentication must be added first; out of scope for both phases below.

---

## Module Layout (`src/`)

```
src/
  __init__.py                    # __version__ = "0.1.0" (unchanged)
  __main__.py                    # uvicorn.run("api:app", port=8001) (unchanged)
  api/
    __init__.py                  # app factory — drop the DB-init lifespan, keep the /app static mount
    _common.py                   # ok()/api_error() (unchanged)
    health.py                    # unchanged
    reports.py                   # NEW: POST /reports/send
  config/
    settings.py                  # REWRITTEN: SMTP + upload-limit + (Phase 2) scope-path settings; no DB/LLM fields
  domain/
    __init__.py
    report.py                    # NEW: ColumnMapping, ReportBundle, SendResult, (Phase 2) RecipientScope
  ingestion/
    __init__.py
    loader.py                    # NEW: load_file(bytes, filename) -> pandas.DataFrame
    columns.py                   # NEW: detect_columns(df) -> ColumnMapping  (alias rules: spec/data.md)
  reporting/
    __init__.py
    aggregate.py                 # NEW: aggregate(df, mapping) -> plant/buyer totals + period + warnings
    charts.py                    # NEW: render_plant_chart(), render_buyer_chart() -> PNG bytes
    email_body.py                # NEW: render_html(...) via Jinja2 -> str
    mailer.py                    # NEW: send_email(...) via smtplib -> None | raises
    pipeline.py                  # NEW: send_report(file_bytes, filename, recipients) -> SendResult
    scoping.py                   # Phase 2: load_scopes(), group_recipients_by_scope()
    templates/
      report_email.html.j2       # NEW: the HTML email template
  observability/
    events.py                    # unchanged: structlog configuration
```

Removed entirely: `src/db/`, `src/graph/`, `src/llm/`, `src/prompts/`, `src/domain/run.py`, `src/api/runs.py`, `alembic/`, `alembic.ini`.

---

## Column Detection & Period Derivation

The exact alias tables, normalization rule, and period-formatting logic are the single source of truth in **`spec/data.md` → `## Input File Schema`**. This file only records *where* that logic runs: `src/ingestion/columns.py` for column detection, `src/reporting/aggregate.py` for period derivation and the aggregation formulas.

## ₹-Crores Conversion

`value_in_crores = raw_value / 1e7` (1 Crore = 10,000,000). Full formula and rounding/display rule in `spec/data.md`. Applied in `src/reporting/aggregate.py`; never applied twice (the raw DataFrame values stay in rupees until the final display/formatting step, so intermediate warnings like "N rows excluded" always refer to raw-currency row counts, not converted amounts).

## pyqvd Integration

> **Assumed — verify before implementation.** `pyqvd` is a real but less-common PyPI package. Based on its published description and this repository's own prior use of it (see git history: `pyqvd>=2.3.2` was already pinned and working in a related build in this repo), the expected API surface is:
> ```python
> from pyqvd import QvdTable
> df = QvdTable.from_qvd(path_to_file).to_pandas()
> ```
> **Do not trust this blindly.** Before wiring `src/ingestion/loader.py`, the code-generator must confirm the actual class/method names by running `uv run python -c "import pyqvd; help(pyqvd)"` (or `pip show -f pyqvd` and reading the installed source) against the installed package, and adjust the call to match. If `from_qvd` does not accept a bare path, `loader.py` must still present the file as a filesystem path to whatever `pyqvd`'s real entry point requires (see the temp-file pattern below) — the *behavior* (bytes in → DataFrame out) is the contract; the exact call is verified, not guessed, at implementation time.

Because the upload arrives as in-memory bytes but `pyqvd` most likely needs a filesystem path, `loader.py` writes the uploaded `.qvd` bytes to a `tempfile.NamedTemporaryFile(suffix=".qvd", delete=False)`, calls the verified `pyqvd` read entry point on that path, and deletes the temp file in a `finally` block before returning — regardless of success or failure. `.csv` files never touch disk (`pandas.read_csv` reads directly from the in-memory upload stream).

## Chart Rendering

`matplotlib.use("Agg")` **must** be set at the top of `src/reporting/charts.py`, before `import matplotlib.pyplot as plt` — omitting this on a headless server either crashes (no display) or silently tries to open a GUI backend. Both charts are rendered to an in-memory `io.BytesIO()` via `fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")` and returned as raw PNG bytes — never written to disk.

- **Plant chart:** vertical bar chart, one bar per Plant, sorted descending by ₹-Crore value; title `"Plant-wise GR Value (₹ Crore) — {period}"`; y-axis `"₹ Crore"`; value label above each bar to 2 decimals.
- **Buyer chart:** horizontal bar chart, exactly the top 10 buyers by ₹-Crore value, sorted descending top-to-bottom (buyer names are long — horizontal avoids label collision); title `"Top 10 Buyers by GR Value (₹ Crore) — {period}"`.
- **Plant table:** rendered as literal HTML (`<table>` via the Jinja2 template), **not** an image — figures must be selectable/copyable in the email client. Same sort order as the plant chart, plus a `Total` footer row.

## Email MIME Structure

```
multipart/related                          (root — allows cid: references)
├── multipart/alternative
│   ├── text/plain                         (auto-generated plain-text summary — filename, period, warnings, "view in an HTML-capable client for charts")
│   └── text/html                          (real body: warning banner if any, filename + period line, <img src="cid:plant_chart">, <table>…</table>, <img src="cid:buyer_chart"> — omitted entirely if the buyer chart could not be generated)
├── image/png  Content-ID: <plant_chart>   Content-Disposition: inline   (omitted if Plant column undetectable)
└── image/png  Content-ID: <buyer_chart>   Content-Disposition: inline  (omitted if Buyer column undetectable)
```

Built with Python's stdlib `email.message.EmailMessage` (`.set_content()` for the plain part, `.add_alternative(html, subtype="html")`, then `.add_related(png_bytes, maintype="image", subtype="png", cid="plant_chart")` per image) and sent via `smtplib.SMTP(host, port)` → `.starttls()` (when `AGENT_SMTP_USE_TLS=true`) → `.login(username, password)` → `.send_message(msg)`. Subject line: `"GR Report — {period} — {source_filename}"`.

## Error Handling & Reliability Model

There are exactly two outcome classes. This table is the single authoritative source for that behavior; capability files cross-reference it rather than restate it.

**FATAL — outright failure.** No email is composed or sent under any circumstance. `POST /reports/send` returns a 4xx/5xx JSON error (`{"detail": {"code": ..., "message": ...}}`); the UI renders the Error state. No automatic retries.

| # | Condition | HTTP | Code |
|---|-----------|------|------|
| F1 | File extension is not `.csv`/`.qvd` (case-insensitive) | 422 | `UNSUPPORTED_FILE_TYPE` |
| F2 | File bytes cannot be parsed at all (corrupt, empty, zero data rows) | 422 | `FILE_UNREADABLE` |
| F3 | GR Value column cannot be detected anywhere in the header row | 422 | `GR_VALUE_COLUMN_MISSING` |
| F4 | GR Value column is detected but every row fails numeric coercion | 422 | `GR_VALUE_UNPARSABLE` |
| F5 | Neither Plant nor Buyer column can be detected | 422 | `NO_GROUPING_COLUMN` |
| F6 | Recipients field is empty, or every entered address fails `EmailStr` validation | 400 | `NO_VALID_RECIPIENTS` |
| F7 | SMTP connection/auth/timeout failure while sending | 502 | `SMTP_SEND_FAILED` |
| F8 | Any other unhandled exception in the pipeline | 500 | `INTERNAL_ERROR` |

F1–F6 are all checked **before** any SMTP contact is attempted. F7 can only occur after a report was fully composed — if SMTP fails, the report is discarded; there is no partial send.

**PARTIAL — degraded but real.** The email **is** sent to every valid recipient; the gap is flagged both inside the email body (a warning banner above the charts) and in the API/UI `warnings[]` list.

| # | Condition | What is skipped | Warning text pattern |
|---|-----------|-----------------|----------------------|
| P1 | Plant column undetectable (Buyer + GR Value present) | Plant chart + plant table | `"Plant-wise chart and table could not be generated: no recognizable Plant column found in the source file."` |
| P2 | Buyer column undetectable (Plant + GR Value present) | Top-10 Buyer chart | `"Top-10 Buyer chart could not be generated: no recognizable Buyer column found in the source file."` |
| P3 | Period/date column undetectable or fully unparsable | The reporting-period line falls back to a placeholder | `"Reporting period could not be determined: no recognizable date column found in the source file."` |
| P4 | GR Value column detected but some (not all) rows fail numeric coercion | Those rows excluded from every total | `"{n} of {total} rows had a non-numeric GR Value and were excluded from the totals below."` |
| P5 | Some (not all) entered recipient addresses fail `EmailStr` validation | Those addresses never receive the email | Not in the email body (they never see it) — surfaced only via the API's `recipients_rejected` list, shown in the UI success panel. |

## Observability

No LLM, so no LangSmith tracing. Structured logging via `structlog` (already wired in the skeleton) is the Phase-1 observability requirement and is never deferred:

- Every `POST /reports/send` call logs one structured event on completion: `report.send` with fields `filename`, `file_type`, `row_count`, `recipient_count` (never the addresses themselves — see `spec/data.md → Sensitive Data`), `period`, `warnings` (list of codes, e.g. `["P2", "P4"]`), `status` (`sent` | `fatal:<code>`), and `duration_ms`.
- SMTP send attempts and failures are logged with the SMTP error class/message (never the password) at `error` level.
- Logs go to stdout in JSON (structlog's default JSON renderer) — no file, no external sink, consistent with the "single local user" scope.

## Testing Conventions

- Unit tests live in `tests/unit/` (column detection, aggregation math, chart-byte validity, MIME structure) — fully deterministic, no network.
- Phase-gate tests live in `tests/phase1/` (and `tests/phase2/`) per `spec/roadmap.md`, and include the one real-SMTP integration test and the independent-recomputation correctness test — both call real external systems (`.env` SMTP creds), never stubbed.
- Frontend E2E lives in `frontend/tests/e2e/` (Playwright), run against the live single-origin server at `http://localhost:8001/app/`.
- No database fixtures anywhere — there is no database.
