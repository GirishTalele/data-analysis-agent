# Capability: Multi-File Join & Export (Phase 2)

## What It Does

Lets the user treat multiple related files (e.g. 12 monthly CSVs) as one dataset, join two existing datasets together, and export a cleaned/derived dataset produced by a prior analysis turn as a downloadable file.

## Inputs

| Input | Type | Source | Required |
|-------|------|--------|----------|
| Additional file | `.csv`/`.xlsx`/`.xls` | `POST /datasets/{id}/files` | yes (for multi-file) |
| Join spec | `{dataset_ids, join_on, how}` | `POST /datasets/join` | yes (for join) |
| Export request | `{query_run_id, name}` | `POST /datasets/{id}/export` | yes (for export) |

## Outputs

| Output | Type | Destination |
|--------|------|-------------|
| Updated `Dataset`/`DatasetProfile` (multi-file) | JSON | `dataset_files`, new `dataset_profiles` row |
| New joined `Dataset` | JSON | `datasets` (`kind="joined"`), `dataset_files`, `dataset_profiles` |
| `DerivedDataset` + downloadable file | JSON + file | `derived_datasets` row + `data/datasets/<id>/derived/<derived_id>.csv` |

## External Calls

| System | Operation | On Failure |
|--------|-----------|------------|
| Local filesystem | Read all files backing a dataset, write derived exports | 400 with a human message if a file is missing/unreadable; export failure leaves no partial `DerivedDataset` row |
| pandas | Union multiple files, join two datasets on a key, re-profile | 400 if the join key is absent from either dataset; the resulting error names the missing column |

## Business Rules

- Adding a file to a dataset re-profiles over the full unioned data — the profile's `row_count` reflects every file, and subsequent questions answer from the full union, not a sample of the first file uploaded.
- A join requires the join key to exist (by name) in every input dataset; mismatched schemas fail loudly with a named column, not a silent partial join.
- Export only ever writes a **new** file under `derived/` — the original uploaded file(s) are never modified or overwritten.
- Exported files are produced by re-running the `generated_code` recorded on the referenced `QueryRun` (or an explicit cleaning transform), never by hand-editing outside the audited code path.

## Success Criteria

- [ ] Given 3 monthly CSVs with a combined row count > 5,000, an aggregate question (e.g. total across all months) answers with the value computed over all 3 files — verified against a precomputed full-data total, not a per-file or sampled total.
- [ ] Joining two datasets on a shared key returns a profile whose row count matches an independently computed join (e.g. via a reference pandas `merge()` in the test) for the same `how`.
- [ ] Joining on a key absent from one dataset returns a `400` naming the missing column, with no `Dataset` row created.
- [ ] Exporting from a successful `QueryRun` produces a downloadable CSV whose row count and a sampled set of values match independently re-running the same code against the source file(s).
