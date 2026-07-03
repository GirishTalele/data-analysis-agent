# UI

---

## UI Type

Chat-style web interface (single page, served at `http://localhost:8001/app/`), with a file-upload area and a profile card above the chat thread.

## Views / Screens

### Screen: Upload & Profile (top of the single page)

**Purpose:** Get a dataset in and see it profiled before asking anything.

**Key elements:**
- File drop-zone / picker, accepting `.csv`/`.xlsx`/`.xls`.
- Profile card: row count, column count, and a scrollable table of `{column, dtype, missing %, sample/min-max}` — rendered from `GET/POST /datasets` response.
- **[Labelled stub, Phase 1]** "+ Add another file" button, greyed out with a "Multi-file datasets — coming soon" tooltip. Non-functional; never mistaken for a bug because it is visibly disabled and labelled.

**Actions available (Phase 1):** upload one file; view its profile.

**States:**
- *Empty:* "Upload a CSV or Excel file to get started" with the drop-zone as the one action. Never a blank panel.
- *Loading:* "Profiling your data…" with a spinner over the drop-zone; upload button disabled meanwhile.
- *Error:* "Couldn't read this file — make sure it's a valid CSV or Excel file under 100MB" plus the reason if known; the drop-zone remains usable to retry.
- *Ideal:* profile card populated as above.

### Screen: Chat / Analysis (below the profile card, appears once a dataset is ready)

**Purpose:** Ask questions about the uploaded data and read answers.

**Key elements:**
- Message thread: user question bubbles (right-aligned) and assistant answer bubbles (left-aligned), rendered through a markdown renderer (never raw text) so numbered lists / bold key numbers render correctly.
- **SummaryTable component (Phase 2):** rendered inside the assistant answer bubble, positioned between the key numbers and the chart. Displays the `query_run.result_table` (`{columns, rows}` from `spec/api.md`) as a plain HTML `<table>` (column headers from `columns`, one `<tr>` per entry in `rows`). Absent entirely when `result_table` is `null` (scalar-only answers). It renders alongside the interactive chart (built by the `frontend-step-list-and-charts` slice) and the existing "View code" disclosure — the three are complementary views of the same answer.
- "View code" collapsible toggle under each assistant message — expands to show the exact pandas code that ran, monospace, syntax-formatted.
- Per-message cost/token badge, e.g. `908 tokens · $0.0016`, next to each assistant message.
- A pinned header badge showing the running session total (tokens + estimated cost) across the whole conversation.
- Step-progress indicator while a query runs: Phase 1 shows a single real step ("Running analysis…") since there is exactly one pass — this is real progress, not a stub, and disappears once the answer renders.
- Question input box + send button, disabled while a query is in flight.
- **[Labelled stubs, Phase 1 — visibly marked "Coming soon", non-interactive or clearly inert]:**
  - A chart placeholder panel beneath any numeric answer, with a caption "Interactive charts — coming in a future update" (no fake chart image).
  - A disabled "Export cleaned data" button with a tooltip explaining it's not yet available.
  - A disabled "View audit trail" nav link/icon with the same "coming soon" treatment.
  - No follow-up-suggestion chips are rendered at all in Phase 1 (rather than fake/non-functional ones) — Phase 2 introduces real, clickable suggestions.

**Actions available (Phase 1):** type and submit a question; expand/collapse the code view for any past answer; reload the page and see the same history.

**States:**
- *Empty (before first question):* "Ask a question about your data — e.g. 'What's the average of column X?'" placeholder text in the input.
- *Loading:* step indicator active, input disabled, existing messages remain visible and scrollable.
- *Error:* an inline assistant-style bubble with a plain-language explanation (`cannot_answer`/`failed` cases from `spec/agent.md`) — e.g. "I couldn't compute that: the column 'reveune' doesn't exist in this file. Did you mean 'revenue'?" — never a raw stack trace or a silent failure.
- *Ideal:* answer bubble with key numbers, code toggle, cost badge, all populated.

## Error States

- Upload errors, in-flight network errors ("Network error — is the server running?"), and agent-side `cannot_answer`/`failed` results are each rendered as a distinct, human-readable message in context (on the upload card or in the chat thread respectively) — never a bare HTTP status or JSON blob.
- Every error state names what failed and, where known, why and what to do next (per `harness/patterns/ui-ux.md`).

## Tech Stack

Next.js 15 + React 19, static export (`output: 'export'`, `basePath: '/app'`) served by FastAPI at `/app` (existing skeleton pattern) — Tailwind v4 for styling, `react-markdown` + `remark-gfm` for rendering assistant messages, Playwright for the `frontend/tests/e2e/` smoke suite. See `spec/architecture.md` → Stack for the full rationale.
