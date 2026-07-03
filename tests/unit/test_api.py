"""API contract smoke tests for the routers that don't need the real LLM
(`health`, and request-shape validation for `datasets`/`conversations`).
Real integration coverage for `/datasets/*` lives in
tests/integration/test_datasets_api.py and for `/conversations/*` in
tests/integration/test_conversation_flow.py.
"""


def test_health(api_client):
    r = api_client.get("/health")
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "ok"


def test_create_conversation_unknown_dataset_returns_404(api_client):
    r = api_client.post("/datasets/does-not-exist/conversations", json={})
    assert r.status_code == 404


def test_post_message_unknown_conversation_returns_404(api_client):
    r = api_client.post(
        "/conversations/does-not-exist/messages", json={"question": "hello?"}
    )
    assert r.status_code == 404


def test_post_message_missing_question_field_rejected(api_client):
    r = api_client.post("/conversations/does-not-exist/messages", json={})
    assert r.status_code == 422


def test_get_messages_unknown_conversation_returns_404(api_client):
    r = api_client.get("/conversations/does-not-exist/messages")
    assert r.status_code == 404
