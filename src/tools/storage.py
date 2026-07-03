"""Local file storage layout for uploaded datasets (spec/architecture.md ->
Local File Storage Layout). Pure functions: no DB access here.

Layout: {data_dir}/datasets/{dataset_id}/original/{filename}
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from tools.profiling import load_dataframe

# Maps a lowercased file extension to the DatasetFile.file_type value
# (spec/data.md#DatasetFile).
ALLOWED_EXTENSIONS: dict[str, str] = {
    ".csv": "csv",
    ".xlsx": "xlsx",
    ".xls": "xls",
}


class UnsupportedFileTypeError(ValueError):
    """Raised when the uploaded file's extension isn't one we support."""


class FileTooLargeError(ValueError):
    """Raised when the uploaded file exceeds the configured size limit."""


@dataclass(frozen=True)
class StoredFile:
    """Result of saving an uploaded file to local storage."""

    stored_path: str  # relative to data_dir, POSIX-style (spec/data.md#DatasetFile.stored_path)
    absolute_path: Path
    file_type: str
    size_bytes: int


def validate_extension(filename: str) -> str:
    """Return the normalized file_type (csv/xlsx/xls) or raise UnsupportedFileTypeError."""
    ext = Path(filename or "").suffix.lower()
    file_type = ALLOWED_EXTENSIONS.get(ext)
    if file_type is None:
        raise UnsupportedFileTypeError(
            f"Unsupported file type '{ext or filename}'. Allowed types: "
            + ", ".join(sorted(ALLOWED_EXTENSIONS))
        )
    return file_type


def validate_size(size_bytes: int, max_upload_mb: int) -> None:
    """Raise FileTooLargeError if size_bytes exceeds max_upload_mb."""
    max_bytes = max_upload_mb * 1024 * 1024
    if size_bytes > max_bytes:
        raise FileTooLargeError(
            f"File is {size_bytes} bytes, which exceeds the {max_upload_mb}MB limit"
        )


def save_uploaded_file(
    *,
    data_dir: str | Path,
    dataset_id: str,
    filename: str,
    content: bytes,
    max_upload_mb: int,
) -> StoredFile:
    """Validate and persist an uploaded file under the canonical storage layout.

    Raises UnsupportedFileTypeError / FileTooLargeError on invalid input.
    """
    file_type = validate_extension(filename)
    validate_size(len(content), max_upload_mb)

    # Strip any directory components the client may have sent (path-traversal guard).
    safe_filename = Path(filename).name

    data_dir_path = Path(data_dir)
    dest_dir = data_dir_path / "datasets" / dataset_id / "original"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / safe_filename
    dest_path.write_bytes(content)

    relative_path = dest_path.relative_to(data_dir_path)
    return StoredFile(
        stored_path=relative_path.as_posix(),
        absolute_path=dest_path,
        file_type=file_type,
        size_bytes=len(content),
    )


# ---------------------------------------------------------------------------
# Multi-file (folder-as-dataset) support — Phase 2 (spec/data.md#Dataset kind
# "multi_file"). A dataset may be backed by several DatasetFile rows; profiling
# and execution must agree that such a dataset resolves to a single DataFrame
# formed by concatenating (unioning) all its files in a stable order.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FileSpec:
    """A single backing file's stored location + type, relative to data_dir.

    This is the storage-layer contract the API passes in (it owns the DB); it
    keeps this module DB-free, matching the module's "no DB access here" rule.
    """

    stored_path: str  # relative to data_dir (spec/data.md#DatasetFile.stored_path)
    file_type: str


def resolve_dataset_paths(
    data_dir: str | Path, file_specs: Sequence[FileSpec]
) -> list[Path]:
    """Return the ordered list of absolute paths for a dataset's backing files.

    Exposed so the execution layer (src/sandbox / src/graph) can resolve a
    multi-file dataset to the same ordered file list that profiling uses.
    """
    base = Path(data_dir)
    return [base / spec.stored_path for spec in file_specs]


def load_dataset_dataframe(
    data_dir: str | Path, file_specs: Sequence[FileSpec]
) -> pd.DataFrame:
    """Load and vertically concatenate ALL backing files into one DataFrame.

    This is the canonical "one dataset -> one df" resolution shared by
    profiling (re-profiling across the unioned files) and, once wired, by the
    sandbox executor so that aggregate questions are computed over the FULL
    combined data — never a single file or a truncated sample (spec/roadmap.md
    Phase 2 success criterion).

    Files are concatenated in the order given; the caller (the API, which owns
    the DB) is responsible for choosing a stable order (e.g. by uploaded_at).
    Raises ProfilingError (from load_dataframe) if any file is unreadable.
    """
    if not file_specs:
        raise ValueError("Cannot load a dataset with no backing files.")

    base = Path(data_dir)
    frames = [
        load_dataframe(base / spec.stored_path, spec.file_type) for spec in file_specs
    ]
    if len(frames) == 1:
        return frames[0]
    return pd.concat(frames, ignore_index=True)


def derived_csv_path(
    data_dir: str | Path, dataset_id: str, derived_id: str
) -> tuple[Path, str]:
    """Return (absolute_path, stored_path) for a derived/exported CSV.

    Layout: {data_dir}/datasets/{dataset_id}/derived/{derived_id}.csv
    (spec/architecture.md -> Local File Storage Layout).
    """
    base = Path(data_dir)
    dest_dir = base / "datasets" / dataset_id / "derived"
    dest_path = dest_dir / f"{derived_id}.csv"
    return dest_path, dest_path.relative_to(base).as_posix()


def file_specs_from_rows(rows: Iterable) -> list[FileSpec]:
    """Adapt DatasetFile ORM rows (which have .stored_path/.file_type) to FileSpecs."""
    return [FileSpec(stored_path=r.stored_path, file_type=r.file_type) for r in rows]


def list_dataset_files(rows: Iterable) -> list[tuple[str, str]]:
    """Return the ORDERED list of ``(stored_path, file_type)`` backing a dataset.

    The caller (the API/graph layer, which owns the DB) passes DatasetFile rows
    already ordered stably (e.g. by ``uploaded_at`` ascending). This is the
    minimal contract the execution layer needs to resolve a multi-file dataset.
    """
    return [(r.stored_path, r.file_type) for r in rows]


def combined_csv_cache_path(data_dir: str | Path, dataset_id: str) -> Path:
    """Absolute path of the cached concatenated CSV for a multi-file dataset.

    Kept OUTSIDE ``original/`` (a sibling under the dataset dir) so it is never
    re-discovered as one of the dataset's own backing files.
    """
    return Path(data_dir) / "datasets" / dataset_id / "_combined.csv"


def resolve_execution_source(
    data_dir: str | Path, file_specs: Sequence[FileSpec], dataset_id: str
) -> tuple[Path, str]:
    """Return ``(path, file_type)`` ready to hand to ``sandbox.executor.run_code``.

    - Single-file dataset -> the file itself, unchanged.
    - Multi-file dataset -> the backing files are concatenated (unioned) into a
      single cached CSV (``combined_csv_cache_path``) and ``(that_path, "csv")``
      is returned, so the sandbox — which loads exactly one file — computes
      aggregates over the FULL combined data (spec/roadmap.md Phase-2 win).

    This keeps the sandbox executor/runner unchanged: the multi-file union is
    resolved to a single physical file here in the storage layer.
    """
    if not file_specs:
        raise ValueError("Cannot resolve an execution source for a dataset with no files.")
    base = Path(data_dir)
    if len(file_specs) == 1:
        spec = file_specs[0]
        return base / spec.stored_path, spec.file_type

    combined = load_dataset_dataframe(data_dir, file_specs)
    dest = combined_csv_cache_path(data_dir, dataset_id)
    dest.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(dest, index=False)
    return dest, "csv"
