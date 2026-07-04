# Capability: Error Surfacing in the Web UI

## What It Does

Renders the correct, unambiguous UI state for every possible pipeline outcome — loading while the request is in flight, a success panel (with any warnings) when the email was sent, or an error panel when nothing was sent — so the user is never left staring at an ambiguous or broken-looking result.

## Inputs

| Input | Type | Source | Required |
|-------|------|--------|----------|
| JSON response body from `POST /reports/send` (success envelope or `{"detail": {"code","message"}}` error) | JSON | Backend API | yes |
| HTTP status code | `int` | Backend API | yes |

## Outputs

| Output | Type | Destination |
|--------|------|-------------|
| Rendered UI state (idle / loading / success / error) | React component state | Browser |

## External Calls

None — this capability is a pure client-side rendering contract over the API response already defined in `spec/api.md`.

## Business Rules

- A non-2xx HTTP response (any F1–F8 code from `spec/architecture.md`) **always** renders the Error panel: the exact `detail.message` text, plus a short actionable hint (e.g. missing-column errors hint "check the file has Plant, Buyer and GR Value columns"; `SMTP_SEND_FAILED` hints "the mail server may be unreachable — contact IT"). Never a raw stack trace, never a bare status code.
- A 2xx response **always** renders the Success panel, even when `warnings` is non-empty — a partial report is still a successful send and must read as one, with the gaps called out separately, never mixed into the error path.
- If `warnings` is non-empty, the Success panel shows an amber sub-section listing each warning verbatim.
- If `recipients_rejected` is non-empty, the Success panel shows a note listing which entered addresses were skipped as invalid — this is always a UI-only note (those addresses never received an email, so nothing can be flagged to them).
- While the request is in flight, the Send Report button is disabled and shows in-progress copy ("Generating & sending report…") — never a frozen, unlabelled wait.
- Nothing here retries automatically; a failed run requires the user to fix the input (file or recipients) and click Send Report again.

## Success Criteria

- [ ] Every fatal error code (F1–F8) renders a human-readable message and hint, never a stack trace or a raw JSON dump.
- [ ] A 2xx response with an empty `warnings` list renders a clean success panel with no warning sub-section shown.
- [ ] A 2xx response with a non-empty `warnings` list renders both the success confirmation and the warnings sub-section in the same panel (not a separate ambiguous state).
- [ ] A response with a non-empty `recipients_rejected` list shows exactly those addresses in the UI.
- [ ] Clicking Send Report immediately (within ~100ms) disables the button and shows in-progress copy; the button re-enables once the response (success or error) arrives.
