"""Phase 1: real SMTP integration test.

Sends an actual email via the credentials configured in `.env`
(`AGENT_SMTP_*`), addressed to the service account's own mailbox
(`AGENT_SMTP_FROM_ADDRESS`) so this is a genuine real send without spamming a
third party. Skips only when SMTP credentials are genuinely absent from
`.env` — the same real-key-required discipline as an LLM integration test,
applied to SMTP (see `spec/roadmap.md`).

`_SmtpConfig` (not raw `os.environ`) is used to check presence/read the
from-address because settings are loaded by `pydantic-settings` directly
from the `.env` file — they are not necessarily exported into the process
environment.
"""

import pytest

from reporting.mailer import _SmtpConfig, send_email

_config = _SmtpConfig()
_SMTP_CONFIGURED = bool(_config.host) and bool(_config.username)


@pytest.mark.skipif(
    not _SMTP_CONFIGURED,
    reason=(
        "AGENT_SMTP_HOST/AGENT_SMTP_USERNAME not set in .env — "
        "skipping real SMTP send (real-key-required discipline)"
    ),
)
def test_real_smtp_send_to_self_succeeds():
    """No exception raised == a genuine, successful real send via the
    configured SMTP server, addressed to the service account's own mailbox."""
    from_address = _config.from_address
    assert from_address, "AGENT_SMTP_FROM_ADDRESS must be set in .env for this test"

    html_body = (
        "<html><body>"
        "<p>GR Report Agent — Phase 1 SMTP integration test.</p>"
        "<p>This is an automated test send; no action needed.</p>"
        "</body></html>"
    )
    plain_body = (
        "GR Report Agent — Phase 1 SMTP integration test.\n"
        "This is an automated test send; no action needed."
    )

    send_email(
        recipients=[from_address],
        subject="GR Report Agent — SMTP integration test",
        html_body=html_body,
        plain_body=plain_body,
    )
