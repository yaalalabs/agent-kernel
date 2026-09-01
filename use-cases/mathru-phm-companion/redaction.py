"""Phone-number redaction for log output.

Scope matters here. Redaction applies to **logs only**. It must never touch the escalation
path, which needs the PHM's real number to deliver a message, nor the stored records, which
are keyed on the mother's number.

Agent Kernel has no built-in log redaction: the only `pii` setting in the framework is the
WalledAI guardrail's request/response masking, which is a different thing on a different
path. So this is implemented here as a standard `logging.Filter`.
"""

from __future__ import annotations

import logging
import re

# Sri Lankan numbers in the shapes this system handles, plus any bare 9-15 digit run that
# looks like an international subscriber number.
PHONE_PATTERN = re.compile(r"\+?\d{9,15}")

KEEP_TRAILING_DIGITS = 3


def redact_phone(phone: str) -> str:
    """Mask a single phone number, keeping the last three digits for support triage."""
    if not phone:
        return "<empty>"
    return f"***{phone[-KEEP_TRAILING_DIGITS:]}" if len(phone) > KEEP_TRAILING_DIGITS else "***"


def redact_text(text: str) -> str:
    """Mask every phone-number-shaped run inside a block of free text."""
    if not text:
        return text
    return PHONE_PATTERN.sub(lambda match: redact_phone(match.group().lstrip("+")), text)


class PhoneRedactionFilter(logging.Filter):
    """Redacts phone-number-shaped digit runs from log messages and their arguments.

    Attached to the root logger, this covers Agent Kernel's own loggers too. Agent Kernel
    names its session logger `ak.core.session [<session id>]`, and the session id is the
    mother's phone number, so the logger *name* is redacted as well.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_text(record.msg)

        if record.args:
            if isinstance(record.args, dict):
                record.args = {key: self._scrub(value) for key, value in record.args.items()}
            else:
                record.args = tuple(self._scrub(value) for value in record.args)

        record.name = redact_text(record.name)
        return True

    @staticmethod
    def _scrub(value: object) -> object:
        return redact_text(value) if isinstance(value, str) else value


def install() -> None:
    """Attach the redaction filter to the root logger and every existing handler.

    Filters on a logger do not apply to records propagated from child loggers, so the
    filter is attached to the handlers as well, where it sees everything that is emitted.
    """
    root = logging.getLogger()
    redaction_filter = PhoneRedactionFilter()
    root.addFilter(redaction_filter)
    for handler in root.handlers:
        handler.addFilter(redaction_filter)
