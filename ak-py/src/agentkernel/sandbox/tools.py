"""Sandbox system tools — the agent-facing surface of the sandbox capability.

Five async tools registered on every agent (via ``SystemToolFactory``) when
``sandbox.enabled`` is true. All of them return JSON strings, every result carries a
``sandbox_session_id``, and machinery errors are caught and returned as
``{"error": ...}`` strings — tools never raise into the framework.
"""

import json
import logging
from typing import Any, Optional, Union

from ..core.config import AKConfig
from ..core.model import SystemTool
from .manager import SandboxManager
from .model import SandboxResult, SandboxTask

_log = logging.getLogger("ak.sandbox.tools")

_DISABLED = json.dumps({"error": "sandbox capability is disabled"})


def _max_chars() -> int:
    """Return the configured truncation limit for tool output."""
    return AKConfig.get().sandbox.tool_output_max_chars


def _default_session_echo(sandbox_session_id: Optional[str], profile: Optional[str]) -> str:
    """The sandbox_session_id a caller can reuse when it did not pass one explicitly."""
    if sandbox_session_id:
        return sandbox_session_id
    return f"default:{profile or AKConfig.get().sandbox.default_profile}"


def _error_json(exc: Exception, sandbox_session_id: Optional[str]) -> str:
    """Serialize a machinery error into the tool ``{"error": ...}`` JSON contract."""
    return json.dumps({"error": str(exc), "sandbox_session_id": sandbox_session_id or ""})


def _outcome_json(outcome: Union[SandboxResult, SandboxTask]) -> str:
    """Serialize an execute outcome: a pending-task handle for a promoted ``SandboxTask``,
    or stdout/stderr/exit_code (truncated) for a ``SandboxResult``."""
    if isinstance(outcome, SandboxTask):
        return json.dumps({"task_id": outcome.task_id, "status": "pending", "sandbox_session_id": outcome.sandbox_session_id})
    limit = _max_chars()
    return json.dumps(
        {
            "stdout": outcome.stdout[:limit],
            "stderr": outcome.stderr[:limit],
            "exit_code": outcome.exit_code,
            "sandbox_session_id": outcome.sandbox_session_id,
        }
    )


async def run_code(code: str, language: str = "python", sandbox_session_id: Optional[str] = None, profile: Optional[str] = None) -> str:
    """
    Execute code in an isolated sandbox and return the outcome as a JSON string.

    Args:
        code: Source code to execute.
        language: Language the code is written in (default "python").
        sandbox_session_id: Reuse an existing sandbox session; omit for the default session.
        profile: Workload profile to run under; omit for the configured default.

    Returns:
        JSON with stdout, stderr, exit_code, and sandbox_session_id; or
        {"task_id", "status": "pending", "sandbox_session_id"} when execution continues
        in the background; or {"error": ...} on a sandbox machinery failure.
    """
    manager = SandboxManager.get()
    if manager is None:
        return _DISABLED
    try:
        wait = AKConfig.get().sandbox.broker.wait_timeout
        outcome = await manager.execute(code=code, language=language, profile=profile, sandbox_session_id=sandbox_session_id, wait=wait)
        return _outcome_json(outcome)
    except Exception as exc:  # noqa: BLE001 — tools never raise into the framework
        _log.warning("run_code failed: %s", exc)
        return _error_json(exc, sandbox_session_id)


async def run_command(command: str, sandbox_session_id: Optional[str] = None, profile: Optional[str] = None) -> str:
    """
    Execute a shell command in an isolated sandbox and return the outcome as a JSON string.

    Args:
        command: Shell command to execute.
        sandbox_session_id: Reuse an existing sandbox session; omit for the default session.
        profile: Workload profile to run under; omit for the configured default.

    Returns:
        JSON with stdout, stderr, exit_code, and sandbox_session_id; or
        {"task_id", "status": "pending", "sandbox_session_id"} when execution continues
        in the background; or {"error": ...} on a sandbox machinery failure.
    """
    manager = SandboxManager.get()
    if manager is None:
        return _DISABLED
    try:
        wait = AKConfig.get().sandbox.broker.wait_timeout
        outcome = await manager.execute(command=command, profile=profile, sandbox_session_id=sandbox_session_id, wait=wait)
        return _outcome_json(outcome)
    except Exception as exc:  # noqa: BLE001 — tools never raise into the framework
        _log.warning("run_command failed: %s", exc)
        return _error_json(exc, sandbox_session_id)


async def write_sandbox_file(path: str, content: str, sandbox_session_id: Optional[str] = None, profile: Optional[str] = None) -> str:
    """
    Write a UTF-8 text file into the sandbox workspace.

    Args:
        path: Destination path inside the sandbox.
        content: UTF-8 text content to write.
        sandbox_session_id: Reuse an existing sandbox session; omit for the default session.
        profile: Workload profile to run under; omit for the configured default.

    Returns:
        JSON with path, written flag, and sandbox_session_id; or {"error": ...} on failure.
    """
    manager = SandboxManager.get()
    if manager is None:
        return _DISABLED
    try:
        await manager.upload(path, content.encode("utf-8"), profile=profile, sandbox_session_id=sandbox_session_id)
        return json.dumps({"path": path, "written": True, "sandbox_session_id": _default_session_echo(sandbox_session_id, profile)})
    except Exception as exc:  # noqa: BLE001 — tools never raise into the framework
        _log.warning("write_sandbox_file failed: %s", exc)
        return _error_json(exc, sandbox_session_id)


