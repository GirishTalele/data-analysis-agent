# Roadmap

---

## What This Agent Does

The GR (Goods Receipt) Report Agent is a local, single-user tool that turns a raw QVD or CSV GR-transaction export into a distributable email report: a plant-wise GR value bar chart, a plant breakdown table, and a Top-10-Buyer GR value bar chart, all in ₹ Crores — sent immediately, on demand, via the company's on-prem SMTP server. There is no LLM anywhere in this system.

## Who Uses It

A single internal user at a packaging manufacturing company (e.g. a finance/ops analyst) who currently pulls GR data from Qlik/SAP by hand, builds the same three charts/tables in Excel, and emails them to plant/leadership recipients each reporting period. They want to do this in one upload-and-click action instead.

## Core Problem Being Solved

Replaces a manual, repeated Excel-and-email workflow with a single deterministic pipeline: upload the same export the user already has, click one button, and the correct plant/buyer breakdown reaches the right inboxes — with the numbers guaranteed to match the source file, not eyeballed or hand-copied.

## Success Criteria

- [ ] Uploading a real GR QVD or CSV and clicking **Send Report** delivers a real email within the same request, containing a correct plant-wise chart, a correct plant table, and a correct Top-10-Buyer chart, all in ₹ Crores.
- [ ] The computed totals are independently verified against a direct pandas recomputation of the same source file, within floating-point tolerance — this is tested, not asserted.
- [ ] A file missing a non-essential column (Buyer, or the period/date column) still produces a sent email, with the gap explicitly flagged in both the email body and the UI — never a silent gap.
- [ ] A file that cannot be parsed at all, or an SMTP send failure, blocks the email entirely and surfaces a clear, actionable error in the web UI — no partial or broken-looking email is ever sent, and there is no automatic retry.
- [ ] (Phase 2) A recipient configured with a plant scope receives only their plant(s)' data; a recipient absent from the scope config still receives the full report.

## What This Agent Does NOT Do (Out of Scope)

### Deferred to a named future phase (Phase 2, below)
- Per-recipient plant scoping (a config file restricting what each recipient sees).

### Permanently excluded — will not be built at any phase (do not re-add later)
- **Multi-file / folder union** — one file per run only; if a file spans multiple periods (e.g. a multi-month QVD), that is handled as a single file with a derived period range, not a folder-merge feature.
- **Period-over-period comparison** (e.g. this month vs last month) — not built, not planned.
- **Scheduled / folder-watch triggering** — manual trigger only, forever; no cron, no file-watcher.
- **Dry-run / preview mode** — clicking Send Report always sends immediately; there is no "preview before sending" step.
- **Run history / audit logging** — confirmed twice by the user: no database, no persisted record of past runs, ever.
- **Any LLM usage** — confirmed twice by the user: this agent is pure code end-to-end.
- **Authentication / multi-user accounts** — single local user, `localhost` only.

## Key Constraints

- Single-user, local tool — no multi-tenant concerns, no auth.
- Sends only via the company's on-prem SMTP server (Logix); no third-party email API.
- GR values are production-grade — recipients act on these numbers, so correctness must be independently testable against the raw source file.
- No automatic retries on any failure — the user re-triggers manually after fixing the input.
- Fully stateless: no database, no file persisted to disk except a transient temp file needed to hand a `.qvd` upload to `pyqvd` (deleted before the response returns).
- One file per run; the file itself may span multiple reporting periods (a multi-month QVD is normal input, not a special case).

---

## Phases of Development

> **Deviation from the default DB/Alembic gate items in `harness/patterns/phases.md`:** this project has no database (see `spec/architecture.md → Deliberate Deviations`). Every DB-specific gate item (driver in `[project.dependencies]`, `alembic upgrade head`, `alembic current`) does **not apply**; the gates below are the complete, authoritative gate for each phase.
>
> **Deviation from the "≥3 capabilities per requirements phase" default:** Phase 1 below already delivers all four core capabilities (the full primary journey), and Phase 2 delivers exactly the one capability the brief explicitly named as a deferred future phase (per-recipient plant scoping). Padding Phase 2 with unrelated capabilities purely to reach a numeric minimum would be scope creep — directly contradicted by this project's explicit "permanently excluded" list above. This is a deliberate, brief-driven exception, not an oversight.

### Phase 1 — Upload, Aggregate & Send

- **Goal:** the complete primary journey, first-time-right: upload one real QVD/CSV → enter recipients → click Send Report → a real email arrives via the real SMTP server with a correct plant-wise chart, plant table, and Top-10-Buyer chart in ₹ Crores, stating the source filename and reporting period. Degraded/fatal paths behave exactly per `spec/architecture.md`'s error matrix. This phase delivers all four Phase-1 capabilities in `spec/capabilities/index.md` — there is no smaller meaningful slice, and no non-functional stub is needed anywhere on this screen.

