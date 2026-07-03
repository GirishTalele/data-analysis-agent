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


# --- Phase 2 -------------------------------------------------------------


class JoinDatasetsRequest(BaseModel):
    """Body for `POST /datasets/join` (spec/api.md -> Phase 2)."""

    dataset_ids: list[str] = Field(..., min_length=2)
    join_on: str = Field(..., min_length=1)
    how: str = Field(default="inner")


class ExportDatasetRequest(BaseModel):
    """Body for `POST /datasets/{id}/export` (spec/api.md -> Phase 2)."""

    query_run_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)


class DerivedDatasetResponse(BaseModel):
    """`derived_dataset` object in `POST /datasets/{id}/export` (spec/api.md)."""

    id: str
    name: str
    row_count: int
    download_url: str


class DerivedDatasetListItem(BaseModel):
    """One derived dataset in `GET /datasets/{id}/derived` (spec/data.md#DerivedDataset)."""

    id: str
    source_dataset_id: str
    created_from_query_run_id: str | None = None
    name: str
    row_count: int
    download_url: str
    created_at: datetime
