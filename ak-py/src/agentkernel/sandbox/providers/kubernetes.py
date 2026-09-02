"""``kubernetes`` provider — pod-per-sandbox via the Kubernetes Python client (``kubernetes`` extra).

Each sandbox is a pod running ``sleep infinity`` as PID 1; executions are exec calls through the
stream API (which inherit the container's ``/workspace`` working directory), and files
travel as single-member tars framed in base64 over the exec channels (``head -c N`` gives
the remote pipeline its EOF, since a WebSocket exec cannot half-close stdin). The SDK is
synchronous, so every call runs in ``asyncio.to_thread``.

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
import logging
import posixpath
import shlex
import tarfile
import time
import uuid
from typing import Any, Optional

import kubernetes
import kubernetes.client
import kubernetes.config
import kubernetes.stream

from ..base import Sandbox, SandboxProvider
from ..errors import SandboxCapabilityError, SandboxError, SandboxGoneError, SandboxPolicyError, SandboxProvisionError, SandboxTimeoutError
from ..model import IsolationTier, SandboxCapabilities, SandboxPolicy, SandboxPrincipal, SandboxResult

logger = logging.getLogger("ak.sandbox.provider")

WORKDIR = "/workspace"

# The sweep, operators, and the hardening NetworkPolicy find sandbox pods by these labels.
_MANAGED_LABELS = {"app.kubernetes.io/managed-by": "agent-kernel", "agentkernel.io/sandbox": "true"}
# Per-pod label the per-pod NetworkPolicy selects on; always set last so nothing displaces it.
_NAME_LABEL = "agentkernel.io/sandbox-name"

_TERMINAL_PHASES = ("Succeeded", "Failed")


def _safe_rel(path: str) -> str:
    """Resolve a caller path to a WORKDIR-relative POSIX path, rejecting absolute paths and
    ``..`` traversal that would escape the workdir (mirrors the docker provider's check)."""
    rel = path.lstrip("/")
    resolved = posixpath.normpath(posixpath.join(WORKDIR, rel))
    if resolved != WORKDIR and not resolved.startswith(WORKDIR + "/"):
        raise SandboxPolicyError(f"path '{path}' escapes the sandbox working directory")
    return posixpath.relpath(resolved, WORKDIR)


class KubernetesSandbox(Sandbox):
    """Handle to one running sandbox pod; executions are stream-API exec calls inside it."""

    def __init__(self, api: Any, namespace: str, pod_name: str) -> None:
        """Bind the handle to a pod; the id is ``<namespace>/<pod>`` (the ``attach_to`` format)."""
        self.id = f"{namespace}/{pod_name}"
        self._api = api
        self._namespace = namespace
        self._pod = pod_name

    async def execute_code(self, code: str, language: str = "python", timeout: float | None = None) -> SandboxResult:
        """Exec the language interpreter with the code (``python -c`` in v1)."""
        if language not in KubernetesSandboxProvider.capabilities.languages:
            raise SandboxCapabilityError(self.__class__.__name__, f"language:{language}")
        return await self._exec(["python", "-c", code], timeout)

    async def execute_command(self, command: str, timeout: float | None = None) -> SandboxResult:
        """Exec a shell command via ``/bin/sh -c``."""
        return await self._exec(["/bin/sh", "-c", command], timeout)

    async def install_packages(self, packages: list[str]) -> SandboxResult:
        """Exec ``pip install`` for the given packages."""
        return await self._exec(["pip", "install", *packages], None)

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

    async def _exec(self, argv: list[str], timeout: float | None, stdin_data: Optional[str] = None) -> SandboxResult:
        """Run one exec through the stream API in a thread under ``asyncio.wait_for``; on
        expiry make a best-effort kill of the exec'd process and raise ``SandboxTimeoutError``."""

        def run() -> tuple[str, str, int]:
            try:
                resp = kubernetes.stream.stream(
                    self._api.connect_get_namespaced_pod_exec,
                    self._pod,
                    self._namespace,
                    command=argv,
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
            while resp.is_open():
                resp.update(timeout=1)
                if resp.peek_stdout():
                    stdout_parts.append(resp.read_stdout())
                if resp.peek_stderr():
                    stderr_parts.append(resp.read_stderr())
            resp.close()
            exit_code = resp.returncode
            return "".join(stdout_parts), "".join(stderr_parts), exit_code if exit_code is not None else -1

        try:
            stdout, stderr, exit_code = await asyncio.wait_for(asyncio.to_thread(run), timeout=timeout)
        except asyncio.TimeoutError as exc:
            await self._best_effort_kill(argv[0])
            raise SandboxTimeoutError(f"kubernetes exec exceeded timeout {timeout}s") from exc
        return SandboxResult(stdout=stdout, stderr=stderr, exit_code=exit_code)

    async def _best_effort_kill(self, interpreter: str) -> None:
        """Kill the timed-out exec'd process by interpreter name. Safe because the
        concurrency contract allows at most one in-flight execution per sandbox."""
        try:
            await self._exec(["sh", "-c", f"pkill -9 {posixpath.basename(interpreter)}"], None)
        except Exception as exc:  # noqa: BLE001 — the kill is best-effort by contract
            logger.warning("Best-effort kill in pod %s failed: %s", self.id, exc)


class KubernetesSandboxProvider(SandboxProvider):
    """Pod-per-sandbox provider over the synchronous Kubernetes client."""

    capabilities = SandboxCapabilities(
        isolation=IsolationTier.CONTAINER,
        shell=True,
        languages=["python"],
        files=True,
        package_install=True,
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
        if config.network_policy:
            # Instance-level capability override (#503): whether NetworkPolicy is actually
            # enforced depends on the cluster CNI, which the provider cannot detect; the
            # operator asserts it per instance. The class default stays honest (False).
            self.capabilities = type(self).capabilities.model_copy(update={"policy_network": True})

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
        return KubernetesSandbox(core, namespace, name)

    def _pod_manifest(self, name: str, namespace: str, policy: SandboxPolicy) -> dict:
        """Build the pod manifest: hardened securityContext defaults under the config
        overlays (config wins per key), with the ``SandboxPolicy`` mapped on top."""
        container_sc: dict = {"allowPrivilegeEscalation": False, "seccompProfile": {"type": "RuntimeDefault"}, "capabilities": {"drop": ["ALL"]}}
        container_sc.update(self._config.container_security_context)
        container: dict = {
            "name": "sandbox",
            "image": self._config.image,
            # sleep runs as PID 1 directly: under `sh -c` PID 1 would be `sh`, and the
            # timeout path's best-effort `pkill sh` could kill it and take down the pod.
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
                raise SandboxGoneError(f"sandbox pod '{namespace}/{name}' no longer exists") from exc
            raise
        if getattr(pod.metadata, "deletion_timestamp", None) is not None or getattr(pod.status, "phase", None) in _TERMINAL_PHASES:
            raise SandboxGoneError(f"sandbox pod '{namespace}/{name}' is terminating or terminated")
        if getattr(pod.status, "phase", None) == "Pending":
            await self._wait_running(core, name, namespace)  # the same bounded wait as create
        return KubernetesSandbox(core, namespace, name)

    async def destroy(self, sandbox_id: str) -> None:
        """Delete the pod and its NetworkPolicy if one exists. Idempotent; 404s are no-ops.
        Runs under the worker's own identity: disposal is platform-owned (the ABC carries no
        principal here, and the idle sweep destroys with no user in context either)."""
        namespace, name = self._parse_id(sandbox_id)
        await self._cleanup(name, namespace)

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
