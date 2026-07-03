"""Unit tests for src/tools/joins.py (spec/api.md -> POST /datasets/join)."""
import pandas as pd
import pytest

from tools.joins import (
    InvalidJoinError,
    JoinKeyMissingError,
    join_dataframes,
)


def _customers():
    return pd.DataFrame({"customer_id": [1, 2, 3], "name": ["a", "b", "c"]})


def _orders():
    return pd.DataFrame({"customer_id": [1, 2, 2], "amount": [10, 20, 30]})


def test_inner_join_happy_path():
    result = join_dataframes([_customers(), _orders()], join_on="customer_id", how="inner")
    assert set(result.columns) == {"customer_id", "name", "amount"}
    # customer 3 has no orders -> dropped by inner join; 2 has two orders.
    assert len(result) == 3
    assert sorted(result["amount"].tolist()) == [10, 20, 30]


def test_left_join_keeps_unmatched_rows():
    result = join_dataframes([_customers(), _orders()], join_on="customer_id", how="left")
    assert len(result) == 4  # 3 orders + customer 3 with NaN amount
    assert result["amount"].isna().sum() == 1


def test_three_way_join():
    third = pd.DataFrame({"customer_id": [1, 2, 3], "region": ["N", "S", "E"]})
    result = join_dataframes(
        [_customers(), _orders(), third], join_on="customer_id", how="inner"
    )
    assert "region" in result.columns
    assert len(result) == 3


def test_missing_join_key_raises():
    bad = pd.DataFrame({"other_id": [1, 2], "x": [1, 2]})
    with pytest.raises(JoinKeyMissingError):
        join_dataframes([_customers(), bad], join_on="customer_id", how="inner")


def test_fewer_than_two_frames_raises():
    with pytest.raises(InvalidJoinError):
        join_dataframes([_customers()], join_on="customer_id", how="inner")


def test_unsupported_how_raises():
    with pytest.raises(InvalidJoinError):
        join_dataframes([_customers(), _orders()], join_on="customer_id", how="cross-ish")
