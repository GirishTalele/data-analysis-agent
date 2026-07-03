"""`/datasets` endpoints — upload, retrieve, and re-fetch the profile
(spec/api.md -> POST /datasets, GET /datasets/{id}, GET /datasets/{id}/profile).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from api._common import api_error, ok
from config.settings import get_settings
from db.models import Dataset, DatasetFile, DatasetProfile
from db.session import get_session
from domain.dataset import (
    ColumnProfile,
    DatasetProfileResponse,
    DatasetResponse,
    DatasetWithProfileResponse,
)
from tools.profiling import ProfilingError, profile_file
from tools.storage import FileTooLargeError, UnsupportedFileTypeError, save_uploaded_file

router = APIRouter()


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
