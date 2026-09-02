"""End-to-end test of the chart-deployed sandbox broker over NATS, on a kind cluster.

Builds the three example images, installs the ak-k8s chart with values-dev.yaml plus this
example's sandbox-values.yaml (sandbox worker tier + hardened namespace), and drives the
README walkthrough through the REST API: a bounded-wait execution, a promotion, the
check_sandbox_task recovery, and the default-deny egress sentinel.

Skipped when docker, kind, kubectl, helm, or an OpenAI key is unavailable.
"""

import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
import pytest

HERE = Path(__file__).parent
CHART = (HERE / "../../../ak-deployment/ak-k8s/chart").resolve()
KIND_CLUSTER = "ak-sandbox-nats"
KUBE_CONTEXT = f"kind-{KIND_CLUSTER}"
IMAGES = ["ak-sbx-io-handler:dev", "ak-sbx-agent-runner:dev", "ak-sbx-sandbox-worker:dev"]
API_PORT = 18080
API_URL = f"http://localhost:{API_PORT}"
# Separate sessions so no test can pass on conversation memory: the sandbox pod's hostname
# (ak-sandbox-<hex>) is a runtime-only fact a session's model has never seen, which keeps
# every assertion grounded in an execution that actually happened.
SESSION_QUICK = f"e2e-a-{uuid.uuid4().hex[:8]}"
SESSION_SLOW = f"e2e-b-{uuid.uuid4().hex[:8]}"
SESSION_EGRESS = f"e2e-c-{uuid.uuid4().hex[:8]}"


def _run(*args: str, cwd: Path | None = None) -> None:
    subprocess.run(list(args), cwd=cwd, check=True)


def _kubectl(*args: str) -> None:
    _run("kubectl", "--context", KUBE_CONTEXT, *args)


def _chat(prompt: str, session_id: str, timeout: float = 180.0) -> str:
    payload = {"prompt": prompt, "session_id": session_id, "agent": "coder"}
    response = httpx.post(f"{API_URL}/api/v1/chat", json=payload, timeout=timeout)
    response.raise_for_status()
    result = response.json().get("result", "")
    print(f"\n[chat] {payload['prompt']}\n[reply] {result}", flush=True)  # visible with pytest -s
    return result


def _wait_for_api(timeout: float = 120.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{API_URL}/health", timeout=2.0).status_code == 200:
                return
        except httpx.HTTPError:
            time.sleep(2)
    raise TimeoutError("the pipeline's REST API never became healthy")


@pytest.fixture(scope="session")
def deployment():
    """Images, kind cluster, chart install, port-forward; all torn down afterwards."""
    for tool in ("docker", "kind", "kubectl", "helm"):
        if shutil.which(tool) is None:
            pytest.skip(f"{tool} is not installed or not in PATH")
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY is not set; skipping integration test")

    _run("./package.sh", "local", cwd=HERE / "deploy")

    clusters = subprocess.run(["kind", "get", "clusters"], capture_output=True, text=True, check=True).stdout.split()
    created_cluster = KIND_CLUSTER not in clusters
    if created_cluster:
        _run("kind", "create", "cluster", "--name", KIND_CLUSTER, "--wait", "120s")
    _run("kind", "load", "docker-image", *IMAGES, "--name", KIND_CLUSTER)
    # Pre-pull the sandbox pod image INSIDE the node (kind load docker-image chokes on
    # multi-arch registry images under docker's containerd image store), so the first pod
    # create stays inside the profile's create_timeout.
    _run("docker", "exec", f"{KIND_CLUSTER}-control-plane", "crictl", "pull", "docker.io/library/python:3.12-slim")

    _kubectl("delete", "secret", "openai", "--ignore-not-found")
    _kubectl("create", "secret", "generic", "openai", f"--from-literal=api-key={os.environ['OPENAI_API_KEY']}")
    _run("helm", "dependency", "build", str(CHART))
    _run(
        "helm", "--kube-context", KUBE_CONTEXT, "upgrade", "--install", "ak", str(CHART),
        "-f", str(CHART / "values-dev.yaml"), "-f", str(HERE / "sandbox-values.yaml"),
        "--wait", "--timeout", "600s",
    )  # fmt: skip

    port_forward = subprocess.Popen(
        ["kubectl", "--context", KUBE_CONTEXT, "port-forward", "service/ak-agent-kernel-io", f"{API_PORT}:80"],
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    try:
        _wait_for_api()
        yield
    finally:
        port_forward.terminate()
        # Diagnostics before teardown, so a red run is explainable from the pytest output alone.
        for deployment_name in ("ak-agent-kernel-sandbox-worker", "ak-agent-kernel-agent-runner"):
            subprocess.run(
                ["kubectl", "--context", KUBE_CONTEXT, "logs", f"deployment/{deployment_name}", "--tail=120"],
                check=False,
            )
        subprocess.run(
            ["kubectl", "--context", KUBE_CONTEXT, "get", "pods", "-n", "ak-sandboxes", "-o", "wide"], check=False
        )
        subprocess.run(["helm", "--kube-context", KUBE_CONTEXT, "uninstall", "ak"], check=False)
        subprocess.run(
            ["kubectl", "--context", KUBE_CONTEXT, "delete", "namespace", "ak-sandboxes", "--ignore-not-found"],
            check=False,
        )
        if created_cluster:
            subprocess.run(["kind", "delete", "cluster", "--name", KIND_CLUSTER], check=False)


@pytest.mark.order(1)
def test_sandbox_executes_within_the_bounded_wait(deployment):
    # runner pod -> SANDBOX_REQUESTS -> worker -> pod in ak-sandboxes -> SANDBOX_COMPLETIONS
    # -> Valkey -> the runner's bounded poll, all inside one chat turn. The pod's generated
    # hostname is a fact the model cannot invent, so the assertion proves real execution.
    response = _chat(
        "Run python in the sandbox: import socket; print(socket.gethostname()) . Reply with only the output.",
        SESSION_QUICK,
    )
    assert "ak-sandbox-" in response


@pytest.mark.order(2)
def test_long_execution_promotes_to_a_pending_task(deployment):
    response = _chat(
        "Run python in the sandbox: import time, socket; time.sleep(30); print('LATE-' + socket.gethostname()) . "
        "If the sandbox reports the execution as pending, reply with exactly PENDING and the task id.",
        SESSION_SLOW,
    )
    assert "PENDING" in response.upper()


@pytest.mark.order(3)
def test_recovery_via_check_sandbox_task(deployment):
    # The recovery contract: the turn above ended with a pending task; check_sandbox_task
    # returns the finished output. This session has never seen its pod's hostname, so the
    # LATE-ak-sandbox- reply can only come from the stored completion.
    time.sleep(35)
    response = _chat(
        "Check that pending sandbox task now with check_sandbox_task and reply with only the output it captured.",
        SESSION_SLOW,
    )
    assert "LATE-ak-sandbox-" in response


@pytest.mark.order(4)
def test_default_deny_egress_blocks_network(deployment):
    # A fixed reachable IP (no DNS, which deny-egress would also stall) with a short timeout:
    # blocked egress raises inside the sandbox and prints the hostname-grounded sentinel.
    response = _chat(
        "Run python in the sandbox: import socket, urllib.request\n"
        "try:\n"
        "    print(urllib.request.urlopen('http://1.1.1.1', timeout=3).status)\n"
        "except Exception:\n"
        "    print('BLOCKED-' + socket.gethostname())\n"
        "Reply with only the output.",
        SESSION_EGRESS,
    )
    assert "BLOCKED-ak-sandbox-" in response
