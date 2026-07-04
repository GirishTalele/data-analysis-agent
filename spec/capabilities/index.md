# Capabilities Index

---

## Capabilities in This Project

| Capability | Phase | File |
|-----------|-------|------|
| File Ingestion & Column Validation | 1 | [file-ingestion-validation.md](file-ingestion-validation.md) |
| GR Aggregation & Chart/Table Generation | 1 | [gr-aggregation-reporting.md](gr-aggregation-reporting.md) |
| HTML Email Composition & SMTP Delivery | 1 | [email-composition-delivery.md](email-composition-delivery.md) |
| Error Surfacing in the Web UI | 1 | [error-surfacing.md](error-surfacing.md) |
| Per-Recipient Plant Scoping | 2 | [recipient-plant-scoping.md](recipient-plant-scoping.md) |

## How to Add a New Capability

Run `/zero-shot-build [description]` on the existing spec. The spec-writer sub-agent will:
1. Create a new file in this directory (`<name>.md`, no number prefix)
2. Update this index
3. Flag any dependencies on existing capabilities
4. Self-review that it fits the architecture and data model before returning

## Capability File Template

Each capability file should answer:
- **What it does** (one sentence)
- **Inputs** (what data it receives)
- **Outputs** (what it produces)
- **External calls** (APIs, LLMs, databases it touches)
- **Error cases** (what can go wrong and how it's handled)
- **Success criteria** (how we test it)
