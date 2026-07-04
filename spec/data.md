# Data Model

---

## Storage Technology

**None.** This agent has no database and no persistence layer of any kind (confirmed twice by the user — no run history, no audit log). Every entity below is a transient, in-memory Python/Pydantic object that exists only for the duration of a single `POST /reports/send` HTTP request and is garbage-collected once the response is returned. Nothing is written to disk except a short-lived temporary file used solely to hand a `.qvd` upload's bytes to the `pyqvd` reader (deleted before the request returns — see `spec/architecture.md → pyqvd Integration`).

---

## Input File Schema (QVD/CSV)

The uploaded file is expected to contain one row per GR (Goods Receipt) transaction line item, with at least a GR Value column and, ideally, Plant and Buyer columns and a date/period column. Column names in real exports vary, so detection is by **normalized alias matching**, not a single fixed header string.

### Normalization rule

Before matching, every header cell is normalized identically:

```
normalize(h) = h.strip().lower().replace("_", " ").replace("-", " ")
               → collapse repeated internal whitespace to a single space
```

`"Plant_Code"`, `"plant code"`, `"PLANT   CODE"`, and `"Plant-Code"` all normalize to `"plant code"` and match the same alias.

### Column aliases

| Canonical field | Required for | Recognized header aliases (normalized) |
|---|---|---|
| **Plant** | Plant-wise chart + plant table | `plant`, `plant code`, `plantcode`, `location code`, `location`, `site` |
| **Buyer** | Top-10 Buyer chart | `buyer`, `buyer name`, `customer`, `customer name`, `sold to party`, `soldtoparty` |
| **GR Value** | All three outputs | `gr value`, `grvalue`, `gr amount`, `value`, `amount`, `net value`, `gr value (inr)`, `goods receipt value` |
| **Period date** | The reporting-period line in the email | `gr date`, `posting date`, `document date`, `period`, `date` |

**Matching algorithm:** for each canonical field, scan the file's header cells left to right; the **first** column whose normalized name equals one of that field's aliases is selected. If no column matches, that field is `None` (missing) — this drives the fatal/partial rules in `spec/architecture.md → Error Handling & Reliability Model`. Matching is **exact-after-normalization only** — no fuzzy/typo tolerance, so the mapping is deterministic and testable.

### GR Value numeric coercion

Raw cell values may include currency symbols or thousands separators (e.g. `"₹1,23,456.00"`). Coercion:

```python
cleaned = df[gr_value_col].astype(str).str.replace(",", "").str.replace("₹", "").str.strip()
numeric = pandas.to_numeric(cleaned, errors="coerce")
```

Rows where `numeric` is `NaN` are **excluded** from every aggregation and counted as `excluded_row_count` (drives warning P4). If `numeric` is `NaN` for every row, this is fatal (F4) — see `spec/architecture.md`.

### Period derivation

```python
parsed = pandas.to_datetime(df[period_col], errors="coerce", dayfirst=True)
parsed = parsed.dropna()
```

- If `period_col` is `None`, or `parsed` is empty after dropping unparsable values → period is unavailable (drives warning P3); the email/UI show `"Reporting period could not be determined"`.
- Otherwise: `min_date, max_date = parsed.min(), parsed.max()`.
  - If `min_date.year == max_date.year and min_date.month == max_date.month` → label = `f"{min_date:%b %Y}"` (e.g. `"Jun 2026"`).
  - Else → label = `f"{min_date:%b %Y} – {max_date:%b %Y}"` (e.g. `"Jan 2026 – Jun 2026"`) — this is the case a QVD spanning several months produces.

### ₹-Crores conversion

```
value_in_crores = raw_value / 1e7          # 1 Crore = 10,000,000
```

Display format: `f"₹{value_in_crores:,.2f} Cr"` (2 decimals, thousands separator on the crore figure itself if ≥ 1,000). Applied only at the final display/formatting step — every intermediate sum, and every "N rows excluded" count, refers to raw-currency values/rows, never converted ones, to avoid ever converting a value twice.

### Aggregation formulas

```python
plant_totals_raw   = df.groupby(plant_col)[gr_value_col].sum()                        # after NaN-row exclusion
plant_totals_crore = plant_totals_raw / 1e7                                            # sorted descending for chart + table

buyer_totals_raw   = df.groupby(buyer_col)[gr_value_col].sum().sort_values(ascending=False).head(10)
buyer_totals_crore = buyer_totals_raw / 1e7                                            # exactly the top 10, descending
```

---

## Entities (transient, in-memory only — no table exists for any of these)

### `LoadedDataset`

The parsed, in-memory representation of the uploaded file.

