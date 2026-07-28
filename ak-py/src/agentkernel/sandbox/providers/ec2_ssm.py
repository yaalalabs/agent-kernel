"""``ec2_ssm`` provider — attach-only execution on an existing EC2 instance via SSM (``aws`` extra).

Mode-3 attach: both ``create`` and ``attach`` bind to an already-running instance id
(``attach_to`` in config, or the sandbox id on attach); ``create`` never provisions and
``destroy`` is a no-op — the provider never owns the host. Executions are
``ssm.send_command`` (``AWS-RunShellScript``) polled via ``get_command_invocation``;
``execute_code`` wraps python in a ``python3 - <<'EOF'`` heredoc. boto3 is synchronous, so
every call runs in ``asyncio.to_thread``.

Identity mapping (spec §PrincipalResolver): agent mode uses the default boto3 credential
chain; user mode calls ``sts:AssumeRole`` on ``credentials["role_arn"]`` and, when
``credentials["run_as"]`` is set, runs each command as that OS user (realized as a
``sudo -n -u <run_as>`` prefix — ``AWS-RunShellScript`` has no native RunAs).

Isolation is ``none``: commands run directly on the shared instance with whatever
permissions the SSM agent grants. All policy flags are declared False; only the
framework-side execution timeout applies.

No persistent shell: every ``send_command`` runs as its own independent process on the
instance, so in-shell state (working directory, exported env vars, ``sudo su``) does not
carry across separate commands — a ``cd`` in one command is gone by the next. This is
inherent to SSM Run Command, hence ``stateful=False``; state-dependent steps must be chained
in a single command (``cd /app && ./run.sh``). The injected agent guidance says so for
``ec2_ssm`` profiles.
"""

import asyncio
import logging
import shlex
from typing import Any, Optional

import boto3

from ..base import AttachedEnvironment, AttachedEnvironmentProvider, Sandbox
from ..errors import SandboxCapabilityError, SandboxGoneError, SandboxTimeoutError
from ..model import IsolationTier, SandboxCapabilities, SandboxPolicy, SandboxPrincipal, SandboxResult

logger = logging.getLogger("ak.sandbox.provider")

_HEREDOC_DELIMITER = "AK_SANDBOX_EOF"
_POLL_INTERVAL = 1.0  # seconds between get_command_invocation polls
_PENDING_STATUSES = {"Pending", "InProgress", "Delayed"}


class EC2SSMEnvironment(AttachedEnvironment):
    """Handle bound to one EC2 instance; executions are SSM Run Command invocations.

    An ``AttachedEnvironment``, not a sandbox: the instance exists and keeps running independently
    of the framework, so ``close()`` (inherited) releases nothing."""

    def __init__(self, instance_id: str, ssm_client: Any, run_as: Optional[str] = None) -> None:
        """Bind the handle to the instance id (the sandbox id) and the resolved SSM client."""
        self.id = instance_id
        self._ssm = ssm_client
        self._run_as = run_as

    async def execute_code(self, code: str, language: str = "python", timeout: float | None = None) -> SandboxResult:
        """Wrap the code in a ``python3 - <<'EOF'`` heredoc and run it as a shell command."""
        if language not in EC2SSMSandboxProvider.capabilities.languages:
            raise SandboxCapabilityError(self.__class__.__name__, f"language:{language}")
        script = f"python3 - <<'{_HEREDOC_DELIMITER}'\n{code}\n{_HEREDOC_DELIMITER}"
        return await self.execute_command(script, timeout)

    async def execute_command(self, command: str, timeout: float | None = None) -> SandboxResult:
        """Send the command via ``AWS-RunShellScript`` and poll the invocation to a terminal state."""
        if self._run_as:
            command = f"sudo -n -u {shlex.quote(self._run_as)} sh -c {shlex.quote(command)}"

        def send() -> str:
            response = self._ssm.send_command(
                InstanceIds=[self.id],
                DocumentName="AWS-RunShellScript",
                Parameters={"commands": [command]},
            )
            return response["Command"]["CommandId"]

        try:
            command_id = await asyncio.to_thread(send)
        except Exception as exc:  # noqa: BLE001 — mapped to the typed hierarchy below
            raise _map_instance_error(exc, self.id)
        try:
            invocation = await asyncio.wait_for(self._poll(command_id), timeout=timeout)
        except asyncio.TimeoutError as exc:
            await self._best_effort_cancel(command_id)
            raise SandboxTimeoutError(f"ssm command exceeded timeout {timeout}s") from exc
        return SandboxResult(
            stdout=invocation.get("StandardOutputContent", ""),
            stderr=invocation.get("StandardErrorContent", ""),
            exit_code=invocation.get("ResponseCode", -1),
        )

    async def _poll(self, command_id: str) -> dict:
        """Poll ``get_command_invocation`` until the command reaches a terminal status."""
        while True:
            invocation = await asyncio.to_thread(self._ssm.get_command_invocation, CommandId=command_id, InstanceId=self.id)
            if invocation.get("Status") not in _PENDING_STATUSES:
                return invocation
            await asyncio.sleep(_POLL_INTERVAL)

    async def _best_effort_cancel(self, command_id: str) -> None:
        """Cancel a timed-out command so it stops consuming the instance. Best-effort by contract."""
        try:
            await asyncio.to_thread(self._ssm.cancel_command, CommandId=command_id)
        except Exception as exc:  # noqa: BLE001 — the cancel is best-effort by contract
            logger.warning("Best-effort cancel of SSM command %s failed: %s", command_id, exc)


