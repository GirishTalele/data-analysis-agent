"""Audit-trail endpoints (spec/api.md -> GET /query-runs, GET /cost-summary).

Read-only views over the `QueryRun` audit trail (spec/data.md#QueryRun):
a paginated, filterable list of every question ever asked, and running
cost/token totals for the dashboard.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from api._common import api_error, ok
from db.models import QueryRun
from db.session import get_session
from domain.query_run import (
    CostSummaryResponse,
    QueryRunAuditResponse,
    QueryRunListResponse,
)

router = APIRouter()


def _to_utc(dt: datetime) -> datetime:
    """Normalize to UTC so the bind param's wall-clock matches the naive-UTC
    wall-clock SQLite stores for our tz-aware `created_at` values."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_boundary(value: str) -> tuple[datetime, bool]:
    """Parse an ISO date or datetime. Returns (datetime, is_date_only)."""
    try:
        d = date.fromisoformat(value)
        return datetime(d.year, d.month, d.day), True
    except ValueError:
        return datetime.fromisoformat(value), False


def _serialize(run: QueryRun) -> QueryRunAuditResponse:
    # `result_table_json` is added by a sibling slice; default to None so this
    # serialization works even if that column lands slightly after this code.
    result_table = getattr(run, "result_table_json", None)
    return QueryRunAuditResponse(
        id=run.id,
        execution_status=run.execution_status,
        generated_code=run.generated_code,
        answer_text=run.answer_text,
        key_numbers=run.key_numbers_json,
        result_table=result_table,
        follow_up_suggestions=run.follow_up_suggestions_json or [],
        anomalies=run.anomalies_json or [],
        step_count=run.step_count,
        prompt_tokens=run.prompt_tokens,
        completion_tokens=run.completion_tokens,
        estimated_cost_usd=run.estimated_cost_usd,
        latency_ms=run.latency_ms,
        question_text=run.question_text,
        created_at=run.created_at,
    )


@router.get("/query-runs")
def list_query_runs(
    dataset_id: str | None = None,
    conversation_id: str | None = None,
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = None,
    execution_status: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> dict:
    query = session.query(QueryRun)

    if dataset_id is not None:
        query = query.filter(QueryRun.dataset_id == dataset_id)
    if conversation_id is not None:
        query = query.filter(QueryRun.conversation_id == conversation_id)
    if execution_status is not None:
        query = query.filter(QueryRun.execution_status == execution_status)

    if from_ is not None:
        try:
            start, _ = _parse_boundary(from_)
        except ValueError:
            raise api_error("BAD_REQUEST", f"Invalid 'from' value: {from_!r}", 400)
        query = query.filter(QueryRun.created_at >= _to_utc(start))

    if to is not None:
        try:
            end, is_date_only = _parse_boundary(to)
        except ValueError:
            raise api_error("BAD_REQUEST", f"Invalid 'to' value: {to!r}", 400)
        if is_date_only:
            # Date-only upper bound is inclusive of the whole day.
            query = query.filter(QueryRun.created_at < _to_utc(end + timedelta(days=1)))
        else:
            query = query.filter(QueryRun.created_at <= _to_utc(end))

    total = query.count()
    runs = (
        query.order_by(QueryRun.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return ok(
        QueryRunListResponse(
            query_runs=[_serialize(r) for r in runs],
            limit=limit,
            offset=offset,
            total=total,
        ).model_dump(mode="json")
    )


@router.get("/cost-summary")
def cost_summary(
    scope: str = Query(default="all"),
    conversation_id: str | None = None,
    session: Session = Depends(get_session),
) -> dict:
    if scope not in ("session", "day", "all"):
        raise api_error(
            "BAD_REQUEST",
            "scope must be one of 'session', 'day', 'all'",
            400,
        )

    query = session.query(QueryRun)
    result_date: str | None = None

    if scope == "session":
        if not conversation_id:
            raise api_error(
                "BAD_REQUEST",
                "scope='session' requires a conversation_id",
                400,
            )
        query = query.filter(QueryRun.conversation_id == conversation_id)
    elif scope == "day":
        local_now = datetime.now().astimezone()
        today = local_now.date()
        start = datetime.combine(today, time.min, tzinfo=local_now.tzinfo)
        end = start + timedelta(days=1)
        query = query.filter(
            QueryRun.created_at >= _to_utc(start),
            QueryRun.created_at < _to_utc(end),
        )
        result_date = today.isoformat()

    total_tokens, total_cost, query_count = query.with_entities(
        func.coalesce(func.sum(QueryRun.prompt_tokens + QueryRun.completion_tokens), 0),
        func.coalesce(func.sum(QueryRun.estimated_cost_usd), 0.0),
        func.count(QueryRun.id),
    ).one()

    return ok(
        CostSummaryResponse(
            scope=scope,
            date=result_date,
            total_tokens=int(total_tokens),
            total_cost_usd=round(float(total_cost), 6),
            query_count=int(query_count),
        ).model_dump()
    )
