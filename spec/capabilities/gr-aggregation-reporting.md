# Capability: GR Aggregation & Chart/Table Generation

## What It Does

Aggregates GR Value by Plant and by Buyer (top 10), converts totals to ₹ Crores, derives the reporting period from the source file's date column, and renders the plant-wise bar chart, the plant breakdown table (real HTML), and the Top-10-Buyer bar chart — computing whichever of these three outputs its inputs allow.

## Inputs

| Input | Type | Source | Required |
|-------|------|--------|----------|
| `LoadedDataset` | domain model | File Ingestion & Column Validation capability | yes |
| `ColumnMapping` | domain model | File Ingestion & Column Validation capability | yes |

## Outputs

| Output | Type | Destination |
|--------|------|-------------|
| `ReportBundle` (see `spec/data.md`) | domain model | HTML Email Composition & SMTP Delivery capability |

## External Calls

None — pure in-process computation. No network calls, no filesystem writes.

## Business Rules

- Aggregation formulas, ₹-Crore conversion, and period-derivation logic are the exact ones specified in `spec/data.md → Aggregation formulas` / `Period derivation` — one fact, one place.
- Plant chart and plant table are sorted descending by ₹-Crore value; the table has a `Total` footer row.
- Buyer chart is **exactly** the top 10 buyers by total GR Value, descending; never more, never fewer (unless fewer than 10 distinct buyers exist in the file, in which case all of them appear).
- If `ColumnMapping.plant_column is None`: `plant_chart_png` and `plant_table_html` are both `None`, and warning P1 is added — the run is **not** aborted.
- If `ColumnMapping.buyer_column is None`: `buyer_chart_png` is `None`, and warning P2 is added — the run is **not** aborted.
- If `ColumnMapping.period_column is None`, or every value in it fails date parsing: `period_label` falls back to the P3 placeholder text — the run is **not** aborted.
- `excluded_row_count` and P4's warning text are populated whenever GR Value coercion dropped at least one (but not all) rows.
- Values are converted to ₹ Crores only at the final formatting step, never in intermediate sums — see `spec/data.md`.

## Success Criteria

- [ ] On a fixture where the correct plant/buyer totals are independently computable, the pipeline's numeric totals (before chart rendering) match a direct `pandas.groupby(...).sum()` recomputation of the same raw file within `1e-6` relative tolerance.
- [ ] On a fixture large enough that a truncated (sampled) read would produce a different #1 plant and #1 buyer than the full file, the pipeline's #1 plant and #1 buyer match the full-data answer, not the sampled one.
- [ ] The buyer chart never shows more than 10 bars and is sorted descending.
- [ ] A file with no detectable Plant column still returns a `ReportBundle` with a populated `buyer_chart_png` and warning P1 present — the run completes, it does not raise.
- [ ] A file with no detectable/parsable period column returns `period_label` equal to the documented P3 placeholder text and warning P3 present.
- [ ] Every returned PNG is a structurally valid PNG (verifiable via `PIL.Image.open` without error) of non-trivial size (not a 1×1 blank image).
