"""Phase-2 integration tests: iterative loop-back, result_table derivation,
and the raw-row cap on result_table (spec/agent.md, spec/api.md, spec/data.md).

These call the REAL Gemini API (skipped, not stubbed, if no key is present)
and run REAL pandas code in the sandbox subprocess. They assert both response
content and persisted DB state.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from db import session as session_module
from db.models import Conversation, Dataset, DatasetFile, DatasetProfile, QueryRun
from graph.runner import run_agent
from tools.profiling import profile_file


@pytest.fixture
def _require_gemini_key():
    from config.settings import get_settings

    if not get_settings().gemini_api_key:
        pytest.skip("No AGENT_GEMINI_API_KEY set in .env — skipping real-Gemini integration test.")


@pytest.fixture
def _groupby_dataset(_isolated_db, tmp_path, monkeypatch):
    """A single real CSV with a clear categorical (`region`) and numeric
    (`revenue`) column so a groupby-by-region answer yields a small, bounded
    result_table (4 regions << AGENT_MAX_SUMMARY_ROWS)."""
    import pandas as pd

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    # 200 rows, 4 regions -> groupby produces exactly 4 rows.
    rows = []
    regions = ["North", "South", "East", "West"]
    for i in range(200):
        rows.append({"region": regions[i % 4], "revenue": float(50 + (i % 40)), "units": i % 7})
    df = pd.DataFrame(rows)
    csv_path = data_dir / "sales.csv"
    df.to_csv(csv_path, index=False)

    monkeypatch.setenv("AGENT_DATA_DIR", str(data_dir))
    import config.settings as settings_module

    settings_module._settings = None

    profile_dict = profile_file(csv_path, "csv")

    with Session(session_module._engine) as s:
        dataset = Dataset(name="Sales", kind="single_file", status="ready")
        s.add(dataset)
        s.flush()
        s.add(
            DatasetFile(
                dataset_id=dataset.id,
                original_filename="sales.csv",
                stored_path="sales.csv",  # relative to AGENT_DATA_DIR
                file_type="csv",
                size_bytes=csv_path.stat().st_size,
                row_count=profile_dict["row_count"],
            )
        )
        s.add(
            DatasetProfile(
                dataset_id=dataset.id,
                row_count=profile_dict["row_count"],
                column_count=profile_dict["column_count"],
                columns_json=profile_dict["columns"],
            )
        )
        conversation = Conversation(dataset_id=dataset.id, title="Untitled analysis")
        s.add(conversation)
        s.commit()
        return dataset.id, conversation.id


@pytest.mark.usefixtures("_require_gemini_key")
def test_groupby_question_returns_populated_result_table(_groupby_dataset):
    """A groupby-style question ('average revenue by region') must return a
    populated result_table (columns + rows) within the AGENT_MAX_SUMMARY_ROWS cap."""
    from config.settings import get_settings

    dataset_id, conversation_id = _groupby_dataset
    max_rows = get_settings().max_summary_rows

    run_id = run_agent(dataset_id, conversation_id, "What is the average revenue by region?")

    with Session(session_module._engine) as s:
        run = s.get(QueryRun, run_id)

    assert run is not None
    assert run.execution_status == "success"
    table = run.result_table_json
    assert table is not None, f"expected a result_table, answer={run.answer_text!r}"
    assert isinstance(table["columns"], list) and len(table["columns"]) >= 2
    assert isinstance(table["rows"], list) and 1 <= len(table["rows"]) <= max_rows
    # 4 regions in the data -> at most 4 rows.
    assert len(table["rows"]) <= 4


@pytest.mark.usefixtures("_require_gemini_key")
def test_scalar_question_returns_null_result_table(_groupby_dataset):
    """A scalar-only question ('overall average revenue') must return result_table=null."""
    dataset_id, conversation_id = _groupby_dataset

    run_id = run_agent(dataset_id, conversation_id, "What is the overall average revenue across all rows?")

    with Session(session_module._engine) as s:
        run = s.get(QueryRun, run_id)

    assert run is not None
    assert run.execution_status == "success"
    assert run.result_table_json is None, f"expected null result_table, got {run.result_table_json!r}"


@pytest.mark.usefixtures("_require_gemini_key")
def test_multi_step_loop_retries_and_increments_step_count(_groupby_dataset, monkeypatch):
    """A first-attempt execution error triggers the Phase-2 loop-back: the graph
    routes back to generate_code (a fresh REAL Gemini call), and step_count > 1.

    Only the FIRST sandbox execution is forced to fail; subsequent attempts run
    the real sandbox, so the real self-correction loop is exercised end-to-end."""
    import graph.nodes as nodes_module
    from sandbox.executor import ExecutionResult, run_code as real_run_code

    dataset_id, conversation_id = _groupby_dataset
    call_count = {"n": 0}

    def _flaky_run_code(code, dataset_path, file_type):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return ExecutionResult(
                result=None, stdout="", error="KeyError: 'nonexistent_column' (forced first-attempt failure)"
            )
        return real_run_code(code, dataset_path, file_type)

    monkeypatch.setattr(nodes_module, "run_code", _flaky_run_code, raising=False)
    # execute_code imports run_code inside the function from sandbox.executor,
    # so patch there too.
    import sandbox.executor as executor_module

    monkeypatch.setattr(executor_module, "run_code", _flaky_run_code)

    run_id = run_agent(dataset_id, conversation_id, "What is the average revenue by region?")

    with Session(session_module._engine) as s:
        run = s.get(QueryRun, run_id)

    assert run is not None
    assert call_count["n"] >= 2, "the loop should have retried after the forced failure"
    assert run.step_count > 1, f"expected step_count > 1 after a retry, got {run.step_count}"
