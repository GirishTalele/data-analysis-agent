# UI

---

## UI Type

Web page — a single screen, not a chat interface, not a CLI. Served at `http://localhost:8001/app/` (Next.js static export, single-origin per `harness/patterns/tech-stack.md`).

## Views / Screens

### Screen: GR Report Sender (the only screen)

**Purpose:** upload one GR data file, enter recipients, and send the report — everything the user needs, on one screen.

**Key elements:**
- File input restricted to `.csv`/`.qvd` (drag-and-drop or click-to-browse), showing the chosen filename once selected.
- Recipients `<textarea>` with helper copy: "One or more email addresses, separated by commas or new lines."
- **Send Report** button — the single primary action; disabled until a file is chosen **and** the recipients field contains at least one non-empty line.
- A status/result area below the form.

**Actions available:**
- Choose/replace the file.
- Edit the recipients text.
- Click **Send Report**.

### States (all real in Phase 1 — no non-functional stubs on this screen)

1. **Empty/idle** — no file chosen yet. Helper copy explains what to upload and what the report will contain ("Upload your GR export (CSV or QVD) to email a plant-wise and Top-10-Buyer GR value report."). Never a blank panel.
2. **Loading** — immediately on click: the button disables and reads "Generating & sending report…"; nothing else on the page changes so the user isn't confused about what's happening.
3. **Success** — a green panel: `"Report sent to {N} recipient(s)."`, the source filename, and the reporting period. If `warnings` is non-empty, an amber sub-panel lists each warning verbatim. If `recipients_rejected` is non-empty, a note lists which entered addresses were skipped as invalid.
4. **Error** — a red panel with the exact `error.detail.message` text plus a one-line actionable hint (e.g. "Check that the file has Plant, Buyer, and GR Value columns" for column errors, "The mail server may be unreachable — contact IT" for `SMTP_SEND_FAILED`). Never a raw stack trace or bare status code.

## Error States

Covered fully by states 2–4 above. No separate error page — everything happens on the single screen so the user never loses their file selection or recipient list on failure (both remain populated after an error so they can fix and retry immediately).

## Tech Stack

Next.js 15 + React 19, static export (`output: 'export'`, `basePath: '/app'`), Tailwind v4 (existing `postcss.config.mjs` + `@source "../"` setup — do not touch), served by the FastAPI backend at `:8001/app/`. Playwright (`frontend/tests/e2e/`) covers the primary journey: upload a fixture file → enter a recipient → click Send Report → see the real success panel.
