"""Sandboxed execution of LLM-generated pandas code, and the raw-row privacy
boundary that guards every result before it can re-enter an LLM prompt.

See ``spec/architecture.md`` ("Raw-Row Privacy Boundary", "Sandboxed Code
Execution") and ``spec/agent.md`` (the ``run_code`` / ``summarize_for_llm``
tool table) for the contract this module implements.

Public contract:
    run_code(code: str, dataset_path: Path, file_type: str) -> ExecutionResult
    summarize_for_llm(result, source_code: str = "", full_row_count: int | None = None) -> Any
"""
from __future__ import annotations

import ast
import json
import math
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from config.settings import get_settings

# Names that must never appear in LLM-generated code — a guardrail against
# LLM mistakes, not a hardened multi-tenant sandbox (single trusted local user).
FORBIDDEN_NAMES = {
    "os",
    "sys",
    "subprocess",
    "socket",
    "open",
    "__import__",
    "eval",
    "exec",
    "compile",
    "getattr",
    "setattr",
    "globals",
    "locals",
    "vars",
    "__builtins__",
    "input",
    "breakpoint",
}

_RUNNER_SCRIPT = Path(__file__).parent / "runner.py"


@dataclass
class ExecutionResult:
    """Outcome of running LLM-generated code in the sandbox subprocess."""

    result: Any | None = None
    stdout: str = ""
    error: str | None = None


def _check_code_safety(code: str) -> str | None:
    """Return a human-readable error string if `code` is disallowed, else None."""
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return f"Generated code has a syntax error: {exc}"

    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            return f"Generated code references disallowed name '{node.id}'."
        if (
            isinstance(node, ast.Attribute)
            and node.attr.startswith("__")
            and node.attr.endswith("__")
        ):
            return f"Generated code uses disallowed dunder attribute '{node.attr}'."
        if isinstance(node, ast.Import):
            for alias in node.names:
                root_module = alias.name.split(".")[0]
                if root_module in FORBIDDEN_NAMES:
                    return f"Generated code imports disallowed module '{alias.name}'."
        if isinstance(node, ast.ImportFrom):
            root_module = (node.module or "").split(".")[0]
            if root_module in FORBIDDEN_NAMES:
                return f"Generated code imports disallowed module '{node.module}'."
    return None


def _deserialize(value: Any) -> Any:
    """Reconstruct DataFrame/Series from the runner's JSON-safe encoding."""
    if isinstance(value, dict) and value.get("__type__") == "dataframe":
        return pd.DataFrame.from_records(value.get("records", []), columns=value.get("columns"))
    if isinstance(value, dict) and value.get("__type__") == "series":
        series = pd.Series(value.get("data", {}))
        series.name = value.get("name")
        return series
    return value


