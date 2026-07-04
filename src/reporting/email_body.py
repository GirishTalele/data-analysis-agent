"""Renders the GR report email body (HTML + plain-text fallback) from a `ReportBundle`.

See `spec/architecture.md -> Email MIME Structure` and `-> Error Handling &
Reliability Model` (P1/P2/P3 partial-report rules) for the exact content
contract: a section is omitted entirely (never shown broken/empty) when its
backing `ReportBundle` field is `None`.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from domain.report import ReportBundle

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"

_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "j2", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


def render_html(bundle: ReportBundle, source_filename: str) -> str:
    """Renders the HTML email body for one `ReportBundle`.

    Each chart/table section is included only when its backing field is
    present on the bundle — a missing Plant or Buyer column (P1/P2) omits
    that whole section rather than rendering a broken/empty placeholder.
    """
    template = _env.get_template("report_email.html.j2")
    has_plant = bundle.plant_chart_png is not None and bundle.plant_table_html is not None
    has_buyer = bundle.buyer_chart_png is not None
    return template.render(
        source_filename=source_filename,
        period_label=bundle.period_label,
        warnings=bundle.warnings,
        has_plant=has_plant,
        plant_table_html=bundle.plant_table_html,
        has_buyer=has_buyer,
    )


def render_plain_text(bundle: ReportBundle, source_filename: str) -> str:
    """Renders the plain-text fallback summary for email clients without HTML support."""
    lines = [
        "GR Report",
        f"Source file: {source_filename}",
        f"Reporting period: {bundle.period_label}",
    ]
    if bundle.warnings:
        lines.append("")
        lines.append("Warnings:")
        lines.extend(f"- {warning}" for warning in bundle.warnings)
    lines.append("")
    lines.append(
        "This report includes charts and a data table. "
        "Please view it in an HTML-capable email client to see them."
    )
    return "\n".join(lines)
