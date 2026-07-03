"""Integration tests for the audit-trail endpoints (spec/api.md ->
GET /query-runs, GET /cost-summary).

Real FastAPI TestClient against a real isolated SQLite DB (production driver).
QueryRun rows are seeded directly via the DB session — these endpoints are
pure read/rollup views and involve no LLM call.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest


def _seed(session, *, id, conversation_id, dataset_id, status="success",
          prompt_tokens=100, completion_tokens=50, cost=0.001, created_at=None,
          question="q?"):
    from db.models import QueryRun

    run = QueryRun(
        id=id,
        conversation_id=conversation_id,
        dataset_id=dataset_id,
        question_text=question,
        generated_code="result = df['x'].sum()",
        step_count=1,
        execution_status=status,
        answer_text="an answer",
        key_numbers_json={"x": 1},
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        estimated_cost_usd=cost,
        latency_ms=1200,
        created_at=created_at or datetime.now(timezone.utc),
    )
    session.add(run)
    return run


@pytest.fixture
def seeded(api_client):
    """Seed two datasets/conversations with several QueryRun rows.

    Depends on `api_client` so the isolated-DB monkeypatch (conftest) is
    already applied to the shared session factory before we seed.
    """
    from db.models import Conversation, Dataset
    from db.session import create_db_session

    now = datetime.now(timezone.utc)
    with create_db_session() as s:
        s.add(Dataset(id="ds1", name="a.csv", status="ready"))
        s.add(Dataset(id="ds2", name="b.csv", status="ready"))
        s.add(Conversation(id="cv1", dataset_id="ds1", title="c1"))
        s.add(Conversation(id="cv2", dataset_id="ds2", title="c2"))
        s.flush()
        # Two runs today on ds1/cv1
        _seed(s, id="r1", conversation_id="cv1", dataset_id="ds1",
              prompt_tokens=100, completion_tokens=50, cost=0.001,
              created_at=now - timedelta(minutes=5))
        _seed(s, id="r2", conversation_id="cv1", dataset_id="ds1",
              status="execution_error", prompt_tokens=200, completion_tokens=80,
              cost=0.003, created_at=now - timedelta(minutes=1))
        # One run today on ds2/cv2
        _seed(s, id="r3", conversation_id="cv2", dataset_id="ds2",
              prompt_tokens=300, completion_tokens=100, cost=0.005,
              created_at=now - timedelta(minutes=2))
        # One old run (10 days ago) on ds1/cv1
        _seed(s, id="r_old", conversation_id="cv1", dataset_id="ds1",
              prompt_tokens=999, completion_tokens=999, cost=0.5,
              created_at=now - timedelta(days=10))
    return api_client


# --------------------------------------------------------------------------
# GET /query-runs
# --------------------------------------------------------------------------

def test_query_runs_happy_path_returns_all_with_shape(seeded):
    resp = seeded.get("/query-runs")
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["total"] == 4
    assert len(data["query_runs"]) == 4
    # Newest first.
    assert data["query_runs"][0]["id"] == "r2"
    item = data["query_runs"][0]
    for field in (
        "id", "execution_status", "generated_code", "answer_text",
        "key_numbers", "result_table", "follow_up_suggestions", "anomalies",
        "step_count", "prompt_tokens", "completion_tokens",
        "estimated_cost_usd", "latency_ms", "question_text", "created_at",
    ):
        assert field in item, f"missing {field}"
    assert item["result_table"] is None


def test_query_runs_filter_by_dataset_and_conversation(seeded):
    resp = seeded.get("/query-runs", params={"dataset_id": "ds2"})
    ids = {r["id"] for r in resp.json()["data"]["query_runs"]}
    assert ids == {"r3"}

    resp = seeded.get("/query-runs", params={"conversation_id": "cv1"})
    ids = {r["id"] for r in resp.json()["data"]["query_runs"]}
    assert ids == {"r1", "r2", "r_old"}


def test_query_runs_filter_by_execution_status(seeded):
    resp = seeded.get("/query-runs", params={"execution_status": "execution_error"})
    ids = {r["id"] for r in resp.json()["data"]["query_runs"]}
    assert ids == {"r2"}


def test_query_runs_filter_by_date_range_excludes_old(seeded):
    today = datetime.now(timezone.utc).date().isoformat()
    resp = seeded.get("/query-runs", params={"from": today})
    ids = {r["id"] for r in resp.json()["data"]["query_runs"]}
    assert ids == {"r1", "r2", "r3"}
    assert "r_old" not in ids


def test_query_runs_pagination(seeded):
    # Page 1: 2 of 4.
    resp = seeded.get("/query-runs", params={"limit": 2, "offset": 0})
    data = resp.json()["data"]
    assert data["total"] == 4
    assert [r["id"] for r in data["query_runs"]] == ["r2", "r3"]
    # Page 2.
    resp = seeded.get("/query-runs", params={"limit": 2, "offset": 2})
    data = resp.json()["data"]
    assert [r["id"] for r in data["query_runs"]] == ["r1", "r_old"]


def test_query_runs_empty_result(seeded):
    resp = seeded.get("/query-runs", params={"dataset_id": "does-not-exist"})
    data = resp.json()["data"]
    assert data["total"] == 0
    assert data["query_runs"] == []


def test_query_runs_invalid_from_returns_400(seeded):
    resp = seeded.get("/query-runs", params={"from": "not-a-date"})
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "BAD_REQUEST"


# --------------------------------------------------------------------------
# GET /cost-summary
# --------------------------------------------------------------------------

def test_cost_summary_all_rolls_up_everything(seeded):
    resp = seeded.get("/cost-summary", params={"scope": "all"})
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["scope"] == "all"
    assert data["date"] is None
    assert data["query_count"] == 4
    # tokens = (150 + 280 + 400 + 1998); cost = 0.001+0.003+0.005+0.5
    assert data["total_tokens"] == 150 + 280 + 400 + 1998
    assert data["total_cost_usd"] == pytest.approx(0.509, abs=1e-6)


def test_cost_summary_day_excludes_old_run(seeded):
    resp = seeded.get("/cost-summary", params={"scope": "day"})
    data = resp.json()["data"]
    assert data["scope"] == "day"
    assert data["date"] == datetime.now().astimezone().date().isoformat()
    assert data["query_count"] == 3
    assert data["total_tokens"] == 150 + 280 + 400
    assert data["total_cost_usd"] == pytest.approx(0.009, abs=1e-6)


def test_cost_summary_session_scoped_to_conversation(seeded):
    resp = seeded.get(
        "/cost-summary", params={"scope": "session", "conversation_id": "cv2"}
    )
    data = resp.json()["data"]
    assert data["scope"] == "session"
    assert data["query_count"] == 1
    assert data["total_tokens"] == 400
    assert data["total_cost_usd"] == pytest.approx(0.005, abs=1e-6)


def test_cost_summary_session_without_conversation_id_400(seeded):
    resp = seeded.get("/cost-summary", params={"scope": "session"})
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "BAD_REQUEST"


def test_cost_summary_invalid_scope_400(seeded):
    resp = seeded.get("/cost-summary", params={"scope": "century"})
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "BAD_REQUEST"


def test_cost_summary_all_empty_db_returns_zeros(api_client):
    resp = api_client.get("/cost-summary", params={"scope": "all"})
    data = resp.json()["data"]
    assert data["query_count"] == 0
    assert data["total_tokens"] == 0
    assert data["total_cost_usd"] == 0.0
