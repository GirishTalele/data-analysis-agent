"""Standalone runner script executed in an isolated subprocess by
``src/sandbox/executor.py::run_code``.

This module is never imported by the rest of the application — it is always
invoked as its own Python process (``sys.executable src/sandbox/runner.py
<payload.json> <output.json>``). It loads the target dataset, executes the
LLM-generated pandas code against it in a restricted namespace, and writes the
outcome (result or error) to the output JSON file so the parent process can
read it back.

The parent process (``executor.py::run_code``) is responsible for the AST
safety guardrail *before* this script is even spawned; this script's only job
is to execute already-approved code against the real data, in isolation.
"""
from __future__ import annotations

import io
import json
import math
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import numpy as np
import pandas as pd

# Explicit allow-list of builtins exposed to LLM-generated code. Anything not
# listed here (eval, exec, open, __import__, getattr, setattr, compile,
# globals, locals, vars, breakpoint, input, ...) is simply absent from the
# namespace, so any attempt to reach it — directly or via
# ``getattr(__builtins__, ...)`` — raises NameError/AttributeError/KeyError
# inside this subprocess instead of reaching the real Python builtins.
SAFE_BUILTINS: dict = {
    "len": len,
    "range": range,
    "min": min,
    "max": max,
    "sum": sum,
    "abs": abs,
    "round": round,
    "sorted": sorted,
    "list": list,
    "dict": dict,
    "set": set,
    "tuple": tuple,
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "enumerate": enumerate,
    "zip": zip,
    "map": map,
    "filter": filter,
    "print": print,
    "True": True,
    "False": False,
    "None": None,
}


def _load_dataframe(dataset_path: str, file_type: str) -> pd.DataFrame:
    normalized = file_type.lower().lstrip(".")
    if normalized == "csv":
        return pd.read_csv(dataset_path)
    if normalized in ("xlsx", "xls", "excel"):
        return pd.read_excel(dataset_path)
    if normalized == "qvd":
        # Isolated-subprocess safe: pyqvd is a normal runtime dependency, so
        # ``sys.executable`` (this process) can import it.
        from pyqvd import QvdTable

        return QvdTable.from_qvd(str(dataset_path)).to_pandas()
    raise ValueError(f"Unsupported file_type '{file_type}'")


def _serialize(value):
    """Convert an arbitrary execution result into a JSON-safe structure.

    DataFrame/Series are tagged with ``__type__`` so the parent process can
    reconstruct them (summarize_for_llm needs the real pandas type to apply
    the raw-row privacy boundary correctly).
    """
    if isinstance(value, pd.DataFrame):
        return {
            "__type__": "dataframe",
            "records": json.loads(value.to_json(orient="records")),
            "columns": [str(c) for c in value.columns],
        }
    if isinstance(value, pd.Series):
        return {
            "__type__": "series",
            "data": json.loads(value.to_json()),
            "name": str(value.name) if value.name is not None else None,
        }
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        as_float = float(value)
        return None if math.isnan(as_float) else as_float
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, dict):
        return {str(k): _serialize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize(v) for v in value]
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def main() -> None:
    payload_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    payload = json.loads(payload_path.read_text(encoding="utf-8"))

    code = payload["code"]
    dataset_path = payload["dataset_path"]
    file_type = payload["file_type"]

    stdout_buffer = io.StringIO()
    output: dict = {"result": None, "stdout": "", "error": None}

    try:
        df = _load_dataframe(dataset_path, file_type)
        namespace = {"pd": pd, "df": df, "__builtins__": SAFE_BUILTINS}
        with redirect_stdout(stdout_buffer), redirect_stderr(stdout_buffer):
            exec(compile(code, "<generated_code>", "exec"), namespace)
        if "result" not in namespace:
            output["error"] = "Generated code did not assign a 'result' variable."
        else:
            output["result"] = _serialize(namespace["result"])
    except Exception as exc:  # noqa: BLE001 - must never crash, always report
        output["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        output["stdout"] = stdout_buffer.getvalue()

    output_path.write_text(json.dumps(output), encoding="utf-8")


if __name__ == "__main__":
    main()
