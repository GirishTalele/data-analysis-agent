# Capability: Dataset Ingestion & Profiling

## What It Does

Accepts an uploaded CSV/Excel file (Phase 2: multiple files or a folder treated as one dataset), stores it locally, and immediately auto-profiles it — columns, dtypes, row count, missing values — without the user having to ask.

## Inputs

| Input | Type | Source | Required |
|-------|------|--------|----------|
| File upload | `.csv` / `.xlsx` / `.xls`, ≤ `AGENT_MAX_UPLOAD_MB` | `POST /datasets` (multipart) | yes |
| Additional file (Phase 2) | same | `POST /datasets/{id}/files` | no |
| Join spec (Phase 2) | `{dataset_ids, join_on, how}` | `POST /datasets/join` | no |

## Outputs

| Output | Type | Destination |
|--------|------|-------------|
| `Dataset` record | row in `datasets` | SQLite (`spec/data.md`) |
| `DatasetFile` record(s) | row(s) in `dataset_files` | SQLite |
| `DatasetProfile` | row in `dataset_profiles`, returned as JSON | SQLite + `POST /datasets` / `GET /datasets/{id}/profile` response |

## External Calls

| System | Operation | On Failure |
|--------|-----------|------------|
| Local filesystem | Write uploaded file to `data/datasets/<id>/original/` | 400/500 with a human message; nothing partially persisted (no `Dataset` row without a readable file) |
| pandas | Parse file, compute dtypes/missing values/row count | Unreadable/corrupt file → 400 with the parse error surfaced in plain language |

## Business Rules

- Profiling happens synchronously on upload — the user never has to click "profile" separately.
- Profiling never sends the file contents anywhere except the local pandas process; only the resulting `columns_json` (aggregated stats) is ever eligible to reach the LLM (see `spec/architecture.md` → Raw-Row Privacy Boundary).
- Phase 1: exactly one file per dataset (`kind="single_file"`). Phase 2: adding a file re-profiles the whole dataset over the unioned data (`kind="multi_file"`); a join creates a new dataset (`kind="joined"`) profiled over the joined result.
- A dataset's profile history is retained (new `DatasetProfile` rows, not overwrites) so the audit trail can show the schema as of any given query.

## Success Criteria

- [ ] Uploading a valid CSV returns a profile whose `row_count`, `column_count`, and per-column `missing_count` exactly match values independently computed from the same file with pandas.
- [ ] Uploading an unsupported file type or a file over `AGENT_MAX_UPLOAD_MB` returns a `400` with a human-readable message, and no `Dataset` row is created.
- [ ] (Phase 2) Adding a second file to a dataset updates `row_count` to the sum of both files' rows, and a subsequent aggregate question answers using both files' data (verified against a fixture large enough that a sampled answer would differ from the full-data answer).
