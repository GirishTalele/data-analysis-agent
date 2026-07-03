# API

---

## API Style

REST, single-origin at `http://localhost:8001`. Two routes total. (Backend framework choice lives in `spec/architecture.md → Stack`.)

## Endpoints

### `GET /health`

**Purpose:** liveness check (unchanged from the boilerplate skeleton).

**Response:**
```json
{ "data": { "status": "ok" }, "error": null }
```

---

### `POST /reports/send`

**Purpose:** Upload a GR data file, validate & aggregate it, compose and send the email report to the given recipients — synchronous, immediate send, no preview/approval step.

**Request:** `multipart/form-data`

| Field | Type | Required | Description |
|-------|------|----------|--------------|
| `file` | binary | yes | The `.csv` or `.qvd` export |
| `recipients` | string | yes | Comma and/or newline separated email addresses |

**Response — 200 (sent, possibly with warnings):**
```json
{
  "data": {
    "status": "sent",
    "source_filename": "GR_Export_Jun2026.qvd",
    "period": "Jun 2026",
    "recipients_sent": ["a@company.com", "b@company.com"],
    "recipients_rejected": ["not-an-email"],
    "warnings": [
      "Top-10 Buyer chart could not be generated: no recognizable Buyer column found in the source file."
    ]
  },
  "error": null
}
```

`recipients_rejected` and `warnings` are always present (empty arrays when there is nothing to report) so the frontend never has to guard against missing keys.

**Error cases:**

| Status | Code | Condition |
|--------|------|-----------|
| 400 | `NO_VALID_RECIPIENTS` | `recipients` empty, or every entered address fails email validation |
| 422 | `UNSUPPORTED_FILE_TYPE` | file extension is not `.csv`/`.qvd` |
| 422 | `FILE_UNREADABLE` | file cannot be parsed at all (corrupt/empty/zero rows) |
| 422 | `GR_VALUE_COLUMN_MISSING` | no column matches a GR Value alias |
| 422 | `GR_VALUE_UNPARSABLE` | GR Value column detected but every row fails numeric coercion |
| 422 | `NO_GROUPING_COLUMN` | neither Plant nor Buyer column is detectable |
| 502 | `SMTP_SEND_FAILED` | SMTP connection/auth/timeout failure — report was computed but never delivered |
| 500 | `INTERNAL_ERROR` | any other unhandled exception |

Error body shape (consistent across every error case):
```json
{ "detail": { "code": "GR_VALUE_COLUMN_MISSING", "message": "No GR Value column could be found in the uploaded file." } }
```

Full condition definitions live in `spec/architecture.md → Error Handling & Reliability Model` (one fact, one place — this table cross-references it, not restates it).

## Phase 2 Addition

No new route. `POST /reports/send` gains one additional response field once per-recipient plant scoping is wired:

```json
{
  "data": {
    "...": "... (all Phase 1 fields, unchanged)",
    "scoped_recipients": {
      "plant.head@company.com": ["1010"],
      "regional.manager@company.com": ["1010", "1020"]
    }
  }
}
```

Recipients absent from `scoped_recipients` received the full, unrestricted report (Phase 1 behavior). See `spec/capabilities/recipient-plant-scoping.md`.

## Authentication

None. This is a local, single-user tool bound to `localhost:8001` — no login, no API key, no multi-user concept.

> **Assumed:** no authentication is required at any phase covered by this spec, per the brief's "single user" framing. If this tool is ever exposed beyond localhost, authentication must be added first — that is explicitly out of scope here.
