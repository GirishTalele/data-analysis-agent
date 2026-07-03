"""Builds and sends the GR report email via the company's on-prem SMTP server.

Message construction (`build_message`) is a pure function, kept separate from
the actual network I/O (`send_email`) so the MIME structure can be asserted on
without touching a real SMTP connection. See
`spec/architecture.md -> Email MIME Structure` for the exact structure this
must produce: a `multipart/related` root (so `cid:` references resolve),
containing a `multipart/alternative` (plain + html) and, as siblings of it,
one `image/png` part per chart that is present.

SMTP settings: this module currently reads the six `AGENT_SMTP_*` variables
directly (mirroring the same `pydantic-settings` env-file pattern already
used by `src/config/settings.py`) so it never blocks on a hard dependency to
that shared module. Once `src/config/settings.py` (owned by a different
slice) exposes SMTP fields, `_SmtpConfig` below should be replaced by reading
those fields from `config.settings.get_settings()` instead.
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage, MIMEPart

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from observability.events import get_logger

log = get_logger("reporting.mailer")


class SmtpSendError(RuntimeError):
    """Raised when the report email could not be delivered via SMTP.

    Covers connection failures, authentication failures, and timeouts. Never
    carries the SMTP password — only the exception class name and the
    server's own (non-credential) response text, if any.
    """


class _SmtpConfig(BaseSettings):
    """Local SMTP settings shim — see module docstring."""

    model_config = SettingsConfigDict(
        env_prefix="AGENT_SMTP_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    host: str = Field(default="")
    port: int = Field(default=587)
    username: str = Field(default="")
    password: str = Field(default="")
    from_address: str = Field(default="")
    use_tls: bool = Field(default=True)


def build_message(
    *,
    recipients: list[str],
    subject: str,
    html_body: str,
    plain_body: str,
    from_address: str,
    plant_chart_png: bytes | None = None,
    buyer_chart_png: bytes | None = None,
) -> EmailMessage:
    """Builds the `multipart/related` MIME message. Pure function — no network I/O."""
    if not recipients:
        raise ValueError("build_message requires at least one recipient")

    root = EmailMessage()
    root["Subject"] = subject
    root["From"] = from_address
    root["To"] = ", ".join(recipients)

    alternative = MIMEPart(policy=root.policy)
    alternative.set_content(plain_body)
    alternative.add_alternative(html_body, subtype="html")

    root.make_related()
    root.attach(alternative)

    if plant_chart_png is not None:
        root.add_related(plant_chart_png, maintype="image", subtype="png", cid="plant_chart")
    if buyer_chart_png is not None:
        root.add_related(buyer_chart_png, maintype="image", subtype="png", cid="buyer_chart")

    return root


def send_email(
    recipients: list[str],
    subject: str,
    html_body: str,
    plain_body: str,
    plant_chart_png: bytes | None = None,
    buyer_chart_png: bytes | None = None,
) -> None:
    """Composes and sends the report email via the configured SMTP server.

    Raises `SmtpSendError` on any connection/auth/timeout failure — never
    swallowed, so the caller (the pipeline) can map it to `SMTP_SEND_FAILED`
    (F7) and guarantee no partial send.
    """
    config = _SmtpConfig()
    message = build_message(
        recipients=recipients,
        subject=subject,
        html_body=html_body,
        plain_body=plain_body,
        from_address=config.from_address,
        plant_chart_png=plant_chart_png,
        buyer_chart_png=buyer_chart_png,
    )

    try:
        with smtplib.SMTP(config.host, config.port, timeout=30) as client:
            if config.use_tls:
                client.starttls()
            if config.username:
                client.login(config.username, config.password)
            client.send_message(message)
    except (smtplib.SMTPException, OSError, TimeoutError) as exc:
        log.error(
            "smtp.send_failed",
            error_type=type(exc).__name__,
            host=config.host,
            port=config.port,
        )
        raise SmtpSendError(
            f"Failed to send report email via SMTP ({type(exc).__name__})."
        ) from exc

    log.info(
        "smtp.send_succeeded",
        recipient_count=len(recipients),
        host=config.host,
    )