def _map_instance_error(exc: Exception, instance_id: str) -> Exception:
    """Translate a boto3 invalid/unknown-instance error into ``SandboxGoneError``; pass others through."""
    error_code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
    if error_code == "InvalidInstanceId" or exc.__class__.__name__ == "InvalidInstanceId":
        return SandboxGoneError(f"instance '{instance_id}' is not reachable via SSM")
    return exc


class EC2SSMSandboxProvider(AttachedEnvironmentProvider):
    """Attach-only provider running commands on an existing EC2 instance over SSM.

    Lifecycle non-ownership comes from ``AttachedEnvironmentProvider``: ``create`` binds to
    the configured ``attach_to`` instance and ``destroy`` is a no-op.
    """

    capabilities = SandboxCapabilities(
        isolation=IsolationTier.NONE,  # commands run directly on the shared instance
        shell=True,
        languages=["python"],
        files=False,
        package_install=False,
        stateful=False,  # SSM runs each command as its own process — no persistent shell/cwd/env
        attach=True,
        provisions=False,  # attach-only: never creates the environment
        attaches_external=True,  # binds to an instance the framework does not own
        principal_user=True,  # user mode: sts:AssumeRole + optional run_as
        policy_network=False,
        policy_filesystem=False,
        policy_resources=False,
    )

    def __init__(self, config) -> None:
        """Store the config; boto3 clients are created lazily per identity mode."""
        super().__init__(config)
        self._agent_client: Optional[Any] = None

    async def attach(self, sandbox_id: str, *, principal: SandboxPrincipal, policy: SandboxPolicy) -> Sandbox:
        """Bind to the instance id after verifying SSM can see it; a missing/offline
        instance raises ``SandboxGoneError`` (the self-heal signal)."""
        ssm_client, run_as = await asyncio.to_thread(self._resolve_client, principal)

        def verify() -> None:
            described = ssm_client.describe_instance_information(Filters=[{"Key": "InstanceIds", "Values": [sandbox_id]}])
            if not described.get("InstanceInformationList"):
                raise SandboxGoneError(f"instance '{sandbox_id}' is not registered with SSM")

        try:
            await asyncio.to_thread(verify)
        except SandboxGoneError:
            raise
        except Exception as exc:  # noqa: BLE001 — mapped to the typed hierarchy
            raise _map_instance_error(exc, sandbox_id)
        return EC2SSMEnvironment(sandbox_id, ssm_client, run_as)

    def _resolve_client(self, principal: SandboxPrincipal) -> tuple[Any, Optional[str]]:
        """Map the principal onto an SSM client (spec §PrincipalResolver): agent mode uses the
        default boto3 chain (cached); user mode assumes ``credentials["role_arn"]`` and carries
        ``credentials["run_as"]`` onto the handle."""
        region = self._config.region
        if principal.mode != "user":
            if self._agent_client is None:
                self._agent_client = boto3.client("ssm", region_name=region)
            return self._agent_client, None

        role_arn = principal.credentials.get("role_arn")
        if not role_arn:
            from ..errors import SandboxPolicyError

            raise SandboxPolicyError("ec2_ssm user mode requires credentials['role_arn'] on the principal")
        sts = boto3.client("sts", region_name=region)
        assumed = sts.assume_role(RoleArn=role_arn, RoleSessionName=f"ak-sandbox-{principal.subject}"[:64])
        credentials = assumed["Credentials"]
        client = boto3.client(
            "ssm",
            region_name=region,
            aws_access_key_id=credentials["AccessKeyId"],
            aws_secret_access_key=credentials["SecretAccessKey"],
            aws_session_token=credentials["SessionToken"],
        )
        return client, principal.credentials.get("run_as")
