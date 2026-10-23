"""``kubernetes`` provider — pod-per-sandbox via the Kubernetes Python client (``kubernetes`` extra).

Each sandbox is a pod running ``sleep infinity`` as PID 1; executions are exec calls through the
stream API (which inherit the container's ``/workspace`` working directory; code runs through
the language's interpreter argv from ``language_runtimes`` with the code appended), and files
travel as single-member tars framed in base64 over the exec channels (``head -c N`` gives
the remote pipeline its EOF, since a WebSocket exec cannot half-close stdin). The SDK is
synchronous, so every call runs in ``asyncio.to_thread``. A timed-out or cancelled exec is
killed by its environment marker (``ProcessKiller``), which needs ``/bin/sh`` in the image:
the first exec on each pod probes for it (bounded, cached once definite), and a shell-less pod
runs its argv directly, with no kill.

``close()`` leaves the pod running (that is what makes reattach work); ``destroy()``
deletes the pod and its per-pod NetworkPolicy. The security boundary is the credential:
the pod's ServiceAccount RBAC decides what an execution may do, never command-string
parsing. Policy mapping: cpu/memory become requests=limits; filesystem restrictions become
a read-only rootfs with an emptyDir workdir; egress policy maps to per-pod NetworkPolicies
only when ``network_policy: true`` asserts that the cluster CNI enforces them (the
instance-level capability override), otherwise the fail-closed core rejects it under
``strict``.
"""

import asyncio
import base64
import io
import ipaddress
import json
import logging
import posixpath
import shlex
import tarfile
import threading
import time
import uuid
from typing import Any, ClassVar, Optional

import kubernetes
import kubernetes.client
import kubernetes.config
import kubernetes.stream

from ..base import Sandbox, SandboxProvider
from ..errors import SandboxCapabilityError, SandboxError, SandboxGoneError, SandboxPolicyError, SandboxProvisionError, SandboxTimeoutError
from ..model import IsolationTier, SandboxCapabilities, SandboxPolicy, SandboxPrincipal, SandboxResult
from ..packages import PackageInstaller
from .process import ProcessKiller

logger = logging.getLogger("ak.sandbox.provider")

WORKDIR = "/workspace"

# The sweep, operators, and the hardening NetworkPolicy find sandbox pods by these labels.
_MANAGED_LABELS = {"app.kubernetes.io/managed-by": "agent-kernel", "agentkernel.io/sandbox": "true"}
# Per-pod label the per-pod NetworkPolicy selects on; always set last so nothing displaces it.
_NAME_LABEL = "agentkernel.io/sandbox-name"

_TERMINAL_PHASES = ("Succeeded", "Failed")

# kubernetes.stream.ws_client.ERROR_CHANNEL: where the API server writes the exec's final status.
_ERROR_CHANNEL = 3


def _safe_rel(path: str) -> str:
    """Resolve a caller path to a WORKDIR-relative POSIX path: an absolute path is treated
    as workdir-relative (its leading ``/`` is stripped), and ``..`` traversal that would
    escape the workdir is rejected (mirrors the docker provider's check)."""
    rel = path.lstrip("/")
    resolved = posixpath.normpath(posixpath.join(WORKDIR, rel))
    if resolved != WORKDIR and not resolved.startswith(WORKDIR + "/"):
        raise SandboxPolicyError(f"path '{path}' escapes the sandbox working directory")
    return posixpath.relpath(resolved, WORKDIR)