- **Independent slices (parallel build units):**
  - `slice-1` (backend) — File ingestion: `src/ingestion/loader.py`, `src/ingestion/columns.py`, `src/domain/report.py` (domain models). Deps: none.
  - `slice-2` (backend) — Aggregation + chart rendering: `src/reporting/aggregate.py`, `src/reporting/charts.py`. Deps: none — consumes the `LoadedDataset`/`ColumnMapping`/`ReportBundle` shapes already fixed in `spec/data.md`, so it can be authored concurrently with `slice-1` without reading its code.
  - `slice-3` (backend) — Email composition + SMTP send: `src/reporting/email_body.py`, `src/reporting/mailer.py`, `src/reporting/templates/report_email.html.j2`. Deps: none — consumes the `ReportBundle`/`SendResult` shapes fixed in `spec/data.md`.
  - `slice-4` (backend) — Pipeline wiring, API route, settings, cleanup: `src/reporting/pipeline.py`, `src/api/reports.py`, `src/api/__init__.py` (drop DB lifespan), `src/config/settings.py` (SMTP settings, no DB/LLM fields), `pyproject.toml` (owned exclusively by this slice — declares the full dependency set from `spec/architecture.md → Stack`, removes `sqlalchemy`/`alembic`/`anthropic`/`langgraph`/`google-genai`), removal of `src/db/`, `src/graph/`, `src/llm/`, `src/prompts/`, `src/domain/run.py`, `src/api/runs.py`, `alembic/`, `alembic.ini`. Deps: none to author (calls the documented public function signatures of slices 1–3); this is the integration point other slices' tests do not depend on.
  - `slice-5` (frontend) — The single page: `frontend/src/app/page.tsx` (upload + recipients + send + all 4 states), `frontend/tests/e2e/report-send.spec.ts`. Deps: none — calls `POST /reports/send` per `spec/api.md`.

- **Key surfaces / files:** see each slice above. `pyproject.toml` is edited only by `slice-4` to avoid concurrent-edit conflicts.

