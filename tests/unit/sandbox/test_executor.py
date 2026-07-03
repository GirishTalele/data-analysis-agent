"""Tests for the sandbox executor / raw-row privacy boundary.

These exercise real subprocess execution against a real CSV fixture (no
mocking of pandas) so the AST guardrail and the privacy boundary are
genuinely tested, not merely asserted-around.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from sandbox.executor import ExecutionResult, run_code, summarize_for_llm

FIXTURE_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "sample_sales.csv"
FULL_ROW_COUNT = 30  # matches tests/fixtures/sample_sales.csv


def test_fixture_has_expected_row_count():
    df = pd.read_csv(FIXTURE_PATH)
    assert len(df) == FULL_ROW_COUNT


# ---------------------------------------------------------------------------
# run_code
# ---------------------------------------------------------------------------


def test_run_code_scalar_result():
    result = run_code("result = df['amount'].sum()", FIXTURE_PATH, "csv")
    assert result.error is None
    assert isinstance(result.result, (int, float))


def test_run_code_dataframe_result():
    result = run_code(
        "result = df.groupby('category')['amount'].sum().reset_index()",
        FIXTURE_PATH,
        "csv",
    )
    assert result.error is None
    assert isinstance(result.result, pd.DataFrame)
    assert set(result.result.columns) == {"category", "amount"}


def test_run_code_rejects_os_reference_before_execution():
    result = run_code("import os\nresult = os.getcwd()", FIXTURE_PATH, "csv")
    assert result.result is None
    assert result.error is not None
    assert "os" in result.error.lower() or "disallowed" in result.error.lower()


def test_run_code_rejects_open_call():
    result = run_code("f = open('secret.txt')\nresult = 1", FIXTURE_PATH, "csv")
    assert result.error is not None
    assert result.result is None


def test_run_code_rejects_subprocess_reference():
    result = run_code(
        "import subprocess\nresult = subprocess.run(['ls'])", FIXTURE_PATH, "csv"
    )
    assert result.error is not None
    assert result.result is None


def test_run_code_rejects_dunder_attribute_access():
    result = run_code("result = df.__class__", FIXTURE_PATH, "csv")
    assert result.error is not None
    assert result.result is None


def test_run_code_captures_runtime_exception_without_raising():
    # 'nonexistent_column' does not exist -> KeyError inside exec(), must be
    # captured as ExecutionResult.error, never raised out of run_code.
    result = run_code("result = df['nonexistent_column']", FIXTURE_PATH, "csv")
    assert isinstance(result, ExecutionResult)
    assert result.error is not None
    assert result.result is None


def test_run_code_missing_result_variable_is_an_error():
    result = run_code("x = 1 + 1", FIXTURE_PATH, "csv")
    assert result.error is not None
    assert result.result is None


def test_run_code_rejects_eval_string_bypass():
    # Regression: wrapping a forbidden call inside a string passed to eval()
    # must not defeat the AST guardrail nor reach the real filesystem/OS.
    result = run_code(
        "result = eval(\"__import__('os').getcwd()\")", FIXTURE_PATH, "csv"
    )
    assert result.error is not None
    # Must never leak a real filesystem path.
    assert result.result is None


def test_run_code_rejects_builtins_getattr_open_bypass():
    # Regression: __builtins__ is a bare Name (not an Attribute), and exec()
    # auto-injects it into the namespace. getattr(__builtins__, 'open') must
    # not be able to reach the real open() and read raw file content.
    code = (
        "b = __builtins__\n"
        "op = getattr(b, 'open') if not isinstance(b, dict) else b['open']\n"
        "f = op(r'" + str(FIXTURE_PATH) + "')\n"
        "result = f.read()\n"
        "f.close()\n"
    )
    result = run_code(code, FIXTURE_PATH, "csv")
    assert result.error is not None
    assert result.result is None
    # Must never leak raw CSV content.
    fixture_content = FIXTURE_PATH.read_text(encoding="utf-8")
    assert result.stdout != fixture_content


def test_safe_builtins_excludes_dangerous_names():
    from sandbox.runner import SAFE_BUILTINS

    for forbidden in ("open", "eval", "exec", "__import__", "getattr", "compile", "setattr"):
        assert forbidden not in SAFE_BUILTINS


def test_run_code_timeout_returns_error_not_exception(monkeypatch):
    import sandbox.executor as executor_module

    class _FakeSettings:
        sandbox_timeout_seconds = 1
        max_summary_items = 50
        max_summary_rows = 20

    monkeypatch.setattr(executor_module, "get_settings", lambda: _FakeSettings())

    result = run_code(
        "import time\ntime.sleep(5)\nresult = 1", FIXTURE_PATH, "csv"
    )
    assert result.error is not None
    assert "timed out" in result.error.lower()
    assert result.result is None


# ---------------------------------------------------------------------------
# summarize_for_llm
# ---------------------------------------------------------------------------


def test_summarize_scalar_passthrough():
    assert summarize_for_llm(42) == 42
    assert summarize_for_llm(3.14) == 3.14
    assert summarize_for_llm("hello") == "hello"
    assert summarize_for_llm(None) is None
    assert summarize_for_llm(True) is True


def test_summarize_small_dataframe_is_fully_summarized():
    df = pd.DataFrame({"category": ["a", "b", "c"], "amount": [1.0, 2.0, 3.0]})
    summary = summarize_for_llm(df, source_code="result = df.groupby('category').sum()")
    assert summary["row_count"] == 3
    assert len(summary["data"]) == 3
    assert summary["data"][0]["category"] == "a"


def test_summarize_large_dataframe_never_returns_raw_rows():
    # 100 rows, well above max_summary_rows default (20); code includes an
    # aggregation marker so this doesn't hit the pass-through rejection path.
    df = pd.DataFrame({"amount": list(range(100))})
    summary = summarize_for_llm(
        df, source_code="result = df.groupby('amount').sum()", full_row_count=None
    )
    assert summary["truncated"] is True
    assert summary["row_count"] == 100
    # The only allowed "row-shaped" data is the describe() aggregate — assert
    # explicitly that no per-row records structure (list of len == row_count)
    # is present anywhere in the returned summary.
    assert "data" not in summary
    assert isinstance(summary["summary"], dict)
    for stats in summary["summary"].values():
        assert isinstance(stats, dict)
        assert len(stats) <= 8  # describe() only ever produces ~8 stat rows


def test_summarize_oversized_list_is_truncated_at_cap():
    big_list = list(range(75))
    summary = summarize_for_llm(big_list)
    assert summary["truncated"] is True
    assert summary["total_items"] == 75
    assert len(summary["items"]) == 50  # default max_summary_items


def test_summarize_oversized_dict_is_truncated_at_cap():
    big_dict = {f"k{i}": i for i in range(60)}
    summary = summarize_for_llm(big_dict)
    assert summary["truncated"] is True
    assert summary["total_items"] == 60
    assert len(summary["items"]) == 50


def test_summarize_small_list_and_dict_pass_through_unchanged():
    assert summarize_for_llm([1, 2, 3]) == [1, 2, 3]
    assert summarize_for_llm({"a": 1, "b": 2}) == {"a": 1, "b": 2}


def test_summarize_full_frame_passthrough_degrades_to_capped_summary():
    """A near-full/full-frame result (e.g. a cleaning step that keeps most rows)
    is NOT hard-rejected — it degrades to an aggregated, row-capped summary so
    the cleaning question resolves in a single pass. The raw-row privacy
    boundary still holds: only <= max_summary_rows rows ever surface, and the
    full bulk of rows is never returned."""
    from config.settings import get_settings

    max_rows = get_settings().max_summary_rows
    df = pd.read_csv(FIXTURE_PATH)  # 30 rows > max_summary_rows(20)
    summary = summarize_for_llm(
        df, source_code="result = df.dropna(subset=['amount'])", full_row_count=FULL_ROW_COUNT
    )
    # Aggregated success, not a rejection.
    assert summary["truncated"] is True
    assert summary["row_count"] == FULL_ROW_COUNT
    assert "data" not in summary  # never the full raw frame
    # The head sample is present but strictly capped at the boundary.
    assert isinstance(summary["sample"], list)
    assert len(summary["sample"]) <= max_rows
    assert len(summary["sample"]) < FULL_ROW_COUNT  # bulk rows withheld


def test_summarize_allows_full_length_result_when_aggregation_detected():
    # Edge case: an aggregation that happens to produce as many rows as the
    # original dataset (e.g. groupby on a unique id column) should NOT be
    # rejected, since real aggregation was detected in the source.
    df = pd.read_csv(FIXTURE_PATH)
    grouped = df.groupby("id")["amount"].sum().reset_index()
    assert len(grouped) == FULL_ROW_COUNT
    summary = summarize_for_llm(
        grouped,
        source_code="result = df.groupby('id')['amount'].sum().reset_index()",
        full_row_count=FULL_ROW_COUNT,
    )
    # 30 rows is above max_summary_rows(20), so it's aggregated, not raw rows.
    assert summary["truncated"] is True
    assert "data" not in summary


def test_run_code_then_summarize_end_to_end_small_result():
    exec_result = run_code(
        "result = df.groupby('category')['amount'].sum().reset_index()",
        FIXTURE_PATH,
        "csv",
    )
    assert exec_result.error is None
    summary = summarize_for_llm(
        exec_result.result,
        source_code="result = df.groupby('category')['amount'].sum().reset_index()",
        full_row_count=FULL_ROW_COUNT,
    )
    assert summary["row_count"] <= 20
    assert "data" in summary
