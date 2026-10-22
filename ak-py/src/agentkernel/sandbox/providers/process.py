"""``ProcessKiller`` — the marker-based kill shared by the ``docker`` and ``kubernetes`` handles.

A timed-out (or cancelled) exec keeps running inside the sandbox unless something kills it.
Each killable exec carries a unique marker in its environment (``AK_EXEC_ID``), which its
children inherit; the kill SIGKILLs exactly the processes that carry that marker. Processes
left running by earlier execs (e.g. a background server) carry a different marker and survive.

The default ``python:3.12-slim`` image ships neither ``pkill`` nor ``ps``, so the kill is a
``/proc`` scan that needs only ``/bin/sh`` and ``cat``. It is best-effort: a process that
clears its environment escapes, background jobs started by the timed-out exec itself are
killed with it, and the kill is time-bounded.
"""

import shlex
import uuid
from typing import ClassVar

# A procps-free scan: SIGKILL every process whose environment holds the marker. The shell drops
# environ's NUL separators, which is safe because the marker is fixed-length hex (no marker is a
# prefix of another). The scanner itself runs without the marker, so it never matches itself;
# PID 1 (the container's main process) and the scanning shell's own `$$` are skipped regardless.
_SCRIPT = (
    "for p in /proc/[0-9]*; do pid=${{p#/proc/}}; "
    'if [ "$pid" = 1 ] || [ "$pid" = "$$" ]; then continue; fi; '
    'case "$(cat "$p/environ" 2>/dev/null)" in *{needle}*) kill -9 "$pid" 2>/dev/null;; esac; '
    "done; exit 0"
)

# Launcher for transports with no per-exec environment (the Kubernetes stream API): export the
# marker, then exec the real argv, so the process that runs is argv[0] carrying the marker.
_LAUNCHER = 'export {env}="$1"; shift; exec "$@"'


class ProcessKiller:
    """Tags an exec with a unique marker and builds the procps-free command that kills it."""

    MARKER_ENV: ClassVar[str] = "AK_EXEC_ID"
    KILL_TIMEOUT_SECONDS: ClassVar[float] = 5.0  # must stay below BrokerWorkerCore.BACKSTOP_GRACE_SECONDS
    # Exits 0 only where /bin/sh runs — which the launcher and the kill scan both need.
    SHELL_PROBE: ClassVar[tuple[str, ...]] = ("/bin/sh", "-c", "exit 0")

    @staticmethod
    def new_marker() -> str:
        """A fresh fixed-length marker for one exec."""
        return uuid.uuid4().hex

    @classmethod
    def environment(cls, marker: str) -> dict[str, str]:
        """The exec environment carrying ``marker``, for transports that take one (Docker ``exec_run``)."""
        return {cls.MARKER_ENV: marker}

    @classmethod
    def wrap(cls, argv: list[str], marker: str) -> list[str]:
        """``argv`` launched with ``marker`` in its environment, for transports without one (Kubernetes exec)."""
        return ["/bin/sh", "-c", _LAUNCHER.format(env=cls.MARKER_ENV), "ak-exec", marker, *argv]

    @classmethod
    def argv(cls, marker: str) -> list[str]:
        """``/bin/sh -c`` a scan that SIGKILLs every process whose environment holds ``marker``,
        skipping PID 1 and the scanning shell's own ``$$``."""
        return ["/bin/sh", "-c", _SCRIPT.format(needle=shlex.quote(f"{cls.MARKER_ENV}={marker}"))]