- **Gate command:**
  ```
  uv run pytest tests/phase1 -q
  ```
  followed by, from `frontend/`:
  ```
  pnpm build && cd .. && uv run python -m src
  ```
  then, in a second terminal, from `frontend/`:
  ```
  npx playwright test tests/e2e/ --reporter=line
  ```
  `tests/phase1/` must include, at minimum:
  - `test_column_detection.py` — alias matching across case/underscore/spacing variants, and every missing-column fatal/partial branch (F3/F4/F5/P1/P2/P3).
  - `test_aggregation_correctness.py` — the **real-data correctness gate**: a generated fixture `tests/fixtures/gr_export_large.csv` of **at least 6,000 rows** across **at least 6 plants and 40 buyers**, spanning a 4-month date range, with a final block of ~500 rows for one plant and one buyer engineered to be the true #1 by total value **only when the full file is processed** (a first-N-rows/sampled read would report a different #1 plant and #1 buyer). The test independently recomputes plant/buyer totals with `pandas.groupby(...).sum()` on the same fixture and asserts the pipeline's totals match within `1e-6` relative tolerance, and that the pipeline's #1 plant/buyer match the full-data answer specifically (not the sampled one).
  - `test_qvd_ingestion.py` — a small, hand-built/representative `.qvd` fixture confirming `pyqvd`-based loading produces the expected column set, row count, and values (format-level correctness; the large-scale correctness gate above is run via CSV since both formats converge to the same DataFrame → aggregation code path once loaded).
  - `test_email_mime_and_charts.py` — every returned chart is a structurally valid PNG (`PIL.Image.open` succeeds, non-trivial dimensions); the composed `EmailMessage` has the documented `multipart/related` structure with correctly-referenced `cid:` parts; the plant table appears as literal `<table>` HTML in the body.
  - `test_smtp_real_send.py` — **real SMTP integration test**: sends an actual email using the credentials in `.env` (`AGENT_SMTP_*`), addressed to `AGENT_SMTP_FROM_ADDRESS` itself (a real send to the service account's own mailbox — exercises the full real SMTP path without spamming a third party), and asserts no exception is raised. `pytest.skip` (not a stub) only if `AGENT_SMTP_HOST`/`AGENT_SMTP_USERNAME` are genuinely absent from `.env` — this is the same real-key-required discipline as an LLM test, applied to SMTP.
  - `test_error_paths.py` — every fatal condition F1–F8 raises the documented error and confirms no SMTP contact was attempted (mock/patch the SMTP client only in this specific test, to prove the pipeline never reaches it — not a substitute for `test_smtp_real_send.py`).
  - `test_api_reports_send.py` — `TestClient` end-to-end: posts a real fixture file + real recipient(s) to `POST /reports/send`, asserts the full response shape and a 200/4xx/5xx status matches the scenario.

  `frontend/tests/e2e/report-send.spec.ts` walks: open `http://localhost:8001/app/` → upload the small fixture CSV → type a recipient → click **Send Report** → assert the real success panel text appears (not a spinner, not an error) — run against the live server and the real SMTP path (addressed to `AGENT_SMTP_FROM_ADDRESS`, same convention as the backend test).

- **How the user tests it (handoff seed):**
  1. `cd frontend && pnpm build && cd ..`
  2. `uv run python -m src`
  3. Open `http://localhost:8001/app/`.
  4. Upload a real GR export (`.csv` or `.qvd`) with Plant, Buyer, and GR Value columns.
  5. Enter your own email address in the recipients box.
  6. Click **Send Report**.
  7. Expect: the page shows a green success panel within a few seconds (source filename + period stated); a real email arrives in your inbox with a plant-wise bar chart, a plant table (text you can select/copy), and a Top-10-Buyer bar chart, all figures in ₹ Crores.
  8. To see the partial-report path: upload a copy of the file with the Buyer column header renamed to something unrecognizable, and confirm the email still arrives with a Top-10-Buyer section omitted and a visible warning banner instead, matching the same warning shown on the page.
  9. To see the error path: upload a `.txt` file, and confirm the page shows a red error panel and **no email is sent**.
  - Everything on this screen is real — there are no non-functional stubs in Phase 1.

---

### Phase 2 — Per-Recipient Plant Scoping

- **Goal:** the exact deferred feature named in the brief — recipients configured in a scope file see only their plant(s)' data; everyone else keeps getting the Phase 1 full report unchanged.

- **Independent slices (parallel build units):**
  - `slice-1` (backend) — Scope config loading + grouping: `src/reporting/scoping.py`, `config/recipient_scopes.json.example` (checked in; real `config/recipient_scopes.json` is user-maintained and gitignored), `.env.example` addition (`AGENT_RECIPIENT_SCOPES_PATH`). Deps: none.
  - `slice-2` (backend) — Pipeline integration: `src/reporting/pipeline.py` updated to compute one `ReportBundle` per scope group and issue one send per group; `src/api/reports.py` response gains `scoped_recipients`. Deps: **true dependency on `slice-1`'s `scoping.py` public functions** (`load_scopes()`, `group_recipients_by_scope()`) — serialize this slice after `slice-1` lands.
  - `slice-3` (frontend) — Small, real (non-stub) addition to the success panel: when `scoped_recipients` is non-empty, list which recipients received a scoped vs. full report. `frontend/src/app/page.tsx`, `frontend/tests/e2e/report-send-scoped.spec.ts`. Deps: none — reads the Phase-2 API field per `spec/api.md`; can be authored concurrently against the documented shape.

- **Key surfaces / files:** see slices above.

- **Gate command:**
  ```
  uv run pytest tests/phase2 -q
  ```
  `tests/phase2/` must include, at minimum:
  - `test_scoping_grouping.py` — a scoped recipient sees only their configured plant(s)' rows in the recomputed `ReportBundle`; a multi-plant recipient sees the union; recipients sharing a scope are grouped into one send.
  - `test_scoping_unconfigured.py` — a recipient absent from the config still gets the full, unrestricted report, byte-for-byte equivalent to the Phase 1 path.
  - `test_scoping_missing_config.py` — a missing/malformed `config/recipient_scopes.json` degrades to "everyone unscoped" and does not fail the run; a warning is present in the API response.
  - `test_scoping_plant_not_in_file.py` — a configured plant code with zero matching rows in the current file produces a valid, non-fatal, empty-for-that-plant report plus the documented warning text.
  - `test_smtp_real_send_scoped.py` — real SMTP send (same `.env`-driven, self-addressed convention as Phase 1) confirming a scoped group is sent as one message distinct from another scope group's message.

- **How the user tests it (handoff seed):**
  1. Create `config/recipient_scopes.json` (see `spec/data.md` for the exact format) mapping your own email to one plant code that exists in your test file.
  2. Restart the server (`uv run python -m src`), open `http://localhost:8001/app/`, upload the same file, enter your email plus one other (unconfigured) email you control, and click **Send Report**.
  3. Expect: your email contains only your configured plant's rows; the other (unconfigured) address receives the full, unrestricted report — two distinct emails.
  4. Delete/rename `config/recipient_scopes.json` and repeat — expect both recipients now receive the full report, with a warning noted in the success panel that the scope config could not be read.
