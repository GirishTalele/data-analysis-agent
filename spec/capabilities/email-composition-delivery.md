# Capability: HTML Email Composition & SMTP Delivery

## What It Does

Composes one `multipart/related` HTML email — charts embedded as inline `cid:` images, the plant table as real selectable HTML, the source filename and reporting period stated up top, any degraded-section warnings shown as a visible banner — and sends it immediately through the company's on-prem SMTP server to every syntactically-valid recipient.

## Inputs

| Input | Type | Source | Required |
|-------|------|--------|----------|
| `ReportBundle` | domain model | GR Aggregation & Chart/Table Generation capability | yes |
| `source_filename` | `str` | File Ingestion & Column Validation capability (`LoadedDataset.source_filename`) | yes |
| Recipient list (raw string, comma/newline separated) | `str` | `POST /reports/send` form field `recipients` | yes |

## Outputs

| Output | Type | Destination |
|--------|------|-------------|
| `SendResult` (see `spec/data.md`) | domain model | API layer → returned to the browser |
| The email itself | MIME message, delivered | Every valid recipient's inbox (via SMTP) |

## External Calls

| System | Operation | On Failure |
|--------|-----------|------------|
| Company SMTP server (Logix, `.env` `AGENT_SMTP_*`) | Connect, optionally STARTTLS, authenticate, send the composed message | Fatal — `SMTP_SEND_FAILED` (F7, HTTP 502); no retry; nothing was delivered to anyone |

## Business Rules

- Recipient parsing: split the raw string on commas and/or newlines, strip whitespace, drop empty entries, de-duplicate case-insensitively.
- Each remaining entry is validated as an email address (Pydantic `EmailStr`). Invalid entries are excluded from the send and reported in `SendResult.recipients_rejected` (warning P5) — **not** fatal, unless zero valid entries remain (F6, fatal, checked before any SMTP contact).
- Subject: `"GR Report — {period} — {source_filename}"`.
- Body must state the source filename and the reporting period near the top, before any chart.
- If `ReportBundle.warnings` is non-empty, a visible warning banner is rendered above the charts, listing every warning verbatim.
- The buyer image part (and its `<img>` reference) is omitted entirely from the MIME message when `ReportBundle.buyer_chart_png is None` — never render a broken/missing inline-image reference. Same rule for the plant chart/table.
- MIME structure exactly as specified in `spec/architecture.md → Email MIME Structure` — table is real `<table>` HTML, never a table rendered as an image.
- One SMTP send call, one message, all valid recipients in the `To` field (single-user tool, no personalization in Phase 1 — see the Phase 2 capability for per-recipient scoping, which changes this to one send per distinct scope group).
- No automatic retries on SMTP failure of any kind.

## Success Criteria

- [ ] A real send (via `.env` SMTP credentials) to a real inbox produces an email whose inline images render (verifiable by re-parsing the sent `EmailMessage`'s `cid:`-referenced parts) and whose table is present as literal `<table>` markup, not an image.
- [ ] The email body visibly states the exact `source_filename` and `period_label` values from the inputs.
- [ ] A run with a `ReportBundle.warnings` list produces an email containing every warning string verbatim, and the corresponding `SendResult.warnings` list is identical.
- [ ] A recipients string that is empty or contains only invalid addresses raises the fatal `NO_VALID_RECIPIENTS` error and never contacts the SMTP server.
- [ ] A recipients string with a mix of valid and invalid addresses sends only to the valid ones and reports the invalid ones in `recipients_rejected`.
- [ ] Simulating an SMTP authentication/connection failure raises `SMTP_SEND_FAILED` and no partial artifact (no half-sent email) exists.
