"""Dataset joins — Phase 2 (spec/api.md -> POST /datasets/join).

Combine two or more DataFrames on a shared key into a single joined frame.
Pure functions: no DB or filesystem access (the API layer resolves datasets to
DataFrames via ``tools.storage.load_dataset_dataframe`` and persists results).
"""
from __future__ import annotations

from collections.abc import Sequence
from functools import reduce

import pandas as pd

# pandas merge `how` values we accept (spec/api.md -> `how`).
ALLOWED_HOW = {"inner", "left", "right", "outer"}


class JoinKeyMissingError(ValueError):
    """Raised when the join key is absent from one of the datasets (spec/api.md -> 400)."""


class InvalidJoinError(ValueError):
    """Raised for a structurally invalid join request (too few frames, bad `how`)."""


def join_dataframes(
    frames: Sequence[pd.DataFrame],
    *,
    join_on: str,
    how: str = "inner",
) -> pd.DataFrame:
    """Join >=2 DataFrames on `join_on` using `how`.

    Raises:
        InvalidJoinError: fewer than 2 frames or an unsupported `how`.
        JoinKeyMissingError: `join_on` is missing from any frame (spec 400).
    """
    if len(frames) < 2:
        raise InvalidJoinError("A join requires at least two datasets.")
    if how not in ALLOWED_HOW:
        raise InvalidJoinError(
            f"Unsupported join type '{how}'. Allowed: {', '.join(sorted(ALLOWED_HOW))}."
        )

    missing = [i for i, f in enumerate(frames) if join_on not in f.columns]
    if missing:
        raise JoinKeyMissingError(
            f"Join key '{join_on}' is missing from dataset(s) at position(s) "
            f"{', '.join(str(i) for i in missing)}."
        )

    return reduce(
        lambda left, right: pd.merge(left, right, on=join_on, how=how), frames
    )
