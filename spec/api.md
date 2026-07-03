# API

---

## API Style

REST (FastAPI), envelope pattern per the existing skeleton (`ok(data)` / `api_error(code, message, status)`). All endpoints below are relative to `http://localhost:8001`. The frontend consumes this exact contract so `frontend-chat-ui` (Phase 1) and the Phase-2 frontend slices can build against it in parallel with the backend slices.

## Endpoints / Commands — Phase 1

### `POST /datasets`

**Purpose:** Upload a single CSV/Excel file, store it locally, and auto-profile it synchronously.

**Request:** `multipart/form-data` with field `file` (`.csv`, `.xlsx`, or `.xls`, ≤ `AGENT_MAX_UPLOAD_MB`).

**Response:**
```json
{
  "data": {
    "dataset": { "id": "uuid", "name": "sales_q1.csv", "kind": "single_file", "status": "ready", "created_at": "iso8601" },
    "profile": {
      "row_count": 12000,
      "column_count": 8,
      "columns": [
        { "name": "order_date", "dtype": "datetime64", "missing_count": 0, "missing_pct": 0.0, "unique_count": 365, "sample_values": ["2025-01-02"], "min": "2025-01-01", "max": "2025-12-31" },
        { "name": "amount", "dtype": "float64", "missing_count": 12, "missing_pct": 0.1, "min": 0.0, "max": 4200.5, "mean": 88.4 }
      ],
      "generated_at": "iso8601"
    }
  },
  "error": null
}
```

**Error cases:**
| Status | Condition |
|--------|-----------|
| 400 | Unsupported file type, unreadable/corrupt file, or file exceeds `AGENT_MAX_UPLOAD_MB` |
| 500 | Storage or profiling failure unrelated to the file itself |

### `GET /datasets/{dataset_id}`

**Purpose:** Retrieve a dataset and its current (latest) profile.

**Response:** same `{dataset, profile}` shape as `POST /datasets`.

**Error cases:** `404` if `dataset_id` doesn't exist.

### `GET /datasets/{dataset_id}/profile`

**Purpose:** Retrieve just the current profile (used to refresh the profile card without re-fetching everything).

**Response:** the `profile` object above.

**Error cases:** `404` if `dataset_id` doesn't exist.

### `POST /datasets/{dataset_id}/conversations`

**Purpose:** Explicitly start a new conversation against a dataset (optional — `POST .../messages` auto-creates one if `conversation_id` is omitted).

**Request:** `{}` (empty body; title is derived later from the first question).

**Response:**
```json
{ "data": { "id": "uuid", "dataset_id": "uuid", "title": "Untitled analysis", "created_at": "iso8601" }, "error": null }
```

### `POST /conversations/{conversation_id}/messages`

**Purpose:** Ask a natural-language question; runs the analysis loop (`spec/agent.md`) synchronously and returns the answer.

**Request:**
```json
{ "question": "What's the average order amount?" }
```

**Response:**
```json
{
  "data": {
    "message": { "id": "uuid", "role": "assistant", "content": "The average order amount is $88.40.", "created_at": "iso8601" },
    "query_run": {
      "id": "uuid",
      "execution_status": "success",
      "generated_code": "result = df['amount'].mean()",
      "answer_text": "The average order amount is $88.40.",
      "key_numbers": { "average_amount": 88.4 },
      "follow_up_suggestions": [],
      "anomalies": [],
      "result_table": null,
      "step_count": 1,
      "prompt_tokens": 812,
      "completion_tokens": 96,
      "estimated_cost_usd": 0.0016,
      "latency_ms": 4210
    }
  },
  "error": null
}
```

**`result_table` field (Phase 2):** the `query_run` object also carries `result_table`, shape `{ "columns": [...], "rows": [...] } | null`, the structured summary table backing a tabular/breakdown answer (maps to `QueryRun.result_table_json` in `spec/data.md`). It is `null` for scalar-only answers and always `null` in Phase 1. It is AGGREGATED/DERIVED output, never raw source rows, and never exceeds `AGENT_MAX_SUMMARY_ROWS` rows. Example — for "average revenue by region":
```json
"result_table": {
  "columns": ["region", "avg_revenue"],
  "rows": [["North", 88.4], ["South", 74.1], ["East", 91.2], ["West", 60.5]]
}
```
This same `result_table` field also appears on each `QueryRun` record returned by `GET /query-runs`.

