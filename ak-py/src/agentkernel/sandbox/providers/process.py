"""``ProcessKiller`` — the kill-by-name command shared by the ``docker`` and ``kubernetes`` handles.

A timed-out (or cancelled) exec keeps running inside the sandbox unless something kills it.
The default ``python:3.12-slim`` image ships neither ``pkill`` nor ``ps``, so the kill is a
``/proc`` scan that needs only ``/bin/sh``. It is best-effort: it targets the process whose
name equals the argv's first token, orphans that process's children, and is time-bounded.
"""

import posixpath
import shlex
from typing import ClassVar

# Kernel `comm` holds at most 15 characters of the executable name.
_COMM_LENGTH = 15

# A procps-free, fork-free scan: the `read` builtin (not `$(cat ...)`) means no subshell whose
# `comm` could match. PID 1 (the container's main process) and the scanning shell's own `$$`
# are skipped, so a timed-out `/bin/sh -c` never kills its own scanner.
_SCRIPT = (
    "for p in /proc/[0-9]*; do pid=${{p#/proc/}}; "
    'if [ "$pid" = 1 ] || [ "$pid" = "$$" ]; then continue; fi; '
    '{{ read -r comm < "$p/comm"; }} 2>/dev/null || continue; '
    'if [ "$comm" = {name} ]; then kill -9 "$pid" 2>/dev/null; fi; '
    "done; exit 0"
)


class ProcessKiller:
    """Builds a kill-by-name command that needs no procps (the default python:3.12-slim has none)."""

    KILL_TIMEOUT_SECONDS: ClassVar[float] = 5.0  # must stay below BrokerWorkerCore.BACKSTOP_GRACE_SECONDS

    @staticmethod
    def argv(executable: str) -> list[str]:
        """``/bin/sh -c`` a scan that SIGKILLs every process whose ``comm`` equals
        ``basename(executable)[:15]``, skipping PID 1 and the scanning shell's own ``$$``."""
        name = posixpath.basename(executable)[:_COMM_LENGTH]
        return ["/bin/sh", "-c", _SCRIPT.format(name=shlex.quote(name))]
