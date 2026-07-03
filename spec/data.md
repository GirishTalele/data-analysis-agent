# Data Model

---

## Storage Technology

SQLite (`data/agent.db`), accessed via SQLAlchemy 2.0 declarative models and versioned with Alembic migrations. Chosen because this is an explicitly local, single-user tool (see `spec/roadmap.md` → Key Constraints) — matches the default rule in `harness/patterns/tech-stack.md`. Uploaded files themselves are stored on the local filesystem (see `spec/architecture.md` → Local File Storage Layout), not as BLOBs in SQLite.

## Entities

### Entity: Dataset

Represents one logical dataset the user analyzes — one uploaded file in Phase 1; in Phase 2, may be backed by multiple files (`kind="multi_file"`, a folder treated as one dataset) or a join of other datasets (`kind="joined"`).

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | text (UUID) | yes | Primary key |
| name | text | yes | User-facing label; defaults to the first file's name |
| kind | text | yes | `"single_file"` \| `"multi_file"` \| `"joined"` (Phase 1 always `"single_file"`) |
| status | text | yes | `"profiling"` \| `"ready"` \| `"error"` |
| created_at | timestamp | yes | |
| updated_at | timestamp | yes | Bumped whenever a file is added or the dataset is re-profiled |

### Entity: DatasetFile

One physical file backing a Dataset. One row in Phase 1; multiple rows per dataset in Phase 2 (folder-as-dataset).

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | text (UUID) | yes | Primary key |
| dataset_id | text (FK → Dataset.id) | yes | |
| original_filename | text | yes | As uploaded |
| stored_path | text | yes | Path relative to `AGENT_DATA_DIR` |
| file_type | text | yes | `"csv"` \| `"xlsx"` \| `"xls"` |
| size_bytes | integer | yes | |
| row_count | integer | yes | Row count of this individual file |
| uploaded_at | timestamp | yes | |

### Entity: DatasetProfile

The auto-generated profile shown to the user immediately after upload. History is retained (not overwritten) so the audit trail can show what the schema looked like at the time of any given query; `GET /datasets/{id}/profile` always returns the most recent row.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | text (UUID) | yes | Primary key |
| dataset_id | text (FK → Dataset.id) | yes | |
| row_count | integer | yes | Total rows across all `DatasetFile`s at profiling time |
| column_count | integer | yes | |
| columns_json | JSON | yes | List of `{name, dtype, missing_count, missing_pct, unique_count, sample_values, min, max, mean}` (numeric fields null for non-numeric columns) — this is exactly the `schema_context` handed to the LLM; see `spec/architecture.md` → Raw-Row Privacy Boundary |
| generated_at | timestamp | yes | |

### Entity: Conversation

A chat session tied to one dataset; persists across app restarts.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | text (UUID) | yes | Primary key |
| dataset_id | text (FK → Dataset.id) | yes | |
| title | text | yes | Derived from the first question, or `"Untitled analysis"` |
| created_at | timestamp | yes | |
| updated_at | timestamp | yes | Bumped on every new message |

### Entity: ChatMessage

One turn in a Conversation.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | text (UUID) | yes | Primary key |
| conversation_id | text (FK → Conversation.id) | yes | |
| role | text | yes | `"user"` \| `"assistant"` \| `"system"` |
| content | text | yes | For `"assistant"`, this is `answer_text` (or the clarification question); for `"user"`, the question as typed |
| query_run_id | text (FK → QueryRun.id) | no | Links an assistant message to the run that produced it (null for user/system messages) |
| created_at | timestamp | yes | |

### Entity: QueryRun (the audit trail)

