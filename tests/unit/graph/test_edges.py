"""Unit tests for the Phase-2 loop-back / clarification / error routing
(spec/agent.md -> "Conditional edges") and result_table sanitization."""
from __future__ import annotations

from graph.edges import after_clarity, after_observe_result
from graph.nodes import _sanitize_result_table


# --- after_clarity ---------------------------------------------------------


def test_after_clarity_routes_to_handle_error_on_error():
    assert after_clarity({"error": "boom"}) == "handle_error"


def test_after_clarity_routes_to_ask_clarification_when_needed():
    assert after_clarity({"needs_clarification": True}) == "ask_clarification"


def test_after_clarity_defaults_to_generate_code():
    assert after_clarity({"needs_clarification": False}) == "generate_code"


# --- after_observe_result (the iterative loop-back) ------------------------


def test_loop_back_when_execution_error_and_steps_remain():
    """execution_error set + step_count < max_steps -> retry generate_code."""
    state = {"execution_error": "KeyError", "step_count": 1, "max_steps": 5}
    assert after_observe_result(state) == "generate_code"


def test_terminates_at_max_steps_to_cannot_answer():
    """execution_error still set once step_count == max_steps -> cannot_answer."""
    state = {"execution_error": "KeyError", "step_count": 5, "max_steps": 5}
    assert after_observe_result(state) == "cannot_answer"


def test_success_routes_to_compose_answer():
    state = {"execution_error": None, "step_count": 1, "max_steps": 5}
    assert after_observe_result(state) == "compose_answer"


def test_loop_back_boundary_just_below_max():
    state = {"execution_error": "err", "step_count": 4, "max_steps": 5}
    assert after_observe_result(state) == "generate_code"


# --- _sanitize_result_table ------------------------------------------------


def test_result_table_none_for_non_dict():
    assert _sanitize_result_table(None, 20) is None
    assert _sanitize_result_table(42, 20) is None
    assert _sanitize_result_table("x", 20) is None


def test_result_table_rejects_missing_columns_or_rows():
    assert _sanitize_result_table({"rows": [[1]]}, 20) is None
    assert _sanitize_result_table({"columns": ["a"]}, 20) is None
    assert _sanitize_result_table({"columns": [], "rows": []}, 20) is None


def test_result_table_caps_rows_at_max():
    rows = [[i, i * 2] for i in range(100)]
    table = _sanitize_result_table({"columns": ["a", "b"], "rows": rows}, 20)
    assert table is not None
    assert len(table["rows"]) == 20
    assert table["columns"] == ["a", "b"]


def test_result_table_projects_record_shaped_rows_onto_columns():
    raw = {"columns": ["region", "avg"], "rows": [{"region": "North", "avg": 88.4}]}
    table = _sanitize_result_table(raw, 20)
    assert table == {"columns": ["region", "avg"], "rows": [["North", 88.4]]}


def test_result_table_wellformed_passes_through():
    raw = {"columns": ["region", "avg"], "rows": [["North", 88.4], ["South", 74.1]]}
    table = _sanitize_result_table(raw, 20)
    assert table == raw
