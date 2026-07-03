"""Entry point for running one turn of the analysis graph and persisting the
audit trail (spec/agent.md -> "finalize" node notes: the actual QueryRun /
ChatMessage DB writes happen here, after `agentic_ai.invoke()` returns).
"""
from __future__ import annotations

import time
from typing import Any

from config.settings import get_settings
from db.models import ChatMessage, DatasetProfile, QueryRun
from db.session import create_db_session
from graph.agent import agentic_ai
from graph.state import AgentState
from observability.events import get_logger

_logger = get_logger("graph.runner")


def _build_schema_context(session, dataset_id: str) -> dict[str, Any]:
    """Builds `schema_context` from the dataset's most recent DatasetProfile.

    NEVER reads the raw dataset file here — only the persisted column/stat
    summary (spec/architecture.md -> Raw-Row Privacy Boundary).
    """
    profile = (
        session.query(DatasetProfile)
        .filter(DatasetProfile.dataset_id == dataset_id)
        .order_by(DatasetProfile.generated_at.desc())
        .first()
    )
    if profile is None:
        return {"row_count": 0, "column_count": 0, "columns": []}
    return {
        "row_count": profile.row_count,
        "column_count": profile.column_count,
        "columns": profile.columns_json,
    }


def _build_history_context(session, conversation_id: str, limit: int) -> list[dict]:
    """Most-recent-first prior chat turns, capped to `limit` (settings.agent_history_turns)."""
    messages = (
        session.query(ChatMessage)
        .filter(ChatMessage.conversation_id == conversation_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(limit)
        .all()
    )
    return [{"role": m.role, "content": m.content} for m in messages]


def run_agent(dataset_id: str, conversation_id: str, question: str) -> str:
    """Runs one turn of the analysis graph for `question` against `dataset_id`
    within `conversation_id`, persists the `QueryRun` audit row and the
    resulting assistant `ChatMessage`, and returns the created `QueryRun.id`.
    """
    settings = get_settings()

    with create_db_session() as session:
        schema_context = _build_schema_context(session, dataset_id)
        history_context = _build_history_context(
            session, conversation_id, settings.agent_history_turns
        )

        run = QueryRun(
            conversation_id=conversation_id,
            dataset_id=dataset_id,
            question_text=question,
            execution_status="pending",
        )
        session.add(run)
        session.flush()
        run_id = run.id

    initial_state: AgentState = {
        "run_id": run_id,
        "conversation_id": conversation_id,
        "dataset_id": dataset_id,
        "question": question,
        "schema_context": schema_context,
        "history_context": history_context,
        "step_count": 0,
        "max_steps": settings.max_steps,
        "clarity_checked": False,
        "needs_clarification": False,
        "clarification_question": None,
        "generated_code": None,
        "execution_result": None,
        "execution_error": None,
        "answer_text": None,
        "key_numbers": None,
        "follow_up_suggestions": [],
        "anomalies": [],
        "result_table": None,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "estimated_cost_usd": 0.0,
        "status": None,
        "error": None,
    }

    start = time.monotonic()
    final_state: AgentState = agentic_ai.invoke(initial_state)
    latency_ms = int((time.monotonic() - start) * 1000)

    prompt_tokens = final_state.get("prompt_tokens", 0) or 0
    completion_tokens = final_state.get("completion_tokens", 0) or 0
    estimated_cost_usd = (
        prompt_tokens / 1_000_000 * settings.gemini_input_price_per_1m
        + completion_tokens / 1_000_000 * settings.gemini_output_price_per_1m
    )

    status = final_state.get("status") or "failed"
    answer_text = final_state.get("answer_text")

    _logger.info(
        "run_complete",
        trace_id=run_id,
        node="finalize",
        status=status,
        latency_ms=latency_ms,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )

    with create_db_session() as session:
        run = session.get(QueryRun, run_id)
        run.generated_code = final_state.get("generated_code")
        run.step_count = final_state.get("step_count") or 1
        run.execution_status = status
        run.result_summary_json = final_state.get("execution_result")
        run.key_numbers_json = final_state.get("key_numbers")
        run.answer_text = answer_text
        run.clarification_question = final_state.get("clarification_question")
        run.follow_up_suggestions_json = final_state.get("follow_up_suggestions") or []
        run.anomalies_json = final_state.get("anomalies") or []
        run.result_table_json = final_state.get("result_table")
        run.prompt_tokens = prompt_tokens
        run.completion_tokens = completion_tokens
        run.estimated_cost_usd = estimated_cost_usd
        run.latency_ms = latency_ms
        run.error_message = final_state.get("error")

        if answer_text:
            session.add(
                ChatMessage(
                    conversation_id=conversation_id,
                    role="assistant",
                    content=answer_text,
                    query_run_id=run_id,
                )
            )

    return run_id