| Field | Type | Required | Description |
|-------|------|----------|--------------|
| dataframe | `pandas.DataFrame` | yes | One row per GR line item, raw column names preserved |
| source_filename | `str` | yes | Original uploaded filename, shown in the email/UI |
| row_count | `int` | yes | Total rows before any exclusion, used in the P4 warning text |

### `ColumnMapping`

The result of alias detection against `LoadedDataset`.

| Field | Type | Required | Description |
|-------|------|----------|--------------|
| plant_column | `str \| None` | no | Detected header name for Plant, or `None` |
| buyer_column | `str \| None` | no | Detected header name for Buyer, or `None` |
| gr_value_column | `str \| None` | no | Detected header name for GR Value, or `None` (its absence is fatal — see architecture.md) |
| period_column | `str \| None` | no | Detected header name for the period-governing date, or `None` |

### `ReportBundle`

The fully-computed report, ready for email composition.

| Field | Type | Required | Description |
|-------|------|----------|--------------|
| plant_chart_png | `bytes \| None` | no | PNG bytes of the plant-wise bar chart; `None` if Plant undetectable (P1) |
| plant_table_html | `str \| None` | no | Rendered `<table>` HTML for the plant breakdown; `None` if Plant undetectable (P1) |
| buyer_chart_png | `bytes \| None` | no | PNG bytes of the Top-10-Buyer bar chart; `None` if Buyer undetectable (P2) |
| period_label | `str` | yes | Human-readable period string, or the P3 placeholder |
| excluded_row_count | `int` | yes | Rows dropped by GR Value coercion (0 if none) |
| warnings | `list[str]` | yes | Human-readable P1–P4 warning strings that apply to this run (empty if none) |

### `SendResult`

Returned by the pipeline to the API layer.

| Field | Type | Required | Description |
|-------|------|----------|--------------|
| status | `"sent"` | yes | Always `"sent"` on this type — fatal outcomes raise a typed exception instead of returning a `SendResult` (see architecture.md's fatal/partial split) |
| source_filename | `str` | yes | Echoed from `LoadedDataset` |
| period | `str` | yes | Echoed from `ReportBundle.period_label` |
| recipients_sent | `list[str]` | yes | Addresses the email was actually sent to |
| recipients_rejected | `list[str]` | yes | Entered addresses that failed `EmailStr` validation (P5); empty if none |
| warnings | `list[str]` | yes | Echoed from `ReportBundle.warnings` |

### `RecipientScope` (Phase 2 only)

One entry per configured recipient in the scope config file.

| Field | Type | Required | Description |
|-------|------|----------|--------------|
| email | `str` | yes | Lower-cased email address, the config key |
| plants | `list[str]` | yes | Plant codes this recipient is scoped to; a recipient absent from the config file entirely is unscoped (gets the full report) |

Config file format (path from `AGENT_RECIPIENT_SCOPES_PATH`, default `config/recipient_scopes.json`):

```json
{
  "plant.head@company.com": ["1010"],
  "regional.manager@company.com": ["1010", "1020"]
}
```

Any email not present as a key is unscoped. A missing or unparsable config file degrades to "everyone unscoped" (full report to all — same as Phase 1 behavior) plus a UI warning; it never blocks the run.

### Relationships

- A GR line item (one DataFrame row) belongs to exactly one Plant and, if the Buyer column is present, exactly one Buyer.
- `LoadedDataset` → `ColumnMapping` → `ReportBundle` → `SendResult` is a strict one-way pipeline; no entity is ever re-read or mutated after the next stage consumes it.
- (Phase 2) `RecipientScope` entries partition the entered recipient list into scope groups; each distinct scope (including "unscoped/full") gets its own `ReportBundle` computed by filtering `LoadedDataset` to that scope's plants before aggregation, and its own `SendResult`.

## Data Lifecycle

Created when `POST /reports/send` begins, fully discarded (garbage collected, no persistence) when the response is returned — success or failure. Nothing is cached or reused between runs; a re-upload of the same file re-parses and re-aggregates from scratch.

## Sensitive Data

- **GR Value figures** are commercially sensitive financial data. They exist only in server memory for one request and are transmitted only over TLS-secured SMTP (`AGENT_SMTP_USE_TLS=true`). Never written to disk, never logged.
- **Recipient email addresses** are entered fresh per run and never persisted. Structured logs record only the **count** of recipients (`recipient_count`), never the addresses themselves (see `spec/architecture.md → Observability`).
- **SMTP credentials** (`AGENT_SMTP_USERNAME`, `AGENT_SMTP_PASSWORD`) are read from `.env` only, confirmed present by boolean check, never logged or echoed.
