# Capability: File Ingestion & Column Validation

## What It Does

Loads one uploaded QVD or CSV file into a tabular in-memory structure and deterministically detects which of the required GR-report columns (Plant, Buyer, GR Value, reporting-period date) are present, so downstream aggregation knows exactly what it can and cannot compute.

## Inputs

| Input | Type | Source | Required |
|-------|------|--------|----------|
| Uploaded file bytes + filename | `bytes`, `str` | `multipart/form-data` field `file` on `POST /reports/send` | yes |

## Outputs

| Output | Type | Destination |
|--------|------|-------------|
| `LoadedDataset` (see `spec/data.md`) | domain model | GR Aggregation & Chart/Table Generation capability |
| `ColumnMapping` (see `spec/data.md`) | domain model | GR Aggregation & Chart/Table Generation capability |

## External Calls

| System | Operation | On Failure |
|--------|-----------|------------|
| `pyqvd` | Parse `.qvd` bytes into a pandas-compatible table | Fatal — corrupt/unreadable QVD raises `FILE_UNREADABLE` (F2, see `spec/architecture.md`) |

## Business Rules

- Extension check is case-insensitive and limited to `.csv` and `.qvd`; anything else is fatal (`UNSUPPORTED_FILE_TYPE`, F1).
- A file that parses to zero data rows is fatal (`FILE_UNREADABLE`, F2).
- Column detection uses the exact normalized-alias algorithm in `spec/data.md → Input File Schema` — no fuzzy matching, no partial/typo tolerance.
- GR Value column undetectable, or detected but 100% unparsable after numeric coercion, is fatal (F3/F4 in `spec/architecture.md`) — nothing downstream runs.
- Neither Plant nor Buyer detectable is fatal (F5) — there is nothing groupable to report on.
- Plant missing (Buyer + GR Value present), Buyer missing (Plant + GR Value present), or the period column missing/unparsable, are each **partial** conditions (P1/P2/P3) — ingestion still returns a `ColumnMapping` with the relevant field as `None`; it is the aggregation capability's job to degrade the specific output, not ingestion's job to fail the run.
- Rows whose GR Value fails numeric coercion are dropped and counted (`excluded_row_count`), not treated as a parse failure, unless every row fails (see F4).

## Success Criteria

- [ ] A header of `PLANT_CODE`, `Buyer Name`, `GR_Value`, `Posting Date` (mixed case/underscore/spacing) is detected identically to `plant`, `buyer`, `gr value`, `posting date`.
- [ ] A `.csv` and a `.qvd` file containing the same logical data produce an identical `ColumnMapping` and downstream `LoadedDataset.row_count`.
- [ ] A file missing the GR Value column raises the fatal `GR_VALUE_COLUMN_MISSING` error and no further pipeline stage executes.
- [ ] A file missing only the Buyer column returns a `ColumnMapping` with `buyer_column=None` and `plant_column`/`gr_value_column` populated — the run continues (does not fail).
- [ ] Rows with a non-numeric GR Value cell are excluded and counted in `excluded_row_count`, while rows with a valid numeric value are retained.
- [ ] An unsupported extension (e.g. `.xlsx`) is rejected before any parsing is attempted.
