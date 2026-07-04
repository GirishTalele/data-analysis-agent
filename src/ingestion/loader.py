"""Load raw upload bytes (.csv or .qvd) into an in-memory LoadedDataset.

Per `spec/architecture.md -> pyqvd Integration`: `.csv` files are read
directly from the in-memory upload stream via `pandas.read_csv` and never
touch disk. `.qvd` files require a filesystem path (pyqvd's real, verified
API is `QvdTable.from_qvd(path).to_pandas()` -- confirmed against the
installed package, matching the architecture doc's assumption exactly), so
the uploaded bytes are written to a short-lived `tempfile.NamedTemporaryFile`
and the temp file is deleted in a `finally` block regardless of whether
parsing succeeds or fails.
"""

from __future__ import annotations

import io
import os
import tempfile

import pandas as pd
from pyqvd import QvdTable

from domain.report import LoadedDataset

_SUPPORTED_EXTENSIONS = {"csv", "qvd"}


class UnsupportedFileTypeError(ValueError):
    """Extension is not .csv/.qvd (case-insensitive). Maps to F1 / UNSUPPORTED_FILE_TYPE."""


class FileUnreadableError(ValueError):
    """File bytes could not be parsed at all, or parsed to zero data rows.

    Maps to F2 / FILE_UNREADABLE.
    """


def load_file(file_bytes: bytes, filename: str) -> LoadedDataset:
    """Parse uploaded file bytes into a LoadedDataset.

    Raises:
        UnsupportedFileTypeError: extension is not .csv/.qvd (case-insensitive).
        FileUnreadableError: bytes are corrupt/empty, or parse to zero rows.
    """
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in _SUPPORTED_EXTENSIONS:
        raise UnsupportedFileTypeError(
            f"Unsupported file extension: .{extension or '(none)'} — only .csv and .qvd are supported."
        )

    dataframe = _load_csv(file_bytes) if extension == "csv" else _load_qvd(file_bytes)

    if dataframe.empty:
        raise FileUnreadableError("File contains zero data rows.")

    return LoadedDataset(
        dataframe=dataframe,
        source_filename=filename,
        row_count=len(dataframe),
    )


def _load_csv(file_bytes: bytes) -> pd.DataFrame:
    try:
        return pd.read_csv(io.BytesIO(file_bytes))
    except Exception as exc:
        raise FileUnreadableError(f"Could not parse CSV file: {exc}") from exc


def _load_qvd(file_bytes: bytes) -> pd.DataFrame:
    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".qvd", delete=False) as tmp_file:
            tmp_file.write(file_bytes)
            tmp_path = tmp_file.name
        return QvdTable.from_qvd(tmp_path).to_pandas()
    except Exception as exc:
        # pyqvd's own reader opens the file handle itself and only closes it
        # on the success path (see pyqvd.io.reader.QvdFileReader.read()) — on
        # a parse failure the handle leaks. On Windows that keeps an OS-level
        # lock on tmp_path for as long as this exception's traceback is
        # reachable, which would make the os.remove() below raise
        # PermissionError. Dropping the original traceback here breaks that
        # reference chain so the temp file can always be deleted below.
        message = f"Could not parse QVD file: {exc}"
        exc.__traceback__ = None
        raise FileUnreadableError(message) from None
    finally:
        if tmp_path is not None and os.path.exists(tmp_path):
            os.remove(tmp_path)
