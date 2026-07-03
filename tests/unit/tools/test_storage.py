"""Tests for src/tools/storage.py (spec/architecture.md -> Local File Storage Layout)."""
from pathlib import Path

import pytest

from tools.storage import (
    FileTooLargeError,
    UnsupportedFileTypeError,
    save_uploaded_file,
    validate_extension,
    validate_size,
)


def test_validate_extension_accepts_csv_xlsx_xls():
    assert validate_extension("sales.csv") == "csv"
    assert validate_extension("sales.xlsx") == "xlsx"
    assert validate_extension("sales.xls") == "xls"


def test_validate_extension_rejects_unsupported_type():
    with pytest.raises(UnsupportedFileTypeError):
        validate_extension("sales.txt")


def test_validate_extension_rejects_no_extension():
    with pytest.raises(UnsupportedFileTypeError):
        validate_extension("sales")


def test_validate_size_accepts_within_limit():
    validate_size(1024, max_upload_mb=1)  # 1KB well within 1MB, must not raise


def test_validate_size_rejects_oversized():
    with pytest.raises(FileTooLargeError):
        validate_size(2 * 1024 * 1024, max_upload_mb=1)


def test_save_uploaded_file_writes_to_canonical_layout(tmp_path):
    content = b"id,category\n1,a\n2,b\n"
    stored = save_uploaded_file(
        data_dir=tmp_path,
        dataset_id="ds-123",
        filename="sales.csv",
        content=content,
        max_upload_mb=1,
    )

    expected_abs = tmp_path / "datasets" / "ds-123" / "original" / "sales.csv"
    assert stored.absolute_path == expected_abs
    assert expected_abs.read_bytes() == content
    assert stored.stored_path == "datasets/ds-123/original/sales.csv"
    assert stored.file_type == "csv"
    assert stored.size_bytes == len(content)


def test_save_uploaded_file_rejects_oversized_before_writing(tmp_path):
    content = b"x" * (2 * 1024 * 1024)
    with pytest.raises(FileTooLargeError):
        save_uploaded_file(
            data_dir=tmp_path,
            dataset_id="ds-123",
            filename="sales.csv",
            content=content,
            max_upload_mb=1,
        )
    # Nothing should have been written to disk.
    assert not (tmp_path / "datasets").exists()


def test_save_uploaded_file_rejects_bad_extension(tmp_path):
    with pytest.raises(UnsupportedFileTypeError):
        save_uploaded_file(
            data_dir=tmp_path,
            dataset_id="ds-123",
            filename="sales.pdf",
            content=b"not a spreadsheet",
            max_upload_mb=1,
        )
    assert not (tmp_path / "datasets").exists()


def test_save_uploaded_file_strips_path_traversal(tmp_path):
    stored = save_uploaded_file(
        data_dir=tmp_path,
        dataset_id="ds-123",
        filename="../../evil.csv",
        content=b"id\n1\n",
        max_upload_mb=1,
    )
    assert stored.absolute_path.parent == tmp_path / "datasets" / "ds-123" / "original"
    assert stored.absolute_path.name == "evil.csv"
