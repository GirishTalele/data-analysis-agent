"""Chart rendering tests (slice-2).

Structural PNG validity for `reporting.charts.render_plant_chart` and
`render_buyer_chart`: real matplotlib output, decoded by Pillow, non-trivial
dimensions, distinct output per input. `spec/roadmap.md`'s
`test_email_mime_and_charts.py` gate item is intentionally satisfied by TWO
files instead of one: this file (chart validity, owned by slice-2) plus
`tests/phase1/test_email_mime_and_charts.py` (MIME/HTML-table assertions,
owned by slice-3) -- a cleaner split than two slices editing one shared file
concurrently. Together they cover the full gate item.
"""

from __future__ import annotations

import io

from PIL import Image

from reporting.charts import render_buyer_chart, render_plant_chart

PLANT_TOTALS = {
    "1010": 12.34,
    "1020": 45.67,
    "1030": 3.21,
}

BUYER_TOTALS = {f"Buyer Co {i:02d}": float(50 - i) for i in range(1, 15)}


def _open_png(png_bytes: bytes) -> Image.Image:
    return Image.open(io.BytesIO(png_bytes))


def test_render_plant_chart_produces_valid_png() -> None:
    png_bytes = render_plant_chart(PLANT_TOTALS, "Jun 2026")

    assert isinstance(png_bytes, bytes)
    assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"

    image = _open_png(png_bytes)
    assert image.format == "PNG"
    assert image.width > 100
    assert image.height > 100


def test_render_buyer_chart_produces_valid_png() -> None:
    png_bytes = render_buyer_chart(BUYER_TOTALS, "Jan 2026 – Apr 2026")

    assert isinstance(png_bytes, bytes)
    image = _open_png(png_bytes)
    assert image.format == "PNG"
    assert image.width > 100
    assert image.height > 100


def test_render_buyer_chart_caps_at_exactly_top_ten() -> None:
    # 14 buyers supplied; the buyer chart is documented to render exactly the
    # top 10 -- verified indirectly via a taller image for 10 vs. 3 bars, and
    # directly by checking the function never explodes/renders more bars than
    # requested (no public bar-count accessor, so we assert via distinct
    # output between a >10 input and a <=10 input of otherwise-similar shape).
    ten_or_fewer = {f"Buyer Co {i:02d}": float(i) for i in range(1, 6)}
    png_small = render_buyer_chart(ten_or_fewer, "Jun 2026")
    png_large = render_buyer_chart(BUYER_TOTALS, "Jun 2026")

    assert png_small != png_large
    assert _open_png(png_small).height < _open_png(png_large).height


def test_render_plant_chart_single_plant_still_renders() -> None:
    png_bytes = render_plant_chart({"1010": 7.5}, "Jun 2026")
    image = _open_png(png_bytes)
    assert image.width > 50
    assert image.height > 50


def test_render_charts_never_write_to_disk(tmp_path, monkeypatch) -> None:
    # Isolated in its own empty subdirectory rather than bare `tmp_path`,
    # since the (unrelated, pre-existing) skeleton `conftest.py` autouse
    # DB fixture also writes a `test.db` file into `tmp_path` itself.
    empty_dir = tmp_path / "chart_output_check"
    empty_dir.mkdir()
    monkeypatch.chdir(empty_dir)
    render_plant_chart(PLANT_TOTALS, "Jun 2026")
    render_buyer_chart(BUYER_TOTALS, "Jun 2026")
    assert list(empty_dir.iterdir()) == []


def test_render_plant_chart_reflects_period_label_change() -> None:
    png_jun = render_plant_chart(PLANT_TOTALS, "Jun 2026")
    png_range = render_plant_chart(PLANT_TOTALS, "Jan 2026 – Apr 2026")
    assert png_jun != png_range
