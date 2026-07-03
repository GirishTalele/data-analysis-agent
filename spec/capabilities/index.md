# Capabilities Index

---

## What Is a Capability?

A capability is a single, discrete action or behavior the agent performs.

## Capabilities in This Project

| Capability | File | Phase(s) |
|-----------|------|----------|
| Dataset Ingestion & Profiling | [dataset-ingestion-profiling.md](dataset-ingestion-profiling.md) | 1 (single file), 2 (multi-file/folder) |
| Conversational Code-Gen Analysis | [conversational-code-analysis.md](conversational-code-analysis.md) | 1 (single-pass), 2 (full iterative loop + follow-ups/anomalies) |
| Multi-File Join & Export | [multi-file-join-and-export.md](multi-file-join-and-export.md) | 2 |
| Cost & Audit Trail | [cost-and-audit-trail.md](cost-and-audit-trail.md) | 1 (per-query + session total + storage), 2 (dashboard + rollups) |

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
- **Business rules**
- **Success criteria** (how we test it)