One row per user question — the full record of what was asked, what code ran, what it returned, and what it cost. Never deleted (this repo's tool is meant to be queryable later per `spec/roadmap.md`).

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | text (UUID) | yes | Primary key |
| conversation_id | text (FK → Conversation.id) | yes | |
| dataset_id | text (FK → Dataset.id) | yes | Denormalized for fast audit queries without a join |
| question_text | text | yes | The user's question, verbatim |
| generated_code | text | no | The final pandas code executed (null only if `status="failed"` before code generation, or `status="clarification_needed"`) |
| step_count | integer | yes | Number of generate→execute attempts made this turn (always 1 in Phase 1) |
| execution_status | text | yes | `"success"` \| `"execution_error"` \| `"cannot_answer"` \| `"clarification_needed"` \| `"failed"` |
| result_summary_json | JSON | no | The *summarized* (never-raw-row) execution result the answer was based on |
| answer_text | text | no | The plain-language answer (or clarification question, or can't-answer explanation) |
| clarification_question | text | no | Set only when `execution_status="clarification_needed"` (Phase 2) |
| follow_up_suggestions_json | JSON | no | List of 2-3 suggested follow-up questions (Phase 2; `null`/`[]` in Phase 1) |
| anomalies_json | JSON | no | List of flagged data-quality notes (Phase 2; `null`/`[]` in Phase 1) |
| result_table_json | JSON | no | Structured summary table backing a tabular/breakdown answer (Phase 2), shape `{ "columns": [str, ...], "rows": [[cell, ...], ...] }`. This is AGGREGATED/DERIVED output (e.g. a groupby result), NOT raw source rows — it is produced only from the already-summarized execution result and therefore stays within the raw-row privacy boundary, subject to the same row cap (`AGENT_MAX_SUMMARY_ROWS`; see `spec/architecture.md` → Raw-Row Privacy Boundary). `null` when the answer has no tabular breakdown (scalar-only answers) and always `null` in Phase 1. |
| prompt_tokens | integer | yes | Summed across all LLM calls in this turn |
| completion_tokens | integer | yes | Summed across all LLM calls in this turn |
| estimated_cost_usd | numeric | yes | Computed from `prompt_tokens`/`completion_tokens` and the configured per-token prices (see `spec/architecture.md`) |
| latency_ms | integer | yes | Wall-clock time for the whole turn |
| error_message | text | no | Set when `execution_status="failed"` or `"execution_error"` |
| created_at | timestamp | yes | |

### Entity: DerivedDataset (Phase 2)

An exported/cleaned dataset produced from a QueryRun.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | text (UUID) | yes | Primary key |
| source_dataset_id | text (FK → Dataset.id) | yes | |
| created_from_query_run_id | text (FK → QueryRun.id) | no | The run whose code produced this export, if any |
| name | text | yes | User-facing label |
| stored_path | text | yes | Path relative to `AGENT_DATA_DIR`, under `derived/` |
| row_count | integer | yes | |
| created_at | timestamp | yes | |

### Relationships

- `Dataset` 1—N `DatasetFile`
- `Dataset` 1—N `DatasetProfile` (history; latest by `generated_at` is "current")
- `Dataset` 1—N `Conversation`
- `Dataset` 1—N `DerivedDataset`
- `Conversation` 1—N `ChatMessage`
- `Conversation` 1—N `QueryRun`
- `ChatMessage` 0..1—1 `QueryRun` (an assistant message optionally links to the run that produced it)

## Data Lifecycle

- **Created:** `Dataset` + `DatasetFile` + `DatasetProfile` on upload; `Conversation` on the first question against a dataset (auto-created if the client doesn't pass one); `ChatMessage` + `QueryRun` on every question/answer turn; `DerivedDataset` on export (Phase 2).
- **Updated:** `Dataset.updated_at` and a new `DatasetProfile` row on adding a file (Phase 2 multi-file) or a join (Phase 2); `Conversation.updated_at` on every new message.
- **Deleted:** nothing is automatically deleted or archived — this is a single-user local tool where the audit trail is explicitly meant to be retained and queryable later (`spec/roadmap.md` → Key Constraints). No TTL, no cleanup job in scope.

## Sensitive Data

- Uploaded files may contain the user's own business data; they are stored only on the local filesystem, never uploaded to any external service, and never appear in `columns_json`/`result_summary_json` beyond aggregated statistics (see `spec/architecture.md` → Raw-Row Privacy Boundary).
- `AGENT_GEMINI_API_KEY` and any future provider key live only in `.env` (gitignored), loaded via `Settings`, confirmed by presence only — never logged or stored in the DB.
- No PII-specific handling is implemented beyond the raw-row boundary itself — if the user's file contains PII, it is treated the same as any other column: aggregated statistics only ever leave the machine.
