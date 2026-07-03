"""DB layer tests for the domain schema (spec/data.md) — no LLM key required."""
from sqlalchemy.orm import Session

from db.models import (
    ChatMessage,
    Conversation,
    Dataset,
    DatasetFile,
    DatasetProfile,
    QueryRun,
)


def _make_dataset(s: Session, **overrides) -> Dataset:
    ds = Dataset(name="sales_q1.csv", kind="single_file", status="ready", **overrides)
    s.add(ds)
    s.commit()
    return ds


def test_dataset_roundtrip(_isolated_db):
    with Session(_isolated_db) as s:
        ds = _make_dataset(s)
        ds_id = ds.id

    with Session(_isolated_db) as s:
        fetched = s.get(Dataset, ds_id)
        assert fetched is not None
        assert fetched.name == "sales_q1.csv"
        assert fetched.kind == "single_file"
        assert fetched.status == "ready"
        assert fetched.created_at is not None
        assert fetched.updated_at is not None


def test_dataset_defaults(_isolated_db):
    """`kind` defaults to single_file and `status` defaults to profiling on insert."""
    with Session(_isolated_db) as s:
        ds = Dataset(name="untouched.csv")
        s.add(ds)
        s.commit()
        ds_id = ds.id

    with Session(_isolated_db) as s:
        fetched = s.get(Dataset, ds_id)
        assert fetched.kind == "single_file"
        assert fetched.status == "profiling"


def test_dataset_file_roundtrip(_isolated_db):
    with Session(_isolated_db) as s:
        ds = _make_dataset(s)
        f = DatasetFile(
            dataset_id=ds.id,
            original_filename="sales_q1.csv",
            stored_path="datasets/abc/original/sales_q1.csv",
            file_type="csv",
            size_bytes=2048,
            row_count=12000,
        )
        s.add(f)
        s.commit()
        f_id = f.id

    with Session(_isolated_db) as s:
        fetched = s.get(DatasetFile, f_id)
        assert fetched is not None
        assert fetched.file_type == "csv"
        assert fetched.row_count == 12000
        assert fetched.uploaded_at is not None


def test_dataset_profile_roundtrip_and_json_columns(_isolated_db):
    columns = [
        {
            "name": "amount",
            "dtype": "float64",
            "missing_count": 12,
            "missing_pct": 0.1,
            "unique_count": None,
            "sample_values": [1.0, 2.5],
            "min": 0.0,
            "max": 4200.5,
            "mean": 88.4,
        }
    ]
    with Session(_isolated_db) as s:
        ds = _make_dataset(s)
        profile = DatasetProfile(
            dataset_id=ds.id,
            row_count=12000,
            column_count=8,
            columns_json=columns,
        )
        s.add(profile)
        s.commit()
        profile_id = profile.id

    with Session(_isolated_db) as s:
        fetched = s.get(DatasetProfile, profile_id)
        assert fetched is not None
        assert fetched.row_count == 12000
        assert fetched.column_count == 8
        assert fetched.columns_json == columns
        assert fetched.generated_at is not None


def test_dataset_profile_history_retained(_isolated_db):
    """History is retained (not overwritten) — spec/data.md#DatasetProfile."""
    with Session(_isolated_db) as s:
        ds = _make_dataset(s)
        p1 = DatasetProfile(dataset_id=ds.id, row_count=100, column_count=3, columns_json=[])
        s.add(p1)
        s.commit()
        p2 = DatasetProfile(dataset_id=ds.id, row_count=150, column_count=3, columns_json=[])
        s.add(p2)
        s.commit()
        ds_id = ds.id

    with Session(_isolated_db) as s:
        profiles = (
            s.query(DatasetProfile)
            .filter(DatasetProfile.dataset_id == ds_id)
            .order_by(DatasetProfile.generated_at)
            .all()
        )
        assert len(profiles) == 2
        assert profiles[-1].row_count == 150


def test_conversation_roundtrip(_isolated_db):
    with Session(_isolated_db) as s:
        ds = _make_dataset(s)
        conv = Conversation(dataset_id=ds.id, title="Untitled analysis")
        s.add(conv)
        s.commit()
        conv_id = conv.id

    with Session(_isolated_db) as s:
        fetched = s.get(Conversation, conv_id)
        assert fetched is not None
        assert fetched.title == "Untitled analysis"
        assert fetched.created_at is not None
        assert fetched.updated_at is not None


def test_chat_message_roundtrip_with_and_without_query_run(_isolated_db):
    with Session(_isolated_db) as s:
        ds = _make_dataset(s)
        conv = Conversation(dataset_id=ds.id, title="Untitled analysis")
        s.add(conv)
        s.commit()

        user_msg = ChatMessage(
            conversation_id=conv.id, role="user", content="What's the average?"
        )
        s.add(user_msg)
        s.commit()

        run = QueryRun(
            conversation_id=conv.id,
            dataset_id=ds.id,
            question_text="What's the average?",
            execution_status="success",
            answer_text="The average is 88.4.",
        )
        s.add(run)
        s.commit()

        assistant_msg = ChatMessage(
            conversation_id=conv.id,
            role="assistant",
            content="The average is 88.4.",
            query_run_id=run.id,
        )
        s.add(assistant_msg)
        s.commit()
        user_id, assistant_id = user_msg.id, assistant_msg.id

    with Session(_isolated_db) as s:
        fetched_user = s.get(ChatMessage, user_id)
        fetched_assistant = s.get(ChatMessage, assistant_id)
        assert fetched_user.query_run_id is None
        assert fetched_assistant.query_run_id is not None


def test_query_run_roundtrip_full_audit_trail(_isolated_db):
    with Session(_isolated_db) as s:
        ds = _make_dataset(s)
        conv = Conversation(dataset_id=ds.id, title="Untitled analysis")
        s.add(conv)
        s.commit()

        run = QueryRun(
            conversation_id=conv.id,
            dataset_id=ds.id,
            question_text="What's the average order amount?",
            generated_code="result = df['amount'].mean()",
            step_count=1,
            execution_status="success",
            result_summary_json={"average_amount": 88.4},
            answer_text="The average order amount is $88.40.",
            follow_up_suggestions_json=[],
            anomalies_json=[],
            prompt_tokens=812,
            completion_tokens=96,
            estimated_cost_usd=0.0016,
            latency_ms=4210,
        )
        s.add(run)
        s.commit()
        run_id = run.id

    with Session(_isolated_db) as s:
        fetched = s.get(QueryRun, run_id)
        assert fetched is not None
        assert fetched.execution_status == "success"
        assert fetched.result_summary_json == {"average_amount": 88.4}
        assert fetched.prompt_tokens == 812
        assert fetched.estimated_cost_usd == 0.0016
        assert fetched.error_message is None


def test_query_run_failed_status_with_error_message(_isolated_db):
    with Session(_isolated_db) as s:
        ds = _make_dataset(s)
        conv = Conversation(dataset_id=ds.id, title="Untitled analysis")
        s.add(conv)
        s.commit()

        run = QueryRun(
            conversation_id=conv.id,
            dataset_id=ds.id,
            question_text="???",
            execution_status="failed",
            error_message="Gemini API call failed: timeout",
            prompt_tokens=0,
            completion_tokens=0,
            estimated_cost_usd=0.0,
            latency_ms=1000,
        )
        s.add(run)
        s.commit()
        run_id = run.id

    with Session(_isolated_db) as s:
        fetched = s.get(QueryRun, run_id)
        assert fetched.execution_status == "failed"
        assert fetched.generated_code is None
        assert fetched.error_message == "Gemini API call failed: timeout"