class KubernetesSandbox(Sandbox):
    """Handle to one running sandbox pod; executions are stream-API exec calls inside it."""

    # Container-runtime wording for a missing /bin/sh in an exec's failure status (containerd, CRI-O).
    _NO_SHELL_MARKERS: ClassVar[tuple[str, ...]] = ("no such file or directory", "executable file not found", "not found")

    def __init__(
        self,
        api: Any,
        namespace: str,
        pod_name: str,
        *,
        capabilities: SandboxCapabilities,
        installer: PackageInstaller,
        runtimes: dict[str, list[str]],
        kill_enabled: bool,
        shell_cache: dict[str, bool],
    ) -> None:
        """Bind the handle to a pod; the id is ``<namespace>/<pod>`` (the ``attach_to`` format).
        ``capabilities`` are the provider instance's; ``runtimes`` is its ``language_runtimes``
        map; ``kill_enabled`` is False for an ``attach_to`` pod: the framework does not own it,
        so it neither tags nor kills its execs. ``shell_cache`` is the provider's per-pod
        record of whether the pod has ``/bin/sh``, shared by every handle to the pod."""
        self.id = f"{namespace}/{pod_name}"
        self._api = api
        self._namespace = namespace
        self._pod = pod_name
        self._capabilities = capabilities
        self._installer = installer
        self._runtimes = runtimes
        self._kill_enabled = kill_enabled
        self._shell_cache = shell_cache

    async def execute_code(self, code: str, language: str = "python", timeout: float | None = None) -> SandboxResult:
        """Exec the language's configured interpreter argv with the code appended (default ``python -c``)."""
        if language not in self._capabilities.languages:
            raise SandboxCapabilityError(self.__class__.__name__, f"language:{language}")
        return await self._exec([*self._runtimes[language], code], timeout)

    async def execute_command(self, command: str, timeout: float | None = None) -> SandboxResult:
        """Exec a shell command via ``/bin/sh -c``."""
        return await self._exec(["/bin/sh", "-c", command], timeout)

    async def install_packages(self, packages: list[str], ecosystem: str = "python", timeout: float | None = None) -> SandboxResult:
        """Exec the ecosystem's validated installer argv (e.g. ``pip install <packages>``)."""
        if ecosystem not in self._capabilities.package_ecosystems:
            raise SandboxCapabilityError(self.__class__.__name__, f"package_ecosystem:{ecosystem}")
        return await self._exec(self._installer.argv(packages, ecosystem), timeout)

    async def upload_file(self, path: str, content: bytes) -> None:
        """Ship the file as a single-member tar on exec stdin, base64-framed for the text
        channel; ``head -c`` reads exactly the sent bytes so the remote pipeline gets EOF."""
        rel = _safe_rel(path)
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            info = tarfile.TarInfo(name=rel)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
        encoded = base64.b64encode(buf.getvalue()).decode("ascii")
        command = f"head -c {len(encoded)} | base64 -d | tar -xf - -C {WORKDIR}"
        result = await self._exec(["sh", "-c", command], None, stdin_data=encoded)
        if result.exit_code != 0:
            raise SandboxError(f"upload of '{path}' to pod '{self.id}' failed: {result.stderr.strip() or result.exit_code}")

    async def download_file(self, path: str) -> bytes:
        """Fetch the file as a base64-framed tar stream from exec stdout and untar it."""
        rel = _safe_rel(path)
        result = await self._exec(["sh", "-c", f"tar -cf - -C {WORKDIR} {shlex.quote(rel)} | base64"], None)
        if result.exit_code != 0:
            raise FileNotFoundError(path)
        with tarfile.open(fileobj=io.BytesIO(base64.b64decode(result.stdout))) as tar:
            for member in tar.getmembers():
                if member.isfile():
                    return tar.extractfile(member).read()
        raise FileNotFoundError(path)

    async def close(self) -> None:
        """Leave the pod running so a later ``attach`` can reconnect. Idempotent."""
        return None

    async def _exec(self, argv: list[str], timeout: float | None, stdin_data: Optional[str] = None, *, kill: bool = True) -> SandboxResult:
        """Run one exec through the stream API in a thread under ``asyncio.wait_for``. On
        expiry kill the exec'd process and raise ``SandboxTimeoutError``; on cancellation kill
        it and re-raise. A killable exec on a pod with a shell is launched through
        ``ProcessKiller.wrap`` (the stream API has no per-exec environment) so it carries a
        fresh marker. ``kill=False`` is the kill's (or the shell probe's) own exec, so it never
        triggers another."""
        marker = ProcessKiller.new_marker() if kill and self._kill_enabled and await self._has_shell() else None
        command = ProcessKiller.wrap(argv, marker) if marker else argv
        # Set when the caller stops waiting (timeout or cancellation): the thread cannot be cancelled,
        # so it stops streaming and closes the WebSocket itself within one update() tick.
        stop = threading.Event()

        def run() -> tuple[str, str, int]:
            try:
                resp = kubernetes.stream.stream(
                    self._api.connect_get_namespaced_pod_exec,
                    self._pod,
                    self._namespace,
                    command=command,
                    stdout=True,
                    stderr=True,
                    stdin=stdin_data is not None,
                    tty=False,
                    _preload_content=False,
                )
            except AttributeError as exc:
                # The kubernetes client masks a failed WebSocket handshake behind an
                # AttributeError while re-raising it (api_client decodes a None body).
                # The overwhelmingly common cause is missing RBAC: WebSocket exec is a GET,
                # so pods/exec needs BOTH 'create' and 'get'.
                raise SandboxError(
                    f"exec into pod '{self._namespace}/{self._pod}' failed during the WebSocket handshake; "
                    "check that the caller's RBAC grants both 'create' and 'get' on pods/exec"
                ) from exc
            if stdin_data is not None:
                resp.write_stdin(stdin_data)
            stdout_parts: list[str] = []
            stderr_parts: list[str] = []
            while resp.is_open() and not stop.is_set():
                resp.update(timeout=1)
                if resp.peek_stdout():
                    stdout_parts.append(resp.read_stdout())
                if resp.peek_stderr():
                    stderr_parts.append(resp.read_stderr())
            resp.close()
            # Read the status ourselves: the client's ``returncode`` consumes it and drops the message.
            exit_code, message = self._exit_status(resp.read_channel(_ERROR_CHANNEL))
            if exit_code is None:
                stderr_parts.append(
                    f"exec failed before the process started: {message}" if message else "exec ended without a status from the API server"
                )
            return "".join(stdout_parts), "".join(stderr_parts), exit_code if exit_code is not None else -1

        try:
            stdout, stderr, exit_code = await asyncio.wait_for(asyncio.to_thread(run), timeout=timeout)
        except asyncio.TimeoutError as exc:
            stop.set()
            if marker:
                await self._kill(marker)
            raise SandboxTimeoutError(f"kubernetes exec exceeded timeout {timeout}s") from exc
        except asyncio.CancelledError:
            stop.set()
            if marker:
                await self._kill(marker)
            raise
        return SandboxResult(stdout=stdout, stderr=stderr, exit_code=exit_code)

    @staticmethod
    def _exit_status(raw: str) -> tuple[Optional[int], str]:
        """Parse an exec's status channel into ``(exit_code, message)``: ``0`` on Success, the
        ``details.causes`` exit code on a Failure carrying one, else ``None`` with the status
        message (empty when there is no parseable status)."""
        try:
            status = json.loads(raw)
        except (TypeError, ValueError):
            return None, ""
        if not isinstance(status, dict):
            return None, ""
        if status.get("status") == "Success":
            return 0, ""
        try:
            return int(status["details"]["causes"][0]["message"]), ""
        except (KeyError, IndexError, TypeError, ValueError):
            return None, str(status.get("message") or "")

    async def _has_shell(self) -> bool:
        """Whether the pod can run ``/bin/sh`` (the launcher and the kill scan need it), probed once per pod
        under ``SHELL_PROBE_TIMEOUT_SECONDS``.

        Only a definite answer is cached on the provider: exit 0, or ``/bin/sh`` reported missing
        (exit 126/127, or a not-found status). Anything else (a raise, the probe's timeout, another
        failure) is treated as transient: this exec runs unwrapped and the next one probes again."""
        has_shell = self._shell_cache.get(self.id)
        if has_shell is not None:
            return has_shell
        try:
            probe = await asyncio.wait_for(
                self._exec(list(ProcessKiller.SHELL_PROBE), None, kill=False), timeout=ProcessKiller.SHELL_PROBE_TIMEOUT_SECONDS
            )
        except Exception as exc:  # noqa: BLE001 — the probe only decides whether to tag; it never fails the exec
            logger.warning("Shell probe in pod %s failed: %s", self.id, str(exc) or type(exc).__name__)
            return False
        if probe.exit_code == 0:
            self._shell_cache[self.id] = True
            return True
        if probe.exit_code in (126, 127) or (probe.exit_code == -1 and any(m in probe.stderr.lower() for m in self._NO_SHELL_MARKERS)):
            self._shell_cache[self.id] = False
            logger.info("Pod %s has no /bin/sh; its timed-out executions cannot be killed", self.id)
            return False
        logger.warning("Shell probe in pod %s was inconclusive (exit %s): %s", self.id, probe.exit_code, probe.stderr)
        return False

    async def _kill(self, marker: str) -> None:
        """Best-effort, time-bounded kill of the processes carrying the exec's marker; earlier
        execs' processes (e.g. background servers) carry other markers and survive."""
        try:
            await asyncio.wait_for(self._exec(ProcessKiller.argv(marker), None, kill=False), timeout=ProcessKiller.KILL_TIMEOUT_SECONDS)
        except Exception as exc:  # noqa: BLE001 — the kill is best-effort by contract
            logger.warning("Best-effort kill in pod %s failed: %s", self.id, exc)


