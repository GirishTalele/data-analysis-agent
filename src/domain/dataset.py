from datetime import datetime

from pydantic import BaseModel, Field


class ColumnProfile(BaseModel):
    """One column's profile stats — exactly the `schema_context` handed to the LLM.

    Numeric fields (`min`/`max`/`mean`) are `None` for non-numeric columns.
    """

    name: str
    dtype: str
    missing_count: int
    missing_pct: float
    unique_count: int | None = None
    sample_values: list | None = None
    min: float | str | None = None
    max: float | str | None = None
    mean: float | None = None


class DatasetResponse(BaseModel):
    """`dataset` object in `spec/api.md` (`POST /datasets`, `GET /datasets/{id}`)."""

    id: str
    name: str
    kind: str
    status: str
    created_at: datetime


class DatasetProfileResponse(BaseModel):
    """`profile` object in `spec/api.md` (`POST /datasets`, `GET /datasets/{id}/profile`)."""

    row_count: int
    column_count: int
    columns: list[ColumnProfile]
    generated_at: datetime


class DatasetWithProfileResponse(BaseModel):
    """`{dataset, profile}` envelope shared by `POST /datasets` and `GET /datasets/{id}`."""

    dataset: DatasetResponse
    profile: DatasetProfileResponse


class DatasetFileResponse(BaseModel):
    """One physical file backing a Dataset (spec/data.md#DatasetFile)."""

    id: str
    dataset_id: str
    original_filename: str
    stored_path: str
    file_type: str
    size_bytes: int
    row_count: int
    uploaded_at: datetime


class UploadDatasetRequest(BaseModel):
    """Not a JSON body (the endpoint is `multipart/form-data`) — documents the
    non-file fields, if any are ever added. Present for symmetry/completeness."""

    name: str | None = Field(default=None, description="Optional override for the dataset name")