**Error cases:**
| Status | Condition |
|--------|-----------|
| 400 | Empty question, or `dataset_id` resolved from the conversation has no ready profile |
| 404 | `conversation_id` doesn't exist |
| 409 | Another question is already running for this conversation |
| 200 (with `query_run.execution_status="failed"` or `"cannot_answer"`) | The agent itself failed/couldn't answer — this is a normal, well-formed response, not an HTTP error, so the UI can render the plain-language explanation |

### `GET /conversations/{conversation_id}/messages`

**Purpose:** Load full chat history (used on page load / after a restart so history persists).

**Response:**
```json
{
  "data": {
    "conversation": { "id": "uuid", "dataset_id": "uuid", "title": "Untitled analysis" },
    "messages": [
      { "id": "uuid", "role": "user", "content": "What's the average order amount?", "created_at": "iso8601" },
      { "id": "uuid", "role": "assistant", "content": "The average order amount is $88.40.", "query_run_id": "uuid", "created_at": "iso8601" }
    ],
    "session_cost_total_usd": 0.0016,
    "session_tokens_total": 908
  },
  "error": null
}
```

**Error cases:** `404` if `conversation_id` doesn't exist.

## Endpoints / Commands — Phase 2

### `POST /datasets/{dataset_id}/files`

**Purpose:** Add another file to an existing dataset (folder-as-dataset). Triggers re-profiling across the unioned files.

**Request:** `multipart/form-data`, field `file`.

**Response:** updated `{dataset, profile}` (as `POST /datasets`), with `dataset.kind` becoming `"multi_file"`.

### `POST /datasets/join`

**Purpose:** Create a new joined `Dataset` from two or more existing datasets.

**Request:**
```json
{ "dataset_ids": ["uuid1", "uuid2"], "join_on": "customer_id", "how": "inner" }
```

**Response:** `{dataset, profile}` for the new joined dataset (`kind="joined"`).

**Error cases:** `400` if the join key doesn't exist in all datasets.

### `POST /datasets/{dataset_id}/export`

**Purpose:** Export a cleaned/derived dataset produced by a prior `QueryRun`.

**Request:**
```json
{ "query_run_id": "uuid", "name": "cleaned_sales.csv" }
```

**Response:**
```json
{ "data": { "derived_dataset": { "id": "uuid", "name": "cleaned_sales.csv", "row_count": 11988, "download_url": "/datasets/uuid/derived/uuid/download" } }, "error": null }
```

### `GET /datasets/{dataset_id}/derived`

**Purpose:** List derived/exported datasets for a dataset.

### `GET /datasets/{dataset_id}/derived/{derived_id}/download`

**Purpose:** Download a previously-exported derived/cleaned dataset as a CSV file (the `download_url` returned by `POST /datasets/{dataset_id}/export`).

**Path params:** `dataset_id` (the parent dataset), `derived_id` (the exported derived dataset).

**Response:** the CSV file (`text/csv` attachment).

### `GET /query-runs`

**Purpose:** Browse the full audit trail (across all conversations/datasets).

**Query params:** `dataset_id`, `conversation_id`, `from`, `to`, `execution_status` (all optional filters), `limit`, `offset`.

**Response:** paginated list of `QueryRun` records (same shape as the `query_run` object in `POST /conversations/{id}/messages`, including the `result_table` field).

### `GET /cost-summary`

**Purpose:** Running cost/token totals for the dashboard.

**Query params:** `scope` = `"session"` | `"day"` | `"all"`; optional `conversation_id`.

**Response:**
```json
{ "data": { "scope": "day", "date": "2026-07-03", "total_tokens": 15230, "total_cost_usd": 0.041, "query_count": 9 }, "error": null }
```

## Authentication

None — single local user, no network exposure beyond `localhost:8001`. Out of scope per `spec/roadmap.md`.
