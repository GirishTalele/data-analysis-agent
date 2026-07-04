"""Phase 1: email composition, MIME structure, and chart-validity tests.

Ownership note: chart-PNG-structural-validity assertions (PIL.Image.open
succeeds, non-trivial dimensions) belong to the aggregation/chart-rendering
slice and are appended above the marker below. Email-body-rendering and
MIME-structure assertions (the email-composition-and-SMTP-send slice) live
below the marker and must never be removed/rewritten by another slice.
"""

import base64
import smtplib

import pytest

from domain.report import ReportBundle
from reporting.email_body import render_html, render_plain_text
from reporting.mailer import SmtpSendError, build_message, send_email

# --- email composition / MIME tests (slice-3) ---

# A real, structurally-valid 1x1 transparent PNG (PIL.Image.open succeeds on it).
_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)

_PLANT_TABLE_HTML = (
    "<table><thead><tr><th>Plant</th><th>GR Value (Cr)</th></tr></thead>"
    "<tbody><tr><td>1010</td><td>12.34</td></tr></tbody>"
    "<tfoot><tr><td>Total</td><td>12.34</td></tr></tfoot></table>"
)


def _full_bundle(**overrides) -> ReportBundle:
    defaults = dict(
        plant_chart_png=_TINY_PNG,
        plant_table_html=_PLANT_TABLE_HTML,
        buyer_chart_png=_TINY_PNG,
        period_label="Jun 2026",
        excluded_row_count=0,
        warnings=[],
    )
    defaults.update(overrides)
    return ReportBundle(**defaults)


class TestRenderHtml:
    def test_full_report_includes_both_charts_and_table(self):
        html = render_html(_full_bundle(), "GR_Export_Jun2026.csv")
        assert "cid:plant_chart" in html
        assert "cid:buyer_chart" in html
        assert "<table" in html
        assert "Total" in html
        assert "GR_Export_Jun2026.csv" in html
        assert "Jun 2026" in html

    def test_no_warning_banner_when_no_warnings(self):
        html = render_html(_full_bundle(warnings=[]), "f.csv")
        assert "incomplete" not in html.lower()

    def test_warning_banner_present_and_verbatim_when_warnings(self):
        warning_text = (
            "Top-10 Buyer chart could not be generated: no recognizable "
            "Buyer column found in the source file."
        )
        html = render_html(_full_bundle(warnings=[warning_text]), "f.csv")
        assert warning_text in html
        assert "incomplete" in html.lower()

    def test_plant_section_omitted_entirely_when_plant_missing(self):
        """P1: no broken/empty placeholder — the whole section disappears."""
        html = render_html(
            _full_bundle(plant_chart_png=None, plant_table_html=None), "f.csv"
        )
        assert "cid:plant_chart" not in html
        assert _PLANT_TABLE_HTML not in html
        assert "Plant-wise GR Value" not in html
        assert "cid:buyer_chart" in html

    def test_buyer_section_omitted_entirely_when_buyer_missing(self):
        """P2: no broken/empty placeholder — the whole section disappears."""
        html = render_html(_full_bundle(buyer_chart_png=None), "f.csv")
        assert "cid:buyer_chart" not in html
        assert "cid:plant_chart" in html
        assert "<table" in html

    def test_period_placeholder_rendered_verbatim(self):
        """P3: the period line falls back to the placeholder text, unmodified."""
        html = render_html(
            _full_bundle(period_label="Reporting period could not be determined"),
            "f.csv",
        )
        assert "Reporting period could not be determined" in html


class TestRenderPlainText:
    def test_plain_text_contains_filename_period_and_warnings(self):
        text = render_plain_text(
            _full_bundle(warnings=["some warning text"]), "GR_Export.csv"
        )
        assert "GR_Export.csv" in text
        assert "Jun 2026" in text
        assert "some warning text" in text
        assert "HTML-capable" in text
        assert "<" not in text

    def test_plain_text_omits_warnings_section_when_none(self):
        text = render_plain_text(_full_bundle(warnings=[]), "f.csv")
        assert "Warnings:" not in text


