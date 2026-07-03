"""Graph nodes for the conversational code-gen analysis loop (spec/agent.md).

Phase 1: `check_clarity` is a stub (always "clear"), `ask_clarification` is
wired but unreachable, and the `decide_next` loop-back to `generate_code` is
inert because `max_steps=1`. See `spec/agent.md` for the full per-node
contract this module implements.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from graph.state import AgentState
from llm.client import LLMClient
from observability.events import get_logger

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
_GENERATE_CODE_PROMPT_PATH = _PROMPTS_DIR / "generate_code.md"
_COMPOSE_ANSWER_PROMPT_PATH = _PROMPTS_DIR / "compose_answer.md"
_CHECK_CLARITY_PROMPT_PATH = _PROMPTS_DIR / "check_clarity.md"

_logger = get_logger("graph.nodes")


def _load_prompt(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def _extract_code_block(text: str) -> str:
    """Pull the pandas code out of a fenced ```python ...``` block.

    Falls back to the raw text (stripped) if the model didn't fence it.
    """
    match = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()


def _parse_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object out of an LLM response, tolerating markdown fences."""
    cleaned = text.strip()
    fence_match = re.search(r"```(?:json)?\s*\n(.*?)```", cleaned, re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # Last resort: grab the first {...} span.
    brace_match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass
    return {"answer": cleaned, "key_numbers": {}}


def _build_generate_code_user_message(state: AgentState) -> str:
    parts = [
        "## Question",
        state.get("question", ""),
        "",
        "## Schema context (columns/dtypes/stats — NOT raw rows)",
        json.dumps(state.get("schema_context") or {}, indent=2, default=str),
    ]
    history = state.get("history_context") or []
    if history:
        parts += ["", "## Prior conversation turns (most recent first)"]
        for turn in history:
            parts.append(f"- {turn.get('role')}: {turn.get('content')}")
    execution_error = state.get("execution_error")
    if execution_error:
        parts += [
            "",
            "## Your previous attempt failed with this error — fix the code:",
            execution_error,
        ]
    return "\n".join(str(p) for p in parts)


def _build_check_clarity_user_message(state: AgentState) -> str:
    payload = {
        "question": state.get("question", ""),
        "schema_context": state.get("schema_context") or {},
    }
    return json.dumps(payload, indent=2, default=str)


def _sanitize_result_table(raw: Any, max_rows: int) -> dict | None:
    """Validate + cap a model-produced result_table.

    Reuses the raw-row privacy boundary: the table is derived from the
    already-summarized execution result, and here we hard-cap the number of
    rows to `max_rows` (AGENT_MAX_SUMMARY_ROWS) so it can never exceed the
    boundary even if the model over-produces. Returns None for anything that
    isn't a well-formed {"columns": [...], "rows": [[...]]} object.
    """
    if not isinstance(raw, dict):
        return None
    columns = raw.get("columns")
    rows = raw.get("rows")
    if not isinstance(columns, list) or not columns:
        return None
    if not isinstance(rows, list):
        return None
    clean_rows: list[list[Any]] = []
    for row in rows[:max_rows]:
        if isinstance(row, list):
            clean_rows.append(row)
        elif isinstance(row, dict):
            # tolerate a records-shaped row -> project onto columns order
            clean_rows.append([row.get(c) for c in columns])
        else:
            clean_rows.append([row])
    if not clean_rows:
        return None
    return {"columns": [str(c) for c in columns], "rows": clean_rows}


def _build_compose_answer_user_message(state: AgentState) -> str:
    payload = {
        "question": state.get("question", ""),
        "schema_context": state.get("schema_context") or {},
        "execution_result_summary": state.get("execution_result"),
    }
    return json.dumps(payload, indent=2, default=str)


# ---------------------------------------------------------------------------
# check_clarity [P1: stub]
# ---------------------------------------------------------------------------


def check_clarity(state: AgentState) -> AgentState:
    """[P2 active] Real Gemini classification — is the question answerable given
    the schema? If not, set `needs_clarification=True` + a `clarification_question`
    so the graph routes to `ask_clarification`. On an LLM error, set `state["error"]`
    so the graph routes to `handle_error` (never crashes the turn)."""
    try:
        system_prompt = _load_prompt(_CHECK_CLARITY_PROMPT_PATH)
        user_message = _build_check_clarity_user_message(state)
        response = LLMClient().call_model_with_usage(user_message, system=system_prompt)
        parsed = _parse_json_object(response.text)
        # Permissive default: treat as answerable unless the model clearly says no.
        answerable = parsed.get("answerable", True)
        clarification_question = parsed.get("clarification_question")
        needs_clarification = answerable is False and bool(clarification_question)
        _logger.info(
            "check_clarity",
            trace_id=state.get("run_id"),
            node="check_clarity",
            needs_clarification=needs_clarification,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
        )
        return {
            **state,
            "clarity_checked": True,
            "needs_clarification": needs_clarification,
            "clarification_question": clarification_question if needs_clarification else None,
            "prompt_tokens": state.get("prompt_tokens", 0) + response.prompt_tokens,
            "completion_tokens": state.get("completion_tokens", 0) + response.completion_tokens,
        }
    except Exception as exc:  # SDK/network/auth failures -> fatal, route to handle_error
        _logger.error(
            "check_clarity_failed", trace_id=state.get("run_id"), node="check_clarity", error=str(exc)
        )
        return {**state, "clarity_checked": True, "error": f"check_clarity failed: {exc}"}


# ---------------------------------------------------------------------------
# generate_code [P1 active]
# ---------------------------------------------------------------------------


def generate_code(state: AgentState) -> AgentState:
    try:
        system_prompt = _load_prompt(_GENERATE_CODE_PROMPT_PATH)
        user_message = _build_generate_code_user_message(state)
        response = LLMClient().call_model_with_usage(user_message, system=system_prompt)
        code = _extract_code_block(response.text)
        _logger.info(
            "generate_code",
            trace_id=state.get("run_id"),
            node="generate_code",
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
        )
        return {
            **state,
            "generated_code": code,
            "prompt_tokens": state.get("prompt_tokens", 0) + response.prompt_tokens,
            "completion_tokens": state.get("completion_tokens", 0) + response.completion_tokens,
            "step_count": state.get("step_count", 0) + 1,
        }
    except Exception as exc:  # SDK/network/auth failures -> fatal, route to handle_error
        _logger.error(
            "generate_code_failed", trace_id=state.get("run_id"), node="generate_code", error=str(exc)
        )
        return {**state, "error": f"generate_code failed: {exc}"}


# ---------------------------------------------------------------------------
# execute_code [P1 active]
# ---------------------------------------------------------------------------


def execute_code(state: AgentState) -> AgentState:
    from config.settings import get_settings
    from db.models import DatasetFile
    from db.session import create_db_session
    from sandbox.executor import run_code
    from tools.storage import file_specs_from_rows, resolve_execution_source

    dataset_id = state["dataset_id"]
    try:
        with create_db_session() as session:
            rows = (
                session.query(DatasetFile)
                .filter(DatasetFile.dataset_id == dataset_id)
                .order_by(DatasetFile.uploaded_at.asc())
                .all()
            )
            # Capture specs while the session is open (instances expire on exit).
            specs = file_specs_from_rows(rows)
    except Exception as exc:
        return {**state, "error": f"Failed to look up dataset file: {exc}"}

    if not specs:
        return {**state, "error": f"No file found for dataset {dataset_id!r}."}

    # Resolve ALL backing files to a single execution source: the file itself
    # for single-file datasets, or a materialized combined CSV for multi-file
    # datasets (spec/roadmap.md Phase-2 win) — the sandbox stays unchanged.
    try:
        dataset_path, file_type = resolve_execution_source(
            get_settings().data_dir, specs, dataset_id
        )
    except Exception as exc:
        return {**state, "error": f"Failed to resolve dataset files: {exc}"}
    if not dataset_path.exists():
        return {**state, "error": f"Dataset file is missing on disk: {dataset_path}"}

    exec_result = run_code(state.get("generated_code") or "", dataset_path, file_type)
    _logger.info(
        "execute_code",
        trace_id=state.get("run_id"),
        node="execute_code",
        error=exec_result.error,
    )
    return {
        **state,
        "execution_result": exec_result.result,
        "execution_error": exec_result.error,
    }


# ---------------------------------------------------------------------------
# observe_result [P1 active]
# ---------------------------------------------------------------------------


def observe_result(state: AgentState) -> AgentState:
    from sandbox.executor import summarize_for_llm

    if state.get("execution_error"):
        return {**state, "execution_result": None}

    schema_context = state.get("schema_context") or {}
    full_row_count = schema_context.get("row_count")

    # summarize_for_llm enforces the raw-row privacy boundary and always returns
    # a bounded summary (a large/near-full cleaned frame is aggregated + capped,
    # NOT rejected) so a legitimate cleaning result resolves in a single pass.
    summary = summarize_for_llm(
        state.get("execution_result"),
        source_code=state.get("generated_code") or "",
        full_row_count=full_row_count,
    )
    return {**state, "execution_result": summary}


# ---------------------------------------------------------------------------
# compose_answer [P1 active, minimal fields]
# ---------------------------------------------------------------------------


def compose_answer(state: AgentState) -> AgentState:
    try:
        system_prompt = _load_prompt(_COMPOSE_ANSWER_PROMPT_PATH)
        user_message = _build_compose_answer_user_message(state)
        response = LLMClient().call_model_with_usage(user_message, system=system_prompt)
        parsed = _parse_json_object(response.text)
        from config.settings import get_settings

        max_rows = getattr(get_settings(), "max_summary_rows", 20)
        follow_ups = parsed.get("follow_up_suggestions")
        anomalies = parsed.get("anomalies")
        result_table = _sanitize_result_table(parsed.get("result_table"), max_rows)
        _logger.info(
            "compose_answer",
            trace_id=state.get("run_id"),
            node="compose_answer",
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            has_result_table=result_table is not None,
        )
        return {
            **state,
            "answer_text": parsed.get("answer") or "",
            "key_numbers": parsed.get("key_numbers") or {},
            "follow_up_suggestions": [str(s) for s in follow_ups] if isinstance(follow_ups, list) else [],
            "anomalies": [str(a) for a in anomalies] if isinstance(anomalies, list) else [],
            "result_table": result_table,
            "prompt_tokens": state.get("prompt_tokens", 0) + response.prompt_tokens,
            "completion_tokens": state.get("completion_tokens", 0) + response.completion_tokens,
            "status": "success",
        }
    except Exception as exc:
        _logger.error(
            "compose_answer_failed", trace_id=state.get("run_id"), node="compose_answer", error=str(exc)
        )
        return {**state, "error": f"compose_answer failed: {exc}"}


# ---------------------------------------------------------------------------
# ask_clarification [P1: wired but unreachable]
# ---------------------------------------------------------------------------


def ask_clarification(state: AgentState) -> AgentState:
    return {
        **state,
        "answer_text": state.get("clarification_question"),
        "status": "clarification_needed",
    }


# ---------------------------------------------------------------------------
# cannot_answer [P1 active]
# ---------------------------------------------------------------------------


def cannot_answer(state: AgentState) -> AgentState:
    reason = state.get("execution_error") or "the analysis could not be completed."
    question = state.get("question", "")
    answer = (
        f'I could not answer "{question}" using this dataset. '
        f"Here's why: {reason}"
    )
    return {**state, "answer_text": answer, "status": "cannot_answer"}


# ---------------------------------------------------------------------------
# handle_error [P1 active]
# ---------------------------------------------------------------------------


def handle_error(state: AgentState) -> AgentState:
    _logger.error("run_failed", trace_id=state.get("run_id"), node="handle_error", error=state.get("error"))
    return {**state, "status": "failed"}


# ---------------------------------------------------------------------------
# finalize [P1 active]
# ---------------------------------------------------------------------------


def finalize(state: AgentState) -> AgentState:
    return {**state}