class KubernetesSandboxProvider(SandboxProvider):
    """Pod-per-sandbox provider over the synchronous Kubernetes client."""

    capabilities = SandboxCapabilities(
        isolation=IsolationTier.CONTAINER,
        shell=True,
        languages=["python"],  # the default; each instance declares its language_runtimes keys
        files=True,
        package_ecosystems=["python"],  # the default; each instance declares its package_installers keys
        stateful=False,
        attach=True,
        provisions=True,
        attaches_external=True,  # attach_to binds to a '<namespace>/<pod>' the framework did not create
        principal_user=True,  # user mode via RBAC impersonation headers (see _apis_for)
        policy_network=False,  # flips True per instance via network_policy (operator-asserted CNI enforcement)
        policy_filesystem=True,  # readOnlyRootFilesystem + emptyDir workdir
        policy_resources=True,  # requests=limits from policy cpu/memory_mb
    )

    def __init__(self, config: Any, idle_timeout: int) -> None:
        """Store the config; API clients are created lazily on first use. ``idle_timeout``
        (the profile's) sizes the pod's ``activeDeadlineSeconds`` orphan ceiling."""
        super().__init__(config)
        self._idle_timeout = idle_timeout
        self._core_api: Optional[Any] = None
        self._networking_api: Optional[Any] = None
        # Impersonating client pairs cached per (user, groups) subject (the ec2_ssm pattern).
        self._subject_apis: dict[tuple[str, tuple[str, ...]], tuple[Any, Any]] = {}
        self._installer = PackageInstaller.from_config(config)
        self._runtimes = dict(config.language_runtimes)
        overrides: dict[str, Any] = {"languages": list(self._runtimes), "package_ecosystems": self._installer.ecosystems}
        if config.network_policy:
            # Instance-level capability override (#503): whether NetworkPolicy is actually
            # enforced depends on the cluster CNI, which the provider cannot detect; the
            # operator asserts it per instance. The class default stays honest (False).
            overrides["policy_network"] = True
        self.capabilities = type(self).capabilities.derive(**overrides)
        self._kill_enabled = not config.attach_to
        self._shell_pods: dict[str, bool] = {}  # '<namespace>/<pod>' -> whether it has /bin/sh

    def _handle(self, api: Any, namespace: str, pod_name: str) -> "KubernetesSandbox":
        """Wrap a pod in a handle carrying this instance's capabilities, installer and runtimes."""
        return KubernetesSandbox(
            api,
            namespace,
            pod_name,
            capabilities=self.capabilities,
            installer=self._installer,
            runtimes=self._runtimes,
            kill_enabled=self._kill_enabled,
            shell_cache=self._shell_pods,
        )

    def _apis(self) -> tuple[Any, Any]:
        """Return the lazily created ``(CoreV1Api, NetworkingV1Api)`` pair."""
        if self._core_api is None:
            if self._config.kubeconfig:
                kubernetes.config.load_kube_config(config_file=self._config.kubeconfig)
            else:
                try:
                    kubernetes.config.load_incluster_config()
                except Exception:  # noqa: BLE001 — outside a cluster: fall back to the default kubeconfig
                    kubernetes.config.load_kube_config()
            self._core_api = kubernetes.client.CoreV1Api()
            self._networking_api = kubernetes.client.NetworkingV1Api()
        return self._core_api, self._networking_api

    def _apis_for(self, principal: SandboxPrincipal) -> tuple[Any, Any]:
        """The ``(CoreV1Api, NetworkingV1Api)`` pair for this principal: the worker's own
        identity in agent mode, or a cached per-(user, groups) client whose ``Impersonate-*``
        headers make the API server enforce the invoking user's own RBAC on every call it is
        used for (pod create/read, exec, NetworkPolicy creation)."""
        if principal.mode != "user":
            return self._apis()
        user = principal.credentials.get("user") or principal.subject
        groups = tuple(principal.credentials.get("groups") or principal.groups or ())
        if not user:
            raise SandboxPolicyError("user-mode principal carries no user identity to impersonate (set credentials['user'] or subject)")
        if len(groups) > 1:
            raise SandboxPolicyError(
                "the kubernetes python client cannot send repeated Impersonate-Group headers, so user-mode "
                f"impersonation supports at most one group (got {list(groups)}); bind RBAC to the user or a single group"
            )
        key = (user, groups)
        cached = self._subject_apis.get(key)
        if cached is not None:
            return cached
        self._apis()  # loads kubeconfig/in-cluster credentials into the default client configuration
        api_client = kubernetes.client.ApiClient(kubernetes.client.Configuration.get_default_copy())
        api_client.set_default_header("Impersonate-User", user)
        if groups:
            api_client.set_default_header("Impersonate-Group", groups[0])
        pair = (kubernetes.client.CoreV1Api(api_client), kubernetes.client.NetworkingV1Api(api_client))
        self._subject_apis[key] = pair
        return pair

    async def create(self, *, principal: SandboxPrincipal, policy: SandboxPolicy) -> Sandbox:
        """Provision a sandbox pod with the policy mapped onto the manifest and wait for it
        to reach Running; with ``attach_to`` configured, attach to that pod instead (mode 3)."""
        if self._config.attach_to:
            return await self.attach(self._config.attach_to, principal=principal, policy=policy)
        core, networking = self._apis_for(principal)
        name = f"ak-sandbox-{uuid.uuid4().hex[:12]}"
        namespace = self._config.namespace
        # Built (and validated) before any API call so an unenforceable allowlist rejects cleanly.
        netpol = self._network_policy_manifest(name, namespace, policy)
        manifest = self._pod_manifest(name, namespace, policy)
        if netpol is not None:
            # Created before the pod so it never runs a single instant unrestricted.
            await asyncio.to_thread(networking.create_namespaced_network_policy, namespace=namespace, body=netpol)
        try:
            await asyncio.to_thread(core.create_namespaced_pod, namespace=namespace, body=manifest)
        except Exception as exc:  # noqa: BLE001 — any create failure must not orphan the pre-created NetworkPolicy
            await self._cleanup(name, namespace)
            raise SandboxProvisionError(f"creating sandbox pod '{namespace}/{name}' failed: {exc}") from exc
        try:
            await self._wait_running(core, name, namespace)
        except Exception:
            await self._cleanup(name, namespace)  # no orphan from a failed create
            raise
        return self._handle(core, namespace, name)

    def _pod_manifest(self, name: str, namespace: str, policy: SandboxPolicy) -> dict:
        """Build the pod manifest: hardened securityContext defaults under the config
        overlays (config wins per key), with the ``SandboxPolicy`` mapped on top."""
        container_sc: dict = {"allowPrivilegeEscalation": False, "seccompProfile": {"type": "RuntimeDefault"}, "capabilities": {"drop": ["ALL"]}}
        container_sc.update(self._config.container_security_context)
        container: dict = {
            "name": "sandbox",
            "image": self._config.image,
            # sleep runs as PID 1 directly, so PID 1 is never `sh`; the timeout path's
            # marker kill (ProcessKiller) also skips PID 1 as a second guard.
            "command": ["sleep", "infinity"],
            "workingDir": WORKDIR,
            "securityContext": container_sc,
        }
        if self._config.env:
            container["env"] = [{"name": key, "value": value} for key, value in self._config.env.items()]
        if policy.cpu is not None or policy.memory_mb is not None:
            amounts: dict = {}
            if policy.cpu is not None:
                amounts["cpu"] = str(policy.cpu)
            if policy.memory_mb is not None:
                amounts["memory"] = f"{policy.memory_mb}Mi"
            container["resources"] = {"requests": dict(amounts), "limits": dict(amounts)}
        spec: dict = {
            "restartPolicy": "Never",
            # The platform-side orphan ceiling: a session pod outliving it self-heals through
            # SandboxGoneError with the recreated-empty notice.
            "activeDeadlineSeconds": int(2 * self._idle_timeout),
            "terminationGracePeriodSeconds": 5,
            "containers": [container],
        }
        if policy.fs_allow_read or policy.fs_allow_write:
            container_sc["readOnlyRootFilesystem"] = True  # enforcement wins over the overlay
            container["volumeMounts"] = [{"name": "workspace", "mountPath": WORKDIR}]
            spec["volumes"] = [{"name": "workspace", "emptyDir": {}}]
        if self._config.service_account:
            spec["serviceAccountName"] = self._config.service_account
        if self._config.image_pull_secrets:
            spec["imagePullSecrets"] = [{"name": secret} for secret in self._config.image_pull_secrets]
        if self._config.node_selector:
            spec["nodeSelector"] = dict(self._config.node_selector)
        if self._config.security_context:
            spec["securityContext"] = dict(self._config.security_context)
        labels = {**_MANAGED_LABELS, **self._config.labels, _NAME_LABEL: name}
        return {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": name, "namespace": namespace, "labels": labels}, "spec": spec}

    def _network_policy_manifest(self, name: str, namespace: str, policy: SandboxPolicy) -> Optional[dict]:
        """Build the per-pod egress NetworkPolicy, or None when nothing is to be mapped.
        Domain names are unenforceable at L3/L4: ``strict`` rejects them, otherwise they are
        dropped with a WARNING and only CIDR entries are enforced."""
        if not self._config.network_policy or policy.network_egress == "allow":
            return None
        egress: list = []
        if policy.network_egress == "allowlist":
            cidrs: list[str] = []
            domains: list[str] = []
            for entry in policy.network_allow:
                try:
                    ipaddress.ip_network(entry, strict=False)
                    cidrs.append(entry)
                except ValueError:
                    domains.append(entry)
            if domains:
                if policy.strict:
                    raise SandboxPolicyError(f"NetworkPolicy cannot enforce domain-name egress entries {domains}; use CIDRs, or set strict=false")
                logger.warning("Ignoring unenforceable domain-name egress entries %s (strict=false); only CIDR entries are enforced", domains)
            if cidrs:
                egress = [{"to": [{"ipBlock": {"cidr": cidr}} for cidr in cidrs]}]
        return {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "NetworkPolicy",
            "metadata": {"name": name, "namespace": namespace, "labels": dict(_MANAGED_LABELS)},
            "spec": {"podSelector": {"matchLabels": {_NAME_LABEL: name}}, "policyTypes": ["Egress"], "egress": egress},
        }

    async def _wait_running(self, core: Any, name: str, namespace: str) -> None:
        """Poll the pod until Running, failing on a terminal phase or after ``create_timeout``.
        Reads with the caller's client, so user-mode waits run under the same impersonated RBAC."""
        deadline = time.monotonic() + self._config.create_timeout
        while True:
            pod = await asyncio.to_thread(core.read_namespaced_pod, name, namespace)
            phase = getattr(pod.status, "phase", None)
            if phase == "Running":
                return
            if phase in _TERMINAL_PHASES:
                raise SandboxProvisionError(f"sandbox pod '{namespace}/{name}' terminated during provisioning: {self._pod_detail(pod, phase)}")
            if time.monotonic() >= deadline:
                raise SandboxProvisionError(
                    f"sandbox pod '{namespace}/{name}' did not reach Running within {self._config.create_timeout}s: {self._pod_detail(pod, phase)}"
                )
            await asyncio.sleep(0.25)

    @staticmethod
    def _pod_detail(pod: Any, phase: Optional[str]) -> str:
        """The pod's last condition message, falling back to its phase."""
        conditions = getattr(pod.status, "conditions", None) or []
        message = getattr(conditions[-1], "message", None) if conditions else None
        return message or phase or "unknown"

    async def attach(self, sandbox_id: str, *, principal: SandboxPrincipal, policy: SandboxPolicy) -> Sandbox:
        """Reattach to a pod by ``<namespace>/<pod>`` (a bare name uses the configured
        namespace); a missing, terminating, or terminated pod raises ``SandboxGoneError``."""
        core, _ = self._apis_for(principal)
        namespace, name = self._parse_id(sandbox_id)
        try:
            pod = await asyncio.to_thread(core.read_namespaced_pod, name, namespace)
        except kubernetes.client.rest.ApiException as exc:
            if exc.status == 404:
                self._shell_pods.pop(f"{namespace}/{name}", None)  # deleted elsewhere: drop its cached probe answer
                raise SandboxGoneError(f"sandbox pod '{namespace}/{name}' no longer exists") from exc
            raise
        if getattr(pod.metadata, "deletion_timestamp", None) is not None or getattr(pod.status, "phase", None) in _TERMINAL_PHASES:
            self._shell_pods.pop(f"{namespace}/{name}", None)
            raise SandboxGoneError(f"sandbox pod '{namespace}/{name}' is terminating or terminated")
        if getattr(pod.status, "phase", None) == "Pending":
            await self._wait_running(core, name, namespace)  # the same bounded wait as create
        return self._handle(core, namespace, name)

    async def destroy(self, sandbox_id: str) -> None:
        """Delete the pod and its NetworkPolicy if one exists. Idempotent; 404s are no-ops.
        Runs under the worker's own identity: disposal is platform-owned (the ABC carries no
        principal here, and the idle sweep destroys with no user in context either)."""
        namespace, name = self._parse_id(sandbox_id)
        await self._cleanup(name, namespace)
        self._shell_pods.pop(f"{namespace}/{name}", None)

    def _parse_id(self, sandbox_id: str) -> tuple[str, str]:
        """Split ``<namespace>/<pod>``; a bare pod name uses the configured namespace."""
        if "/" in sandbox_id:
            namespace, name = sandbox_id.split("/", 1)
            return namespace, name
        return self._config.namespace, sandbox_id

    async def _cleanup(self, name: str, namespace: str) -> None:
        """Delete the pod and (when this instance manages them) its NetworkPolicy; 404s are
        no-ops. The NetworkPolicy delete is gated on ``network_policy`` because only that
        posture grants the worker the networkpolicies RBAC verbs."""
        core, networking = self._apis()
        if self._config.network_policy:
            try:
                await asyncio.to_thread(networking.delete_namespaced_network_policy, name, namespace)
            except kubernetes.client.rest.ApiException as exc:
                if exc.status != 404:
                    raise
        try:
            await asyncio.to_thread(core.delete_namespaced_pod, name, namespace)
        except kubernetes.client.rest.ApiException as exc:
            if exc.status != 404:
                raise
