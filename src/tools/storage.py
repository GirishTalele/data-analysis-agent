"""Local file storage layout for uploaded datasets (spec/architecture.md ->
Local File Storage Layout). Pure functions: no DB access here.

Layout: {data_dir}/datasets/{dataset_id}/original/{filename}
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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
