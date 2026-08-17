"""Interpretation of a ``ScheduleSpec``'s occurrence rule.

Two collaborators need to read the same rule: the manager validates it before a task is ever
stored, and the local provider computes the next fire time from it. Both resolutions share the
timezone handling and the ``at`` parsing, so they live together here rather than in each caller.

Providers that let their backend interpret the expression (EventBridge Scheduler) do not use
this module.
"""

import datetime
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..core.model import ScheduleSpec
from ..core.util.factory import require_extra

# Number of fields in the standard cron expression the spec accepts (minute, hour, day-of-month,
# month, day-of-week); provider-native flavors are translated by the provider, not accepted here.
CRON_FIELD_COUNT = 5


class OccurrenceCalculator:
    """Resolves a spec's ``at``/``cron``/``timezone`` into concrete occurrence times."""

    @classmethod
    def validate(cls, spec: ScheduleSpec) -> None:
        """Check that the spec's occurrence rule can actually be evaluated.

        Structural validation (exactly one of at/cron, known session_mode) has already run in
        ``ScheduleSpec``; this adds the semantics: a resolvable IANA timezone, a parseable cron
        expression, and an ``at`` timestamp that is ISO-8601, timezone-naive (the spec's
        ``timezone`` field is what places it), and still in the future.

        :param spec: The occurrence rule to validate.
        :raises ValueError: If the timezone, the cron expression, or the ``at`` timestamp is unusable.
        """
        timezone = cls._resolve_timezone(spec.timezone)
        if spec.cron:
            cls._validate_cron(spec.cron)
            return
        occurrence = cls._parse_at(spec.at)
        if occurrence.replace(tzinfo=timezone) <= datetime.datetime.now(timezone):
            raise ValueError(f"schedule 'at' must be in the future: '{spec.at}' has already passed in {spec.timezone}")

    @classmethod
    def next_fire_time(cls, spec: ScheduleSpec, after: Optional[datetime.datetime] = None) -> Optional[datetime.datetime]:
        """Return the first occurrence strictly after ``after``, as an aware datetime.

        :param spec: The occurrence rule to evaluate.
        :param after: The instant to search from; the current time when omitted.
        :return: The next occurrence, or None when the rule has none left (a one-time
                 ``at`` schedule whose timestamp has passed).
        :raises ValueError: If the rule cannot be evaluated (see :meth:`validate`).
        """
        timezone = cls._resolve_timezone(spec.timezone)
        reference = (after or datetime.datetime.now(datetime.timezone.utc)).astimezone(timezone)
        if spec.at:
            occurrence = cls._parse_at(spec.at).replace(tzinfo=timezone)
            return occurrence if occurrence > reference else None
        return cls._next_cron_fire(spec.cron, reference)

    @staticmethod
    def _resolve_timezone(name: str) -> ZoneInfo:
        """Resolve an IANA timezone name, reporting an unknown one as a validation error."""
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown schedule timezone '{name}': expected an IANA name such as 'Asia/Colombo'") from exc

    @staticmethod
    def _parse_at(at: Optional[str]) -> datetime.datetime:
        """Parse a one-time ``at`` timestamp into a naive local wall-clock datetime."""
        try:
            occurrence = datetime.datetime.fromisoformat(at or "")
        except ValueError as exc:
            raise ValueError(f"schedule 'at' must be an ISO-8601 timestamp such as '2030-01-31T09:00:00': got '{at}'") from exc
        if occurrence.tzinfo is not None:
            # An offset would silently compete with the spec's timezone field for authority.
            raise ValueError(f"schedule 'at' must not carry a UTC offset: use a local wall-clock time with 'timezone' instead of '{at}'")
        return occurrence

    @staticmethod
    def _cron_class() -> type:
        """Import croniter, pointing at the extra that ships it when it is missing.

        Imported on demand rather than at module import so one-time (``at``) schedules work
        without the extra installed.
        """
        with require_extra("schedule", "a cron schedule expression"):
            from croniter import croniter

        return croniter

    @classmethod
    def _validate_cron(cls, expression: str) -> None:
        """Reject a cron expression croniter cannot parse, or one that is not 5 fields."""
        croniter = cls._cron_class()
        if len(expression.split()) != CRON_FIELD_COUNT:
            raise ValueError(f"schedule 'cron' must be a standard {CRON_FIELD_COUNT}-field expression such as '0 9 * * 1': got '{expression}'")
        if not croniter.is_valid(expression):
            raise ValueError(f"invalid schedule 'cron' expression '{expression}'")

    @classmethod
    def _next_cron_fire(cls, expression: str, reference: datetime.datetime) -> datetime.datetime:
        """Compute the first cron occurrence strictly after ``reference`` in its timezone."""
        cls._validate_cron(expression)
        return cls._cron_class()(expression, reference).get_next(datetime.datetime)
