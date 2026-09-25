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

    Applied when each record is created, this covers Agent Kernel's own loggers too. Agent Kernel
    names its session logger `ak.core.session [<session id>]`, and the session id is the
    mother's phone number, so the logger *name* is redacted as well.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_text(record.getMessage())
        record.args = ()
        record.name = redact_text(record.name)
        if record.exc_info:
            record.exc_text = redact_text(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = redact_text(record.exc_text)
        if record.stack_info:
            record.stack_info = redact_text(record.stack_info)
        return True


def install() -> None:
    """Redact records before any handler sees them, including non-propagating AK logs.

    Logging configuration can replace handlers after startup. A record factory survives
    that reconfiguration and chains any factory installed by the host application.
    """
    previous_factory = logging.getLogRecordFactory()
    if getattr(previous_factory, "_mathru_phone_redaction", False):
        return
    redaction_filter = PhoneRedactionFilter()

    def factory(*args, **kwargs):
        record = previous_factory(*args, **kwargs)
        redaction_filter.filter(record)
        return record

    factory._mathru_phone_redaction = True
    logging.setLogRecordFactory(factory)
