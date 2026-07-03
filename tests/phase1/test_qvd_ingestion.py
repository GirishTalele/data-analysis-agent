"""QVD ingestion tests: confirms `ingestion.loader.load_file` uses pyqvd's
real, verified API (`QvdTable.from_qvd(path).to_pandas()`) to correctly parse
`tests/fixtures/gr_export_sample.qvd` into a LoadedDataset, and that no temp
file is left behind afterwards.
"""

import os
import tempfile
from pathlib import Path

import pandas as pd
import pytest

from ingestion.loader import FileUnreadableError, UnsupportedFileTypeError, load_file
from ingestion.columns import detect_columns

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "gr_export_sample.qvd"

EXPECTED_COLUMNS = {"Plant Code", "Buyer Name", "GR Value (INR)", "Posting Date"}
EXPECTED_ROW_COUNT = 5
EXPECTED_GR_VALUES = [100000.0, 250000.5, 75000.25, 300000.0, 125000.75]


@pytest.fixture
def qvd_bytes() -> bytes:
    return FIXTURE_PATH.read_bytes()


def test_qvd_fixture_exists():
    assert FIXTURE_PATH.exists(), "tests/fixtures/gr_export_sample.qvd must be committed"


def test_load_file_parses_qvd_into_expected_column_set(qvd_bytes):
    dataset = load_file(qvd_bytes, "gr_export_sample.qvd")
    assert set(dataset.dataframe.columns) == EXPECTED_COLUMNS


def test_load_file_parses_qvd_into_expected_row_count(qvd_bytes):
    dataset = load_file(qvd_bytes, "gr_export_sample.qvd")
    assert dataset.row_count == EXPECTED_ROW_COUNT
    assert len(dataset.dataframe) == EXPECTED_ROW_COUNT


def test_load_file_parses_qvd_values_correctly(qvd_bytes):
    dataset = load_file(qvd_bytes, "gr_export_sample.qvd")
    actual_values = dataset.dataframe["GR Value (INR)"].astype(float).tolist()
    assert actual_values == pytest.approx(EXPECTED_GR_VALUES)


def test_load_file_preserves_source_filename(qvd_bytes):
    dataset = load_file(qvd_bytes, "gr_export_sample.qvd")
    assert dataset.source_filename == "gr_export_sample.qvd"


def test_qvd_upload_extension_is_case_insensitive(qvd_bytes):
    dataset = load_file(qvd_bytes, "GR_EXPORT_SAMPLE.QVD")
    assert dataset.row_count == EXPECTED_ROW_COUNT


def test_loaded_qvd_dataset_feeds_column_detection_end_to_end(qvd_bytes):
    """Exercises the real load -> detect pipeline stage boundary: a .qvd and
    a .csv containing the same logical data must produce an identical
    ColumnMapping (per file-ingestion-validation.md success criteria)."""
    dataset = load_file(qvd_bytes, "gr_export_sample.qvd")
    mapping = detect_columns(dataset.dataframe)
    assert mapping.plant_column == "Plant Code"
    assert mapping.buyer_column == "Buyer Name"
    assert mapping.gr_value_column == "GR Value (INR)"
    assert mapping.period_column == "Posting Date"


def test_load_file_does_not_leave_temp_files_behind(qvd_bytes):
    before = set(os.listdir(tempfile.gettempdir()))
    load_file(qvd_bytes, "gr_export_sample.qvd")
    after = set(os.listdir(tempfile.gettempdir()))
    assert after - before == set(), "load_file must delete its temp .qvd file in a finally block"


def test_load_file_deletes_temp_file_even_when_pyqvd_raises(monkeypatch):
    """Corrupt QVD bytes: pyqvd fails to parse, but the temp file must still
    be cleaned up (finally block), and FileUnreadableError must be raised."""
    created_paths: list[str] = []
    real_named_tempfile = tempfile.NamedTemporaryFile

    def _tracking_named_tempfile(*args, **kwargs):
        tmp = real_named_tempfile(*args, **kwargs)
        created_paths.append(tmp.name)
        return tmp

    monkeypatch.setattr(tempfile, "NamedTemporaryFile", _tracking_named_tempfile)

    with pytest.raises(FileUnreadableError):
        load_file(b"this is not a valid qvd file", "corrupt.qvd")

    assert created_paths, "expected a temp file to have been created"
    assert not os.path.exists(created_paths[0]), "temp file must be deleted even on failure"


def test_load_file_rejects_unsupported_extension():
    with pytest.raises(UnsupportedFileTypeError):
        load_file(b"hello", "report.txt")


def test_load_file_raises_on_empty_qvd_bytes():
    with pytest.raises(FileUnreadableError):
        load_file(b"", "empty.qvd")
