from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Text, TIMESTAMP, Integer, Float, JSON, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return str(uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Dataset(Base):
    """One logical dataset the user analyzes (spec/data.md#Dataset)."""

    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False, default="single_file")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="profiling")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_now, onupdate=_now
    )

    files: Mapped[list["DatasetFile"]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan"
    )
    profiles: Mapped[list["DatasetProfile"]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan"
    )
    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan"
    )


class DatasetFile(Base):
    """One physical file backing a Dataset (spec/data.md#DatasetFile)."""

    __tablename__ = "dataset_files"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    dataset_id: Mapped[str] = mapped_column(
        Text, ForeignKey("datasets.id"), nullable=False
    )
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    stored_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_type: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_now
    )

    dataset: Mapped["Dataset"] = relationship(back_populates="files")


class DatasetProfile(Base):
    """Auto-generated profile of a Dataset at a point in time (spec/data.md#DatasetProfile)."""

    __tablename__ = "dataset_profiles"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    dataset_id: Mapped[str] = mapped_column(
        Text, ForeignKey("datasets.id"), nullable=False
    )
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    column_count: Mapped[int] = mapped_column(Integer, nullable=False)
    columns_json: Mapped[list] = mapped_column(JSON, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_now
    )

    dataset: Mapped["Dataset"] = relationship(back_populates="profiles")


class Conversation(Base):
    """A chat session tied to one dataset (spec/data.md#Conversation)."""

    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    dataset_id: Mapped[str] = mapped_column(
        Text, ForeignKey("datasets.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(Text, nullable=False, default="Untitled analysis")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_now, onupdate=_now
    )

    dataset: Mapped["Dataset"] = relationship(back_populates="conversations")
    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )
    query_runs: Mapped[list["QueryRun"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class ChatMessage(Base):
    """One turn in a Conversation (spec/data.md#ChatMessage)."""

    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    conversation_id: Mapped[str] = mapped_column(
        Text, ForeignKey("conversations.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    query_run_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("query_runs.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_now
    )

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


class QueryRun(Base):
    """One row per user question — the full audit trail (spec/data.md#QueryRun)."""

    __tablename__ = "query_runs"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    conversation_id: Mapped[str] = mapped_column(
        Text, ForeignKey("conversations.id"), nullable=False
    )
    dataset_id: Mapped[str] = mapped_column(
        Text, ForeignKey("datasets.id"), nullable=False
    )
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    generated_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    step_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    execution_status: Mapped[str] = mapped_column(Text, nullable=False)
    result_summary_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    key_numbers_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    answer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    clarification_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    follow_up_suggestions_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    anomalies_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_now
    )

    conversation: Mapped["Conversation"] = relationship(back_populates="query_runs")
