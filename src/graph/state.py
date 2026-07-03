from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    """Full graph state per spec/agent.md -> "Agent State"."""

    # Identity
    run_id: str
    conversation_id: str
    dataset_id: str

    # Input
    question: str
    schema_context: dict                 # columns/dtypes/stats from DatasetProfile — NEVER raw rows
    history_context: list[dict]          # prior {role, content} turns, most-recent-first, capped

    # Control (iteration)
    step_count: int
    max_steps: int

    # Clarification branch [P2 activates]
    clarity_checked: bool
    needs_clarification: bool
    clarification_question: str | None

    # Code-gen / execution
    generated_code: str | None
    execution_result: Any | None         # summarized (never raw-row) result
    execution_error: str | None

    # Answer
    answer_text: str | None
    key_numbers: dict | None
    follow_up_suggestions: list[str]     # [P2 activates] always [] in Phase 1
    anomalies: list[str]                 # [P2 activates] always [] in Phase 1
    result_table: dict | None            # [P2 activates] {"columns":[...],"rows":[...]}; None for scalar answers

    # Cost / audit
    prompt_tokens: int
    completion_tokens: int
    estimated_cost_usd: float

    # Terminal status
    status: str | None
    error: str | None