async def read_sandbox_file(path: str, sandbox_session_id: Optional[str] = None, profile: Optional[str] = None) -> str:
    """
    Read a UTF-8 text file from the sandbox workspace.

    Args:
        path: Path inside the sandbox to read.
        sandbox_session_id: Reuse an existing sandbox session; omit for the default session.
        profile: Workload profile to run under; omit for the configured default.

    Returns:
        JSON with path, content (truncated to the configured maximum), and
        sandbox_session_id; or {"error": ...} on failure.
    """
    manager = SandboxManager.get()
    if manager is None:
        return _DISABLED
    try:
        data = await manager.download(path, profile=profile, sandbox_session_id=sandbox_session_id)
        content = data.decode("utf-8", errors="replace")[: _max_chars()]
        return json.dumps({"path": path, "content": content, "sandbox_session_id": _default_session_echo(sandbox_session_id, profile)})
    except Exception as exc:  # noqa: BLE001 — tools never raise into the framework
        _log.warning("read_sandbox_file failed: %s", exc)
        return _error_json(exc, sandbox_session_id)


async def check_sandbox_task(task_id: str) -> str:
    """
    Check the status of a previously promoted sandbox task.

    Args:
        task_id: Task id returned by run_code/run_command when execution was promoted.

    Returns:
        JSON with task_id, status ("pending", "succeeded", "failed", "timed_out", or
        "unknown"), and sandbox_session_id when known; or {"error": ...} on failure.
    """
    manager = SandboxManager.get()
    if manager is None:
        return _DISABLED
    try:
        task = await manager.task_status(task_id)
        if task is None:
            return json.dumps({"task_id": task_id, "status": "unknown"})
        return json.dumps({"task_id": task.task_id, "status": task.status, "sandbox_session_id": task.sandbox_session_id})
    except Exception as exc:  # noqa: BLE001 — tools never raise into the framework
        _log.warning("check_sandbox_task failed: %s", exc)
        return _error_json(exc, None)


def _profiles_text(config: Any) -> str:
    """Render the configured workload profiles for the tool guidance (config-derived only —
    provider capabilities are not imported at registration time)."""
    lines = []
    for name, prof in config.profiles.items():
        marker = " (default)" if name == config.default_profile else ""
        lines.append(f"- '{name}'{marker}: provider '{prof.type}', scope {prof.scope}")
    return "\n".join(lines) if lines else "- (none configured)"


def get_sandbox_tools() -> list[SystemTool]:
    """Build the sandbox system tools; called by ``SystemToolFactory`` when enabled.

    The capability's whole system-prompt section rides on the first tool's ``description``
    (the multimodal injection pattern: ``SystemToolFactory.get_system_prompt_suffix()`` is
    appended to every agent's instructions via ``Agent._setup_system_prompt()``), so agents
    learn about the sandbox automatically — agent authors never describe these tools in
    their own instructions. The remaining tools carry empty descriptions; their LLM-facing
    schemas come from the function docstrings when the tools are bound.
    """
    config = AKConfig.get().sandbox
    guidance = (
        "[Sandbox execution]\n"
        "You have access to an isolated sandbox where you can execute code you write, run shell commands, "
        "and read/write workspace files. Prefer running real code over computing results yourself, and "
        "report the sandbox's actual output.\n"
        "Available tools:\n"
        "- run_code(code, language, sandbox_session_id, profile): execute code; returns stdout, stderr, exit_code.\n"
        "- run_command(command, sandbox_session_id, profile): execute a shell command.\n"
        "- write_sandbox_file(path, content, sandbox_session_id, profile): write a text file into the sandbox workspace.\n"
        "- read_sandbox_file(path, sandbox_session_id, profile): read a text file from the sandbox workspace.\n"
        "- check_sandbox_task(task_id): poll a long-running execution that returned status 'pending'.\n"
        "Every result includes a sandbox_session_id. Sandbox state (files, workspace) persists per "
        "sandbox_session_id: reuse the id from a previous result to continue in the same environment, "
        "or omit it for the default session.\n"
        f"Available workload profiles (pass as profile=):\n{_profiles_text(config)}\n"
        f"stdout/stderr and file reads are truncated at {config.tool_output_max_chars} characters."
    )
    return [
        SystemTool(name="run_code", description=guidance, func=run_code),
        SystemTool(name="run_command", description="", func=run_command),
        SystemTool(name="write_sandbox_file", description="", func=write_sandbox_file),
        SystemTool(name="read_sandbox_file", description="", func=read_sandbox_file),
        SystemTool(name="check_sandbox_task", description="", func=check_sandbox_task),
    ]
