"""Unit tests for the compose_answer result_table sanitiser (spec/agent.md).

These are pure/no-LLM tests of `_sanitize_result_table`, the defensive cap that
guarantees a model-produced `result_table` can never exceed
`AGENT_MAX_SUMMARY_ROWS` rows (the raw-row privacy boundary) and is `None` for
anything that isn't a well-formed table (e.g. a scalar answer).
"""
from __future__ import annotations

from graph.nodes import _sanitize_result_table


def test_result_table_is_capped_at_max_summary_rows():
    """Even if the model returns MORE rows than the cap, the sanitiser truncates
    to exactly `max_rows` — the privacy boundary can never be exceeded."""
    max_rows = 5
    over_produced = {
        "columns": ["category", "avg_amount"],
        "rows": [[f"cat_{i}", float(i)] for i in range(max_rows + 10)],
    }

    table = _sanitize_result_table(over_produced, max_rows)

    assert table is not None
    assert table["columns"] == ["category", "avg_amount"]
    assert len(table["rows"]) == max_rows
    # First `max_rows` rows are preserved in order.
    assert table["rows"][0] == ["cat_0", 0.0]
    assert table["rows"][-1] == ["cat_4", 4.0]


def test_result_table_within_cap_is_passed_through():
    table = _sanitize_result_table(
        {"columns": ["region", "total"], "rows": [["north", 10], ["south", 20]]},
        max_rows=20,
    )
    assert table == {"columns": ["region", "total"], "rows": [["north", 10], ["south", 20]]}


def test_records_shaped_rows_are_projected_onto_columns():
    """Tolerate a records-shaped `rows` (list of dicts) by projecting onto the
    declared column order."""
    table = _sanitize_result_table(
        {
            "columns": ["region", "total"],
            "rows": [{"region": "north", "total": 10}, {"region": "south", "total": 20}],
        },
        max_rows=20,
    )
    assert table == {"columns": ["region", "total"], "rows": [["north", 10], ["south", 20]]}


def test_scalar_answer_yields_null_result_table():
    """A scalar-only answer has no table — the model returns null / a non-dict,
    and the sanitiser must yield None (not a bogus one-cell table)."""
    assert _sanitize_result_table(None, max_rows=20) is None
    assert _sanitize_result_table(42, max_rows=20) is None
    assert _sanitize_result_table("1234.5", max_rows=20) is None


def test_malformed_table_yields_null():
    """Missing/empty columns or a non-list rows field -> None (never a partial table)."""
    assert _sanitize_result_table({"rows": [[1, 2]]}, max_rows=20) is None  # no columns
    assert _sanitize_result_table({"columns": [], "rows": [[1]]}, max_rows=20) is None
    assert _sanitize_result_table({"columns": ["a"], "rows": "not-a-list"}, max_rows=20) is None
    assert _sanitize_result_table({"columns": ["a"], "rows": []}, max_rows=20) is None
