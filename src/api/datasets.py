"""`/datasets` endpoints — upload, retrieve, and re-fetch the profile
(spec/api.md -> POST /datasets, GET /datasets/{id}, GET /datasets/{id}/profile).
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from api._common import api_error, ok
from config.settings import get_settings
from db.models import Dataset, DatasetFile, DatasetProfile, DerivedDataset, QueryRun
from db.session import get_session
from domain.dataset import (
    ColumnProfile,
    DatasetProfileResponse,
    DatasetResponse,
    DatasetWithProfileResponse,
    DerivedDatasetListItem,
    DerivedDatasetResponse,
    ExportDatasetRequest,
    JoinDatasetsRequest,
)
from tools.export import ExportError, result_to_dataframe, write_derived_csv
from tools.joins import (
    InvalidJoinError,
    JoinKeyMissingError,
    join_dataframes,
)
from tools.profiling import ProfilingError, profile_dataframe, profile_file, profile_files
from tools.storage import (
    FileTooLargeError,
    UnsupportedFileTypeError,
    derived_csv_path,
    file_specs_from_rows,
    load_dataset_dataframe,
    resolve_execution_source,
    save_uploaded_file,
)

router = APIRouter()


def _dataset_files_ordered(session: Session, dataset_id: str) -> list[DatasetFile]:
    stmt = (
        select(DatasetFile)
        .where(DatasetFile.dataset_id == dataset_id)
        .order_by(DatasetFile.uploaded_at.asc())
    )
    return list(session.execute(stmt).scalars().all())


def _derived_download_url(dataset_id: str, derived_id: str) -> str:
    return f"/datasets/{dataset_id}/derived/{derived_id}/download"


def _latest_profile(session: Session, dataset_id: str) -> DatasetProfile | None:
    stmt = (
        select(DatasetProfile)
        .where(DatasetProfile.dataset_id == dataset_id)
        .order_by(DatasetProfile.generated_at.desc())
    )
    return session.execute(stmt).scalars().first()


def _profile_response(profile: DatasetProfile) -> DatasetProfileResponse:
    return DatasetProfileResponse(
        row_count=profile.row_count,
        column_count=profile.column_count,
        columns=[ColumnProfile(**c) for c in profile.columns_json],
        generated_at=profile.generated_at,
    )


def _dataset_with_profile(dataset: Dataset, profile: DatasetProfile) -> dict:
    return DatasetWithProfileResponse(
        dataset=DatasetResponse(
            id=dataset.id,
            name=dataset.name,
            kind=dataset.kind,
            status=dataset.status,
            created_at=dataset.created_at,
        ),
        profile=_profile_response(profile),
    ).model_dump()


@router.post("/datasets")
async def create_dataset(
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
) -> dict:
    settings = get_settings()
    content = await file.read()

    dataset = Dataset(name=file.filename or "upload", kind="single_file", status="profiling")
    session.add(dataset)
    session.flush()

    try:
        stored = save_uploaded_file(
            data_dir=settings.data_dir,
            dataset_id=dataset.id,
            filename=file.filename or "upload",
            content=content,
            max_upload_mb=settings.max_upload_mb,
        )
    except (UnsupportedFileTypeError, FileTooLargeError) as exc:
        raise api_error("BAD_FILE", str(exc), 400) from exc
    except OSError as exc:
        raise api_error("STORAGE_ERROR", f"Could not store file: {exc}", 500) from exc

    try:
        profile_data = profile_file(stored.absolute_path, stored.file_type)
    except ProfilingError as exc:
        raise api_error("BAD_FILE", str(exc), 400) from exc
    except Exception as exc:  # unexpected profiling failure, not the file's fault
        raise api_error("PROFILING_ERROR", f"Could not profile file: {exc}", 500) from exc

    dataset_file = DatasetFile(
        dataset_id=dataset.id,
        original_filename=file.filename or "upload",
        stored_path=stored.stored_path,
        file_type=stored.file_type,
        size_bytes=stored.size_bytes,
        row_count=profile_data["row_count"],
    )
    session.add(dataset_file)

    profile = DatasetProfile(
        dataset_id=dataset.id,
        row_count=profile_data["row_count"],
        column_count=profile_data["column_count"],
        columns_json=profile_data["columns"],
    )
    session.add(profile)

    dataset.status = "ready"

    session.flush()
    session.refresh(dataset)
    session.refresh(profile)

    return ok(_dataset_with_profile(dataset, profile))


@router.get("/datasets/{dataset_id}")
def get_dataset(dataset_id: str, session: Session = Depends(get_session)) -> dict:
    dataset = session.get(Dataset, dataset_id)
    if dataset is None:
        raise api_error("NOT_FOUND", f"Dataset '{dataset_id}' not found", 404)
    profile = _latest_profile(session, dataset_id)
    if profile is None:
        raise api_error("NOT_FOUND", f"Dataset '{dataset_id}' has no profile", 404)
    return ok(_dataset_with_profile(dataset, profile))


@router.get("/datasets/{dataset_id}/profile")
def get_dataset_profile(dataset_id: str, session: Session = Depends(get_session)) -> dict:
    dataset = session.get(Dataset, dataset_id)
    if dataset is None:
        raise api_error("NOT_FOUND", f"Dataset '{dataset_id}' not found", 404)
    profile = _latest_profile(session, dataset_id)
    if profile is None:
        raise api_error("NOT_FOUND", f"Dataset '{dataset_id}' has no profile", 404)
    return ok(_profile_response(profile).model_dump())


# ---------------------------------------------------------------------------
# Phase 2 — multi-file (folder-as-dataset), join, and export
# ---------------------------------------------------------------------------


@router.post("/datasets/join")
def join_datasets(
    body: JoinDatasetsRequest,
    session: Session = Depends(get_session),
) -> dict:
    """Create a NEW joined Dataset from >=2 existing datasets (spec/api.md -> POST /datasets/join)."""
    settings = get_settings()

    datasets: list[Dataset] = []
    frames = []
    for ds_id in body.dataset_ids:
        ds = session.get(Dataset, ds_id)
        if ds is None:
            raise api_error("NOT_FOUND", f"Dataset '{ds_id}' not found", 404)
        files = _dataset_files_ordered(session, ds_id)
        if not files:
            raise api_error("BAD_REQUEST", f"Dataset '{ds_id}' has no files to join", 400)
        try:
            frames.append(
                load_dataset_dataframe(settings.data_dir, file_specs_from_rows(files))
            )
        except ProfilingError as exc:
            raise api_error("BAD_FILE", str(exc), 400) from exc
        datasets.append(ds)

    try:
        joined = join_dataframes(frames, join_on=body.join_on, how=body.how)
    except JoinKeyMissingError as exc:
        raise api_error("BAD_REQUEST", str(exc), 400) from exc
    except InvalidJoinError as exc:
        raise api_error("BAD_REQUEST", str(exc), 400) from exc

    name = " ⋈ ".join(d.name for d in datasets)
    new_dataset = Dataset(name=name, kind="joined", status="profiling")
    session.add(new_dataset)
    session.flush()

    profile_data = profile_dataframe(joined)
    profile = DatasetProfile(
        dataset_id=new_dataset.id,
        row_count=profile_data["row_count"],
        column_count=profile_data["column_count"],
        columns_json=profile_data["columns"],
    )
    session.add(profile)
    new_dataset.status = "ready"

    session.flush()
    session.refresh(new_dataset)
    session.refresh(profile)
    return ok(_dataset_with_profile(new_dataset, profile))


@router.post("/datasets/{dataset_id}/files")
async def add_dataset_file(
    dataset_id: str,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
) -> dict:
    """Add another file to an existing dataset and RE-PROFILE across the unioned
    files (spec/api.md -> POST /datasets/{id}/files)."""
    settings = get_settings()

    dataset = session.get(Dataset, dataset_id)
    if dataset is None:
        raise api_error("NOT_FOUND", f"Dataset '{dataset_id}' not found", 404)

    content = await file.read()
    try:
        stored = save_uploaded_file(
            data_dir=settings.data_dir,
            dataset_id=dataset_id,
            filename=file.filename or "upload",
            content=content,
            max_upload_mb=settings.max_upload_mb,
        )
    except (UnsupportedFileTypeError, FileTooLargeError) as exc:
        raise api_error("BAD_FILE", str(exc), 400) from exc
    except OSError as exc:
        raise api_error("STORAGE_ERROR", f"Could not store file: {exc}", 500) from exc

    # Profile just this new file for its own row_count, and validate readability.
    try:
        this_file_profile = profile_file(stored.absolute_path, stored.file_type)
    except ProfilingError as exc:
        raise api_error("BAD_FILE", str(exc), 400) from exc

    dataset_file = DatasetFile(
        dataset_id=dataset_id,
        original_filename=file.filename or "upload",
        stored_path=stored.stored_path,
        file_type=stored.file_type,
        size_bytes=stored.size_bytes,
        row_count=this_file_profile["row_count"],
    )
    session.add(dataset_file)
    session.flush()

    # Re-profile across ALL backing files (the unioned data) — the core Phase-2 win.
    all_files = _dataset_files_ordered(session, dataset_id)
    specs = [
        (str(Path(settings.data_dir) / f.stored_path), f.file_type) for f in all_files
    ]
    try:
        combined_profile = profile_files(specs)
    except ProfilingError as exc:
        raise api_error("BAD_FILE", str(exc), 400) from exc

    profile = DatasetProfile(
        dataset_id=dataset_id,
        row_count=combined_profile["row_count"],
        column_count=combined_profile["column_count"],
        columns_json=combined_profile["columns"],
    )
    session.add(profile)

    dataset.kind = "multi_file"
    dataset.status = "ready"
    dataset.updated_at = datetime.now(timezone.utc)

    session.flush()
    session.refresh(dataset)
    session.refresh(profile)
    return ok(_dataset_with_profile(dataset, profile))


def _rerun_query_for_export(
    settings, dataset_id: str, files: list[DatasetFile], generated_code: str
):
    """Re-execute a QueryRun's code against the dataset's FULL (unioned) data in
    the sandbox and return the raw result. `resolve_execution_source` collapses
    a multi-file dataset to a single combined CSV so the single-path sandbox
    runner sees ALL rows."""
    from sandbox.executor import run_code

    path, file_type = resolve_execution_source(
        settings.data_dir, file_specs_from_rows(files), dataset_id
    )
    return run_code(generated_code, path, file_type)


@router.post("/datasets/{dataset_id}/export")
def export_dataset(
    dataset_id: str,
    body: ExportDatasetRequest,
    session: Session = Depends(get_session),
) -> dict:
    """Materialize a QueryRun's derived data to a local CSV and persist a
    DerivedDataset (spec/api.md -> POST /datasets/{id}/export)."""
    settings = get_settings()

    dataset = session.get(Dataset, dataset_id)
    if dataset is None:
        raise api_error("NOT_FOUND", f"Dataset '{dataset_id}' not found", 404)

    query_run = session.get(QueryRun, body.query_run_id)
    if query_run is None:
        raise api_error("NOT_FOUND", f"Query run '{body.query_run_id}' not found", 404)
    if query_run.dataset_id != dataset_id:
        raise api_error(
            "BAD_REQUEST", "Query run does not belong to this dataset", 400
        )
    if not query_run.generated_code:
        raise api_error(
            "BAD_REQUEST",
            "This query has no executable code to export (it may have failed before "
            "producing any).",
            400,
        )

    files = _dataset_files_ordered(session, dataset_id)
    if not files:
        raise api_error("BAD_REQUEST", f"Dataset '{dataset_id}' has no files", 400)

    exec_result = _rerun_query_for_export(
        settings, dataset_id, files, query_run.generated_code
    )
    if exec_result.error:
        raise api_error(
            "EXPORT_FAILED",
            f"Could not reproduce the query result for export: {exec_result.error}",
            400,
        )

    try:
        df = result_to_dataframe(exec_result.result)
    except ExportError as exc:
        raise api_error("BAD_REQUEST", str(exc), 400) from exc

    derived = DerivedDataset(
        source_dataset_id=dataset_id,
        created_from_query_run_id=query_run.id,
        name=body.name,
        stored_path="",  # set below once we know the id
        row_count=0,
    )
    session.add(derived)
    session.flush()  # populate derived.id

    abs_path, stored_path = derived_csv_path(settings.data_dir, dataset_id, derived.id)
    try:
        row_count = write_derived_csv(abs_path, df)
    except OSError as exc:
        raise api_error("STORAGE_ERROR", f"Could not write export file: {exc}", 500) from exc

    derived.stored_path = stored_path
    derived.row_count = row_count
    session.flush()
    session.refresh(derived)

    return ok(
        {
            "derived_dataset": DerivedDatasetResponse(
                id=derived.id,
                name=derived.name,
                row_count=derived.row_count,
                download_url=_derived_download_url(dataset_id, derived.id),
            ).model_dump()
        }
    )


@router.get("/datasets/{dataset_id}/derived")
def list_derived_datasets(
    dataset_id: str, session: Session = Depends(get_session)
) -> dict:
    """List derived/exported datasets for a dataset (spec/api.md -> GET /datasets/{id}/derived)."""
    dataset = session.get(Dataset, dataset_id)
    if dataset is None:
        raise api_error("NOT_FOUND", f"Dataset '{dataset_id}' not found", 404)

    stmt = (
        select(DerivedDataset)
        .where(DerivedDataset.source_dataset_id == dataset_id)
        .order_by(DerivedDataset.created_at.desc())
    )
    rows = session.execute(stmt).scalars().all()
    items = [
        DerivedDatasetListItem(
            id=d.id,
            source_dataset_id=d.source_dataset_id,
            created_from_query_run_id=d.created_from_query_run_id,
            name=d.name,
            row_count=d.row_count,
            download_url=_derived_download_url(dataset_id, d.id),
            created_at=d.created_at,
        ).model_dump(mode="json")
        for d in rows
    ]
    return ok({"derived_datasets": items})


@router.get("/datasets/{dataset_id}/derived/{derived_id}/download")
def download_derived_dataset(
    dataset_id: str, derived_id: str, session: Session = Depends(get_session)
):
    """Return the exported CSV as a file download (spec/api.md -> export download_url)."""
    settings = get_settings()
    derived = session.get(DerivedDataset, derived_id)
    if derived is None or derived.source_dataset_id != dataset_id:
        raise api_error("NOT_FOUND", f"Derived dataset '{derived_id}' not found", 404)

    abs_path = Path(settings.data_dir) / derived.stored_path
    if not abs_path.exists():
        raise api_error("NOT_FOUND", "Exported file is missing on disk", 404)

    return FileResponse(
        path=str(abs_path),
        media_type="text/csv",
        filename=derived.name if derived.name.endswith(".csv") else f"{derived.name}.csv",
    )
