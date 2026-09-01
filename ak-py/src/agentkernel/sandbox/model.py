"""Sandbox capability data types.

All models are Pydantic ``BaseModel``s. The field sketches here are normative for
names, types, and defaults across the whole capability.

Result semantics: a failing *program* (compile error, exception, non-zero exit)
is returned as a :class:`SandboxResult` with ``exit_code != 0`` and diagnostics in
``stderr``. Exceptions are reserved for failures of the sandbox *machinery* (see
:mod:`agentkernel.sandbox.errors`).
"""

import base64
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_serializer, field_validator


class IsolationTier(str, Enum):
    """How strong a boundary a backend puts between sandboxed code and the host.

    Declared honestly per provider — AK never implies backends are interchangeable
    on security grounds.
    """

    NONE = "none"  # no isolation boundary (local_subprocess, ec2_ssm)
    OS_POLICY = "os_policy"  # seccomp/Seatbelt/bubblewrap confinement
    CONTAINER = "container"  # shared-kernel namespaces (docker, kubernetes, daytona)
    SYSCALL_FILTER = "syscall_filter"  # gVisor-style user-space kernel
    MICRO_VM = "micro_vm"  # Firecracker/managed VM (e2b, bedrock_agentcore)
    WASM = "wasm"  # in-process WASM runtime


class SandboxCapabilities(BaseModel):
    """What a provider actually supports; unsupported operations raise ``SandboxCapabilityError``."""

    isolation: IsolationTier  # mandatory, no default — declared honestly per provider
    shell: bool = False  # execute_command supported
    languages: list[str] = Field(default_factory=lambda: ["python"])  # languages accepted by execute_code
    files: bool = False  # upload_file / download_file supported
    package_install: bool = False  # install_packages supported
    stateful: bool = False  # variables persist across execute_code calls in one sandbox
    attach: bool = False  # reconnect to a live sandbox by id supported (session continuity)
    provisions: bool = True  # can create new environments (False = attach-only, e.g. ec2_ssm)
    attaches_external: bool = False  # can bind to an environment it did not create (attach_to)
    principal_user: bool = False  # user-assumed identity supported
    policy_network: bool = False  # network egress policy enforceable
    policy_filesystem: bool = False  # filesystem policy enforceable
    policy_resources: bool = False  # cpu/memory limits enforceable


class SandboxFile(BaseModel):
    """A file exchanged with a sandbox; ``content`` is bytes in memory, base64 over the wire."""

    path: str
    content: bytes
    mime_type: str = "application/octet-stream"

    @field_validator("content", mode="before")
    @classmethod
    def _content_from_wire(cls, value: Any) -> Any:
        """Accept the wire form: a base64 string decodes back to bytes; bytes pass through."""
        if isinstance(value, str):
            return base64.b64decode(value, validate=True)
        return value

    @field_serializer("content", when_used="json")
    def _content_to_wire(self, value: bytes) -> str:
        """Emit base64 in JSON-serialization mode so arbitrary binary survives the wire;
        python-mode dumps (in-process flavors, the nv_cache registry) keep raw bytes."""
        return base64.b64encode(value).decode("ascii")


class SandboxResult(BaseModel):
    """The outcome of running code/commands. A non-zero exit is a RESULT, not an exception."""

    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    output_files: list[SandboxFile] = Field(default_factory=list)
    sandbox_session_id: str = ""  # stamped by the manager/worker before returning
    notice: str | None = None  # machinery advisory surfaced to the agent (e.g. sandbox recreated after idle timeout)
    provider_data: dict[str, Any] = Field(default_factory=dict)  # provider-specific escape hatch; never required by callers


class SandboxSession(BaseModel):
    """A cross-turn handle to one sandbox, addressed by a stable ``sandbox_session_id``."""

    sandbox_session_id: str  # uuid4 hex, minted by ExecutionManager
    name: str | None = None  # optional human-friendly label (shown in listings; addressing is by id)
    profile: str  # workload profile that created it
    provider_type: str  # resolved backend type (e.g. "docker")
    sandbox_id: str | None = None  # provider-scoped reconnect handle; None until created
    created_at: float  # epoch seconds
    last_used_at: float  # epoch seconds; drives idle timeout
    status: Literal["active", "closed"] = "active"


class SandboxTask(BaseModel):
    """A suspended (promoted) execution the agent polls for later."""

    task_id: str  # uuid4 hex
    sandbox_session_id: str
    profile: str
    status: Literal["pending", "succeeded", "failed", "timed_out"] = "pending"
    submitted_at: float
    consumed: bool = False  # completion delivered to the agent (dedup flag)
    notice: str | None = None  # machinery advisory surfaced to the agent (e.g. sandbox recreated on idle)
    # Bounded terminal outcome (stdout/stderr tails, exit_code, error) captured when the
    # completion is consumed, so check_sandbox_task returns results, not just statuses.
    result_summary: dict[str, Any] | None = None


class SandboxPrincipal(BaseModel):
    """The identity an execution runs under."""

    mode: Literal["agent", "user"] = "agent"
    subject: str  # agent name, or resolved user identifier
    credentials: dict[str, Any] = Field(default_factory=dict)  # provider-interpreted (role ARN, K8s user/groups, RunAs user)
    groups: list[str] = Field(default_factory=list)


class SandboxPolicy(BaseModel):
    """The permission/resource envelope enforced on an execution."""

    network_egress: Literal["allow", "deny", "allowlist"] = "allow"
    network_allow: list[str] = Field(default_factory=list)  # domains and/or CIDRs when egress == "allowlist"
    fs_allow_read: list[str] = Field(default_factory=list)  # empty = provider default
    fs_allow_write: list[str] = Field(default_factory=list)
    cpu: float | None = None  # cores
    memory_mb: int | None = None
    timeout: float = 120.0  # per-execution wall clock, seconds
    strict: bool = True  # fail closed on unenforceable dimensions
