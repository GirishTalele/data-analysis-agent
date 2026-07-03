"""`/datasets/{id}/conversations` and `/conversations/{id}/messages` endpoints
(spec/api.md -> POST /datasets/{dataset_id}/conversations,
POST /conversations/{conversation_id}/messages,
GET /conversations/{conversation_id}/messages).
"""
from __future__ import annotations

import threading

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from api._common import api_error, ok
from config.settings import get_settings
from db.models import ChatMessage, Conversation, Dataset, DatasetProfile, QueryRun
from db.session import get_session
from domain.conversation import (
    AskQuestionRequest,
    AskQuestionResponse,
    ChatMessageResponse,
    ConversationHistoryResponse,
    ConversationResponse,
    QueryRunResponse,
)
from graph.runner import run_agent

router = APIRouter()

# INR is display-derived from the canonical USD value (spec/capabilities/
# cost-and-audit-trail.md). Round to 4 decimals so small USD costs still show a
# nonzero INR rather than truncating to 0.00.
_INR_DECIMALS = 4


def _to_inr(usd: float, rate: float) -> float:
    return round((usd or 0.0) * rate, _INR_DECIMALS)


# Simple in-memory per-conversation lock (spec/agent.md -> Concurrency Model).
# A single local user, synchronous requests — a dict of conversation_id -> bool
# guarded by a module-level lock is sufficient.
_running_lock = threading.Lock()
_running_conversations: set[str] = set()


def _has_ready_profile(session: Session, dataset_id: str) -> bool:
    stmt = select(DatasetProfile).where(DatasetProfile.dataset_id == dataset_id)
    return session.execute(stmt).scalars().first() is not None


@router.post("/datasets/{dataset_id}/conversations")
def create_conversation(dataset_id: str, session: Session = Depends(get_session)) -> dict:
    dataset = session.get(Dataset, dataset_id)
    if dataset is None:
        raise api_error("NOT_FOUND", f"Dataset '{dataset_id}' not found", 404)

    conversation = Conversation(dataset_id=dataset_id, title="Untitled analysis")
    session.add(conversation)
    session.flush()
    session.refresh(conversation)

    return ok(
        ConversationResponse(
            id=conversation.id,
            dataset_id=conversation.dataset_id,
            title=conversation.title,
            created_at=conversation.created_at,
        ).model_dump()
    )


@router.post("/conversations/{conversation_id}/messages")
def post_message(
    conversation_id: str,
    req: AskQuestionRequest,
    session: Session = Depends(get_session),
) -> dict:
    conversation = session.get(Conversation, conversation_id)
    if conversation is None:
        raise api_error("NOT_FOUND", f"Conversation '{conversation_id}' not found", 404)

    question = req.question.strip()
    if not question:
        raise api_error("BAD_REQUEST", "question must not be empty", 400)

    if not _has_ready_profile(session, conversation.dataset_id):
        raise api_error(
            "BAD_REQUEST",
            f"Dataset '{conversation.dataset_id}' has no ready profile",
            400,
        )

    with _running_lock:
        if conversation_id in _running_conversations:
            raise api_error(
                "CONFLICT",
                f"Another question is already running for conversation '{conversation_id}'",
                409,
            )
        _running_conversations.add(conversation_id)

    try:
        session.add(
            ChatMessage(conversation_id=conversation_id, role="user", content=question)
        )
        if conversation.title == "Untitled analysis":
            conversation.title = question[:120]
        # Commit (not just flush) before calling run_agent, which opens its own
        # DB session/connection — releases our write lock so the two don't
        # contend for SQLite's single-writer lock.
        session.commit()

        dataset_id = conversation.dataset_id
        run_id = run_agent(dataset_id, conversation_id, question)
    finally:
        with _running_lock:
            _running_conversations.discard(conversation_id)

    run = session.get(QueryRun, run_id)
    if run is None:
        raise api_error("INTERNAL_ERROR", "Query run not found after creation", 500)

    assistant_message = (
        session.query(ChatMessage)
        .filter(
            ChatMessage.conversation_id == conversation_id,
            ChatMessage.query_run_id == run_id,
        )
        .order_by(ChatMessage.created_at.desc())
        .first()
    )
    if assistant_message is None:
        raise api_error("INTERNAL_ERROR", "Assistant message not found after run", 500)

    session.refresh(conversation)

    rate = get_settings().usd_to_inr_rate

    return ok(
        AskQuestionResponse(
            message=ChatMessageResponse(
                id=assistant_message.id,
                role=assistant_message.role,
                content=assistant_message.content,
                query_run_id=assistant_message.query_run_id,
                created_at=assistant_message.created_at,
            ),
            query_run=QueryRunResponse(
                id=run.id,
                execution_status=run.execution_status,
                generated_code=run.generated_code,
                answer_text=run.answer_text,
                key_numbers=run.key_numbers_json,
                follow_up_suggestions=run.follow_up_suggestions_json or [],
                anomalies=run.anomalies_json or [],
                result_table=run.result_table_json,
                step_count=run.step_count,
                prompt_tokens=run.prompt_tokens,
                completion_tokens=run.completion_tokens,
                estimated_cost_usd=run.estimated_cost_usd,
                estimated_cost_inr=_to_inr(run.estimated_cost_usd, rate),
                latency_ms=run.latency_ms,
            ),
            usd_to_inr_rate=rate,
        ).model_dump()
    )


@router.get("/conversations/{conversation_id}/messages")
def get_messages(conversation_id: str, session: Session = Depends(get_session)) -> dict:
    conversation = session.get(Conversation, conversation_id)
    if conversation is None:
        raise api_error("NOT_FOUND", f"Conversation '{conversation_id}' not found", 404)

    messages = (
        session.query(ChatMessage)
        .filter(ChatMessage.conversation_id == conversation_id)
        .order_by(ChatMessage.created_at)
        .all()
    )
    runs = (
        session.query(QueryRun)
        .filter(QueryRun.conversation_id == conversation_id)
        .all()
    )

    session_cost_total_usd = sum(r.estimated_cost_usd or 0.0 for r in runs)
    session_tokens_total = sum((r.prompt_tokens or 0) + (r.completion_tokens or 0) for r in runs)
    rate = get_settings().usd_to_inr_rate

    return ok(
        ConversationHistoryResponse(
            conversation=ConversationResponse(
                id=conversation.id,
                dataset_id=conversation.dataset_id,
                title=conversation.title,
            ),
            messages=[
                ChatMessageResponse(
                    id=m.id,
                    role=m.role,
                    content=m.content,
                    query_run_id=m.query_run_id,
                    created_at=m.created_at,
                )
                for m in messages
            ],
            session_cost_total_usd=session_cost_total_usd,
            session_cost_total_inr=_to_inr(session_cost_total_usd, rate),
            session_tokens_total=session_tokens_total,
            usd_to_inr_rate=rate,
        ).model_dump()
    )
