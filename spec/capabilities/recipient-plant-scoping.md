# Capability: Per-Recipient Plant Scoping

> **Phase 2.** Not built in Phase 1 — see `spec/roadmap.md`.

## What It Does

Restricts each recipient's report to only the GR data for their configured plant(s), per a maintained email→plant(s) config file; a recipient with no configured scope still receives the unrestricted full report exactly as in Phase 1.

## Inputs

| Input | Type | Source | Required |
|-------|------|--------|----------|
| Recipient list (already parsed/validated) | `list[str]` | HTML Email Composition capability's recipient-parsing step | yes |
| Scope config file | JSON on disk, path `AGENT_RECIPIENT_SCOPES_PATH` (default `config/recipient_scopes.json`) | Local filesystem | no (absence is a valid, degraded state) |
| `LoadedDataset` + `ColumnMapping` | domain models | File Ingestion & Column Validation capability | yes |

## Outputs

| Output | Type | Destination |
|--------|------|-------------|
| One `ReportBundle` per distinct scope group | domain model | HTML Email Composition & SMTP Delivery capability, called once per group |
| Scope-group → recipients mapping | `dict[tuple[str, ...], list[str]]` | API response field `scoped_recipients` (see `spec/api.md`) |

## External Calls

| System | Operation | On Failure |
|--------|-----------|------------|
| Local filesystem | Read + parse the scope config JSON | Non-fatal — missing or unparsable file degrades to "everyone unscoped" (full report to all, identical to Phase 1 behavior) plus a surfaced UI warning; the run is never blocked by this |

## Business Rules

- Scope key = the sorted tuple of a recipient's configured plant codes, or the sentinel `"FULL"` for an unscoped recipient (absent from the config file, or the file itself is missing/unparsable).
- Recipients sharing an identical scope key receive **one shared email** (all in the `To` field) containing a `ReportBundle` filtered to exactly their plant(s); this is a change from Phase 1's single-email-to-everyone behavior.
- Filtering: the aggregation capability's plant/buyer group-bys run against `LoadedDataset.dataframe` **after** it has been filtered to rows whose Plant value is in the scope's plant list; unscoped groups use the unfiltered dataset (Phase 1 behavior, unchanged).
- A configured plant code that does not appear in the current file's Plant column produces a valid but empty-of-that-plant `ReportBundle` plus a warning: `"No GR rows found for configured plant {code} in this file."` — this does not block the recipient's send.
- All existing Phase 1 fatal/partial rules (`spec/architecture.md`) still apply per scope group — e.g. if a scoped group's filtered data has no Buyer column detectable, that group's email gets warning P2 exactly as an unscoped run would.
- Config file keys are matched case-insensitively against entered recipient addresses (both lower-cased before comparison).

## Success Criteria

- [ ] A recipient configured with a single plant code receives an email whose plant chart, plant table, and buyer chart contain **only** rows for that plant — no other plant's figures appear anywhere in their email.
- [ ] A recipient configured with multiple plant codes receives the union of those plants' data, and no others.
- [ ] A recipient absent from the config file receives the full, unrestricted report — identical in content to the Phase 1 behavior.
- [ ] Two recipients sharing the same scope receive one shared email (single SMTP send, both in `To`), not two separate sends with identical content.
- [ ] A missing or malformed scope config file does not fail the run — every recipient falls back to the full report, and a warning is present in the API response.
- [ ] A configured plant code with zero matching rows in the current file produces a valid (not fatal) empty-for-that-plant report plus the documented warning text.
