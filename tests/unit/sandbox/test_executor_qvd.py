"""QVD support in the sandbox subprocess (Phase 3).

CRITICAL: ``run_code`` spawns an isolated subprocess
(``sys.executable src/sandbox/runner.py``), so the QVD import must work THERE.
This test proves pyqvd is importable in the subprocess and that LLM-generated
pandas code runs against a QVD-loaded frame exactly as against a CSV. The QVD
fixture is generated programmatically with pyqvd's writer — no committed blob.
"""
from __future__ import annotations

import pandas as pd
import pytest

from sandbox.executor import run_code


@pytest.fixture
def sales_qvd(tmp_path):
    from pyqvd import QvdTable

    df = pd.DataFrame(
        {
            "region": ["North", "South", "North", "East"],
            "amount": [100.0, 200.0, 300.0, 400.0],
        }
    )
    path = tmp_path / "sales.qvd"
    QvdTable.from_pandas(df).to_qvd(str(path))
    return path, df


def test_run_code_against_qvd_in_subprocess(sales_qvd):
    path, df = sales_qvd
    result = run_code("result = df['amount'].sum()", path, "qvd")
    assert result.error is None, result.error
    assert result.result == pytest.approx(float(df["amount"].sum()))


def test_run_code_groupby_against_qvd(sales_qvd):
    path, df = sales_qvd
    result = run_code(
        "result = df.groupby('region')['amount'].sum()", path, "qvd"
    )
    assert result.error is None, result.error
