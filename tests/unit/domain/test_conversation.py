"""Pydantic domain model tests for Conversation/ChatMessage/QueryRun shapes (spec/api.md)."""
import pytest
from pydantic import ValidationError

from domain.conversation import (
    AskQuestionRequest,
    AskQuestionResponse,
    ChatMessageResponse,
    ConversationHistoryResponse,
    ConversationResponse,
    QueryRunResponse,
)


def test_ask_question_request_requires_question():
    with pytest.raises(ValidationError):
        AskQuestionRequest()


def test_ask_question_request_happy_path():
    req = AskQuestionRequest(question="What's the average order amount?")
    assert req.question == "What's the average order amount?"


def test_query_run_response_matches_api_shape():
    qr = QueryRunResponse(
        id="uuid",
        execution_status="success",
        generated_code="result = df['amount'].mean()",
        answer_text="The average order amount is $88.40.",
        key_numbers={"average_amount": 88.4},
        follow_up_suggestions=[],
        anomalies=[],
        step_count=1,
        prompt_tokens=812,
        completion_tokens=96,
        estimated_cost_usd=0.0016,
        estimated_cost_inr=0.1408,
        latency_ms=4210,
    )
    assert qr.execution_status == "success"
    assert qr.key_numbers["average_amount"] == 88.4
    assert qr.estimated_cost_inr == 0.1408


def test_query_run_response_failure_status_allows_null_code_and_answer():
    """Edge case: a failed run before code generation has no code/answer yet."""
    qr = QueryRunResponse(
        id="uuid",
        execution_status="failed",
        generated_code=None,
        answer_text=None,
        step_count=1,
        prompt_tokens=0,
        completion_tokens=0,
        estimated_cost_usd=0.0,
        estimated_cost_inr=0.0,
        latency_ms=100,
    )
    assert qr.generated_code is None
    assert qr.follow_up_suggestions == []
    assert qr.anomalies == []


def test_ask_question_response_full_envelope():
    payload = {
        "message": {
            "id": "uuid",
            "role": "assistant",
            "content": "The average order amount is $88.40.",
            "created_at": "2026-07-03T00:00:00Z",
        },
        "query_run": {
            "id": "uuid",
            "execution_status": "success",
            "generated_code": "result = df['amount'].mean()",
            "answer_text": "The average order amount is $88.40.",
            "key_numbers": {"average_amount": 88.4},
            "follow_up_suggestions": [],
            "anomalies": [],
            "step_count": 1,
            "prompt_tokens": 812,
            "completion_tokens": 96,
            "estimated_cost_usd": 0.0016,
            "estimated_cost_inr": 0.1408,
            "latency_ms": 4210,
        },
        "usd_to_inr_rate": 88.0,
    }
    result = AskQuestionResponse.model_validate(payload)
    assert result.message.role == "assistant"
    assert result.query_run.execution_status == "success"
    assert result.usd_to_inr_rate == 88.0
    assert result.query_run.estimated_cost_inr == 0.1408


def test_conversation_history_response_full_envelope_matches_api_shape():
    payload = {
        "conversation": {"id": "uuid", "dataset_id": "uuid", "title": "Untitled analysis"},
        "messages": [
            {
                "id": "uuid1",
                "role": "user",
                "content": "What's the average order amount?",
                "created_at": "2026-07-03T00:00:00Z",
            },
            {
                "id": "uuid2",
                "role": "assistant",
                "content": "The average order amount is $88.40.",
                "query_run_id": "uuid3",
                "created_at": "2026-07-03T00:00:01Z",
            },
        ],
        "session_cost_total_usd": 0.0016,
        "session_cost_total_inr": 0.1408,
        "session_tokens_total": 908,
        "usd_to_inr_rate": 88.0,
    }
    result = ConversationHistoryResponse.model_validate(payload)
    assert result.conversation.created_at is None
    assert len(result.messages) == 2
    assert result.messages[0].query_run_id is None
    assert result.messages[1].query_run_id == "uuid3"
    assert result.session_tokens_total == 908
    assert result.session_cost_total_inr == 0.1408
    assert result.usd_to_inr_rate == 88.0


def test_conversation_history_response_empty_conversation_no_messages():
    """Edge case: a brand-new conversation with no turns yet."""
    payload = {
        "conversation": {"id": "uuid", "dataset_id": "uuid", "title": "Untitled analysis"},
        "messages": [],
        "session_cost_total_usd": 0.0,
        "session_cost_total_inr": 0.0,
        "session_tokens_total": 0,
        "usd_to_inr_rate": 88.0,
    }
    result = ConversationHistoryResponse.model_validate(payload)
    assert result.messages == []


def test_chat_message_response_missing_role_rejected():
    with pytest.raises(ValidationError):
        ChatMessageResponse(id="uuid", content="hi", created_at="2026-07-03T00:00:00Z")
