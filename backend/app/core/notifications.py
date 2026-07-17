"""Notification adapters.

Shared across every module (Identity, Onboarding, ...) rather than
duplicated per module — in the target architecture, no module sends
email/SMS itself; each publishes a command that the Notification module
(a separate module, not yet built) picks up and delivers (Identity spec
section 20.1; Onboarding spec section 23). Until that module exists,
these adapters ARE the delivery mechanism, called directly from each
module's `OutboxDispatcher` wiring (see e.g.
`app/modules/identity/application/outbox_dispatcher.py`). When the real
Notification module ships, only that wiring changes — service code that
publishes a `notificationCommand` via the outbox does not.

**SMS is mocked, by explicit product decision** — no real SMS provider is
wired up yet. **Email defaults to mocked too** (zero config to run
locally) but includes a genuine SMTP adapter that works with any SMTP
server (Mailhog/Mailtrap locally, or a real provider in production) —
set `EMAIL_PROVIDER=smtp` plus the `SMTP_*` variables to use it.

Important: raw OTPs/verification links are secrets. The mock adapters
deliberately print to stdout directly (bypassing `logging`, which is
filtered but still persisted/shipped in production) so a developer can
complete a flow locally without that value ever touching the application's
real log stream. Do not change mock delivery to use `logger.info(...)`.
"""

from __future__ import annotations

import smtplib
from asyncio import to_thread
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol

from app.core.config import get_settings


@dataclass(slots=True)
class SentMessage:
    channel: str  # EMAIL | SMS
    destination: str
    template_code: str
    parameters: dict


class NotificationPort(Protocol):
    async def send(self, *, destination: str, template_code: str, parameters: dict) -> None: ...


class MockSmsAdapter:
    """Local-development stand-in for a real SMS provider (e.g. Twilio)."""

    channel = "SMS"

    def __init__(self) -> None:
        self.sent: list[SentMessage] = []

    async def send(self, *, destination: str, template_code: str, parameters: dict) -> None:
        masked = _mask_destination(destination)
        message = SentMessage(
            channel="SMS", destination=destination, template_code=template_code, parameters=parameters
        )
        self.sent.append(message)
        print(
            f"\n[MOCK SMS -> {masked}] template={template_code} params={parameters}\n"
            "  (No real SMS provider is configured; this message was not actually sent.)\n"
        )


class MockEmailAdapter:
    channel = "EMAIL"

    def __init__(self) -> None:
        self.sent: list[SentMessage] = []

    async def send(self, *, destination: str, template_code: str, parameters: dict) -> None:
        message = SentMessage(
            channel="EMAIL", destination=destination, template_code=template_code, parameters=parameters
        )
        self.sent.append(message)
        print(
            f"\n[MOCK EMAIL -> {destination}] template={template_code} params={parameters}\n"
        )


class SmtpEmailAdapter:
    """Real email delivery over SMTP. Works with Mailhog/Mailtrap locally
    or any production SMTP relay.
    """

    channel = "EMAIL"

    _SUBJECTS = {
        "IDENTITY_EMAIL_VERIFICATION": "Verify your email address",
        "IDENTITY_PASSWORD_RESET": "Reset your password",
        "IDENTITY_PASSWORD_CHANGED": "Your password was changed",
        "IDENTITY_MFA_ENABLED": "Two-factor authentication enabled",
        "IDENTITY_MFA_DISABLED": "Two-factor authentication disabled",
        "IDENTITY_SUSPICIOUS_LOGIN": "New sign-in to your account",
        "IDENTITY_ACCOUNT_LOCKED": "Your account was temporarily locked",
        "IDENTITY_EMAIL_CHANGED": "Your email address was changed",
        "IDENTITY_MOBILE_CHANGED": "Your mobile number was changed",
        "IDENTITY_ALL_SESSIONS_REVOKED": "You were signed out of all devices",
    }

    def __init__(self) -> None:
        self._settings = get_settings()

    async def send(self, *, destination: str, template_code: str, parameters: dict) -> None:
        await to_thread(self._send_sync, destination, template_code, parameters)

    def _send_sync(self, destination: str, template_code: str, parameters: dict) -> None:
        settings = self._settings
        subject = self._SUBJECTS.get(template_code, "Notification from Health Platform")

        body_lines = [f"{key}: {value}" for key, value in parameters.items()]
        body = "\n".join(body_lines) or "(no additional details)"

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = settings.email_from_address
        msg["To"] = destination
        msg.set_content(body)

        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as client:
            if settings.smtp_use_tls:
                client.starttls()
            if settings.smtp_username and settings.smtp_password:
                client.login(settings.smtp_username, settings.smtp_password)
            client.send_message(msg)


def _mask_destination(value: str) -> str:
    if len(value) <= 4:
        return "*" * len(value)
    return value[:2] + "*" * (len(value) - 4) + value[-2:]


_sms_adapter: MockSmsAdapter | None = None
_email_adapter: NotificationPort | None = None


def get_sms_adapter() -> MockSmsAdapter:
    global _sms_adapter
    if _sms_adapter is None:
        _sms_adapter = MockSmsAdapter()
    return _sms_adapter


def get_email_adapter() -> NotificationPort:
    global _email_adapter
    if _email_adapter is None:
        settings = get_settings()
        _email_adapter = SmtpEmailAdapter() if settings.email_provider == "smtp" else MockEmailAdapter()
    return _email_adapter
