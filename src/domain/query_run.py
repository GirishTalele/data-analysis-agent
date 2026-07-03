"""Response models for the audit-trail endpoints
(spec/api.md -> GET /query-runs, GET /cost-summary).

These are read-only views over the `QueryRun` entity (spec/data.md#QueryRun).
The list item mirrors the `query_run` object returned by
`POST /conversations/{id}/messages`, plus the audit-only fields
`question_text` and `created_at` and the Phase-2 `result_table`.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class QueryRunAuditResponse(BaseModel):
    """One record in the `GET /query-runs` paginated list (spec/api.md)."""

    id: str
    execution_status: str
    generated_code: str | None = None
    answer_text: str | None = None
    key_numbers: dict | None = None
    result_table: dict | None = None
    follow_up_suggestions: list[str] = []
    anomalies: list[str] = []
    step_count: int
    prompt_tokens: int
    completion_tokens: int
    estimated_cost_usd: float
    # Display-derived (estimated_cost_usd * usd_to_inr_rate); not stored, no migration.
    estimated_cost_inr: float
    latency_ms: int
    question_text: str
    created_at: datetime


class QueryRunListResponse(BaseModel):
    """`GET /query-runs` response data — paginated audit trail (spec/api.md)."""

    query_runs: list[QueryRunAuditResponse]
    limit: int
    offset: int
    total: int
    # Echoes the configured AGENT_USD_TO_INR — one source of truth for both currencies.
    usd_to_inr_rate: float


class CostSummaryResponse(BaseModel):
    """`GET /cost-summary` response data (spec/api.md)."""

    scope: str
    date: str | None = None
    total_tokens: int
    total_cost_usd: float
    # Display-derived (total_cost_usd * usd_to_inr_rate); not stored, no migration.
    total_cost_inr: float
    usd_to_inr_rate: float
    query_count: int