class TestBuildMessageMimeStructure:
    def _build(self, **overrides):
        defaults = dict(
            recipients=["a@example.com", "b@example.com"],
            subject="GR Report — Jun 2026 — f.csv",
            html_body=(
                '<html><body><img src="cid:plant_chart">'
                '<img src="cid:buyer_chart"></body></html>'
            ),
            plain_body="plain fallback",
            from_address="agent@company.com",
            plant_chart_png=_TINY_PNG,
            buyer_chart_png=_TINY_PNG,
        )
        defaults.update(overrides)
        return build_message(**defaults)

    def test_root_is_multipart_related(self):
        msg = self._build()
        assert msg.get_content_type() == "multipart/related"

    def test_contains_multipart_alternative_with_plain_and_html(self):
        msg = self._build()
        content_types = [part.get_content_type() for part in msg.walk()]
        assert "multipart/alternative" in content_types
        assert "text/plain" in content_types
        assert "text/html" in content_types

    def test_image_parts_have_matching_content_ids(self):
        msg = self._build()
        image_parts = [p for p in msg.walk() if p.get_content_type() == "image/png"]
        assert len(image_parts) == 2
        cids = {p.get("Content-ID", "").strip("<>") for p in image_parts}
        assert cids == {"plant_chart", "buyer_chart"}
        for part in image_parts:
            assert part.get("Content-Disposition", "").startswith("inline")

    def test_html_part_references_matching_cids(self):
        msg = self._build()
        html_part = next(p for p in msg.walk() if p.get_content_type() == "text/html")
        html_content = html_part.get_content()
        assert "cid:plant_chart" in html_content
        assert "cid:buyer_chart" in html_content

    def test_only_present_charts_are_attached(self):
        msg = self._build(buyer_chart_png=None)
        image_parts = [p for p in msg.walk() if p.get_content_type() == "image/png"]
        assert len(image_parts) == 1
        assert image_parts[0].get("Content-ID", "").strip("<>") == "plant_chart"

    def test_no_image_parts_when_both_charts_missing(self):
        msg = self._build(plant_chart_png=None, buyer_chart_png=None)
        image_parts = [p for p in msg.walk() if p.get_content_type() == "image/png"]
        assert image_parts == []
        assert msg.get_content_type() == "multipart/related"

    def test_headers_set_correctly(self):
        msg = self._build()
        assert msg["Subject"] == "GR Report — Jun 2026 — f.csv"
        assert msg["From"] == "agent@company.com"
        assert "a@example.com" in msg["To"]
        assert "b@example.com" in msg["To"]

    def test_requires_at_least_one_recipient(self):
        with pytest.raises(ValueError):
            self._build(recipients=[])

    def test_composed_message_serializes_with_expected_content_ids(self):
        raw = bytes(self._build())
        assert b"multipart/related" in raw
        assert b"Content-ID: plant_chart" in raw
        assert b"Content-ID: buyer_chart" in raw


class TestSendEmailErrorHandling:
    """Unit-level (mocked SMTP) error-path coverage — distinct from the real
    integration send in test_smtp_real_send.py. Proves send_email never
    swallows an SMTP failure and never leaks the password."""

    def test_connection_failure_raises_smtp_send_error(self, monkeypatch):
        class _FailingSmtp:
            def __init__(self, *args, **kwargs):
                raise ConnectionRefusedError("connection refused")

        monkeypatch.setattr(smtplib, "SMTP", _FailingSmtp)

        with pytest.raises(SmtpSendError) as exc_info:
            send_email(
                recipients=["a@example.com"],
                subject="GR Report — Jun 2026 — f.csv",
                html_body="<html><body>hi</body></html>",
                plain_body="hi",
            )
        assert "super-secret" not in str(exc_info.value)

    def test_auth_failure_raises_smtp_send_error_without_leaking_password(
        self, monkeypatch
    ):
        class _AuthFailingSmtp:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def starttls(self):
                pass

            def login(self, username, password):
                assert password  # the real password value was passed to login()
                raise smtplib.SMTPAuthenticationError(535, b"Authentication failed")

            def send_message(self, msg):
                raise AssertionError("send_message must not be reached after login failure")

        monkeypatch.setattr(smtplib, "SMTP", _AuthFailingSmtp)
        monkeypatch.setenv("AGENT_SMTP_USERNAME", "svc-account")
        monkeypatch.setenv("AGENT_SMTP_PASSWORD", "super-secret-password")

        with pytest.raises(SmtpSendError) as exc_info:
            send_email(
                recipients=["a@example.com"],
                subject="subj",
                html_body="<html><body>hi</body></html>",
                plain_body="hi",
            )

        assert "super-secret-password" not in str(exc_info.value)
        assert "super-secret-password" not in repr(exc_info.value)
