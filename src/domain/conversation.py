from datetime import datetime

from pydantic import BaseModel


class ConversationResponse(BaseModel):
    """`POST /datasets/{dataset_id}/conversations` response (spec/api.md).

    `created_at` is optional because the nested `conversation` object returned by
    `GET /conversations/{id}/messages` omits it (see spec/api.md).
    """

    id: str
    dataset_id: str
    title: str
    created_at: datetime | None = None


class ChatMessageResponse(BaseModel):
    """One entry in `GET /conversations/{id}/messages` -> `messages` (spec/api.md)."""

    id: str
    role: str
    content: str
    query_run_id: str | None = None
    created_at: datetime


class AskQuestionRequest(BaseModel):
    """`POST /conversations/{conversation_id}/messages` request body (spec/api.md)."""

    question: str


class QueryRunResponse(BaseModel):
    """`query_run` object in `POST /conversations/{id}/messages` response (spec/api.md)."""

    id: str
    execution_status: str
    generated_code: str | None = None
    answer_text: str | None = None
    key_numbers: dict | None = None
    follow_up_suggestions: list[str] = []
    anomalies: list[str] = []
    result_table: dict | None = None
    step_count: int
    prompt_tokens: int
    completion_tokens: int
    estimated_cost_usd: float
    latency_ms: int


class AskQuestionResponse(BaseModel):
    """`{message, query_run}` envelope for `POST /conversations/{id}/messages`."""

    message: ChatMessageResponse
    query_run: QueryRunResponse


class ConversationHistoryResponse(BaseModel):
    """`GET /conversations/{conversation_id}/messages` response data (spec/api.md)."""

    conversation: ConversationResponse
    messages: list[ChatMessageResponse]
    session_cost_total_usd: float
    session_tokens_total: int