def run_code(code: str, dataset_path: Path, file_type: str) -> ExecutionResult:
    """Run LLM-generated pandas `code` against `dataset_path` in an isolated subprocess.

    Never raises — every failure mode (unsafe code, syntax error, runtime
    exception inside the generated code, subprocess timeout, non-zero exit) is
    captured into `ExecutionResult.error`.
    """
    safety_error = _check_code_safety(code)
    if safety_error:
        return ExecutionResult(result=None, stdout="", error=safety_error)

    settings = get_settings()
    timeout = getattr(settings, "sandbox_timeout_seconds", 20)

    payload = {
        "code": code,
        "dataset_path": str(dataset_path),
        "file_type": file_type,
    }

    with tempfile.TemporaryDirectory() as tmp_dir:
        payload_path = Path(tmp_dir) / "payload.json"
        output_path = Path(tmp_dir) / "output.json"
        payload_path.write_text(json.dumps(payload), encoding="utf-8")

        try:
            proc = subprocess.run(
                [sys.executable, str(_RUNNER_SCRIPT), str(payload_path), str(output_path)],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return ExecutionResult(
                result=None, stdout="", error=f"Execution timed out after {timeout}s."
            )
        except OSError as exc:
            return ExecutionResult(
                result=None, stdout="", error=f"Failed to start sandbox subprocess: {exc}"
            )

        if proc.returncode != 0:
            error_msg = (proc.stderr or "").strip() or (
                f"Sandbox subprocess exited with code {proc.returncode}."
            )
            return ExecutionResult(result=None, stdout=proc.stdout or "", error=error_msg)

        if not output_path.exists():
            return ExecutionResult(
                result=None, stdout=proc.stdout or "", error="Sandbox subprocess produced no output."
            )

        try:
            output = json.loads(output_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            return ExecutionResult(
                result=None, stdout=proc.stdout or "", error=f"Failed to read sandbox output: {exc}"
            )

        if output.get("error"):
            return ExecutionResult(
                result=None,
                stdout=output.get("stdout", proc.stdout or ""),
                error=output["error"],
            )

        return ExecutionResult(
            result=_deserialize(output.get("result")),
            stdout=output.get("stdout", proc.stdout or ""),
            error=None,
        )


def _json_safe_key(key: Any) -> str:
    if isinstance(key, str):
        return key
    if isinstance(key, (np.integer,)):
        return str(int(key))
    if isinstance(key, (np.floating,)):
        return str(float(key))
    return str(key)


def _json_safe(value: Any) -> Any:
    """Recursively coerce numpy/pandas scalar types into plain JSON-safe types."""
    if isinstance(value, dict):
        return {_json_safe_key(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        as_float = float(value)
        return None if math.isnan(as_float) else as_float
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def summarize_for_llm(
    result: Any,
    source_code: str = "",
    full_row_count: int | None = None,
) -> Any:
    """Enforce the raw-row privacy boundary before `result` may enter an LLM prompt.

    Rules (see spec/architecture.md → "Raw-Row Privacy Boundary"):
      - Scalars (int/float/str/bool/None) pass through unchanged.
      - dict/list results are capped at `settings.max_summary_items`; beyond
        that, truncated with an explicit `{"truncated": true, "total_items": N}` marker.
      - DataFrame/Series results with row_count <= `settings.max_summary_rows`
        are converted to plain dict/records; above that threshold only an
        aggregate (`.describe()` / `.value_counts()`) plus the true row count,
        a capped head `sample` (<= `settings.max_summary_rows` rows) and a
        `"truncated": true` marker is returned — never the raw bulk rows.

    A legitimate large / near-full result (e.g. a cleaned frame that keeps most
    of the dataset) is therefore treated as a SUMMARIZABLE SUCCESS: it is
    aggregated + capped, not hard-rejected. This keeps the raw-row privacy
    boundary fully intact (only <= `max_summary_rows` rows ever surface to the
    LLM, exactly as for any other above-cap result) while letting
    `compose_answer` narrate the result and derive a bounded `result_table`.
    The export endpoint re-runs the code against the full data OUTSIDE this
    boundary, so it still produces the complete cleaned output.

    `source_code` / `full_row_count` are retained for signature stability and
    logging context; they no longer drive a hard rejection (the previous
    full-frame-passthrough ValueError forced a costly retry loop for
    legitimate cleaning questions).
    """
    settings = get_settings()
    max_items = getattr(settings, "max_summary_items", 50)
    max_rows = getattr(settings, "max_summary_rows", 20)

    if result is None or isinstance(result, (int, float, str, bool)):
        return result

    if isinstance(result, (pd.Series, pd.DataFrame)):
        row_count = len(result)

        if row_count <= max_rows:
            if isinstance(result, pd.Series):
                return {"data": _json_safe(result.to_dict()), "row_count": row_count}
            return {"data": _json_safe(result.to_dict(orient="records")), "row_count": row_count}

        # Above the cap (includes large/near-full cleaned frames): never return
        # the raw bulk rows — only an aggregate plus a head sample capped at
        # max_rows, marked truncated.
        if isinstance(result, pd.Series):
            if pd.api.types.is_numeric_dtype(result):
                summary = result.describe().to_dict()
            else:
                summary = result.value_counts().head(max_items).to_dict()
            sample = _json_safe(result.head(max_rows).to_dict())
        else:
            numeric_cols = result.select_dtypes(include="number")
            if not numeric_cols.empty:
                summary = numeric_cols.describe().to_dict()
            else:
                summary = {
                    str(col): result[col].value_counts().head(max_items).to_dict()
                    for col in result.columns
                }
            sample = _json_safe(result.head(max_rows).to_dict(orient="records"))

        return {
            "summary": _json_safe(summary),
            "sample": sample,
            "row_count": row_count,
            "truncated": True,
        }

    if isinstance(result, dict):
        if len(result) > max_items:
            truncated_items = dict(list(result.items())[:max_items])
            return {
                "truncated": True,
                "total_items": len(result),
                "items": _json_safe(truncated_items),
            }
        return _json_safe(result)

    if isinstance(result, list):
        if len(result) > max_items:
            return {
                "truncated": True,
                "total_items": len(result),
                "items": _json_safe(result[:max_items]),
            }
        return _json_safe(result)

    # Fallback for any other scalar-like type (e.g. numpy scalar).
    return _json_safe(result)
