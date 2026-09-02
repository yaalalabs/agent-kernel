"""End-to-end test of the sandbox queue broker over Kafka against real infrastructure.

Kafka + Valkey come from docker-compose; sandbox pods run in a kind cluster whose
k8s/rbac.yaml binds the pod ServiceAccount to the `view` ClusterRole, so read-only kubectl
succeeds and writes come back Forbidden: RBAC is the boundary, never command parsing. The
worker is started the same way you would start it by hand (`python app.py worker`), and the
agent side is the CLI driven through the Test harness.

Skipped when docker, kind, kubectl, or an OpenAI key is unavailable.
"""

import asyncio
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from agentkernel.test import Test
from confluent_kafka.admin import AdminClient, NewTopic

BOOTSTRAP_SERVERS = "localhost:9092"
TOPICS = ["sandbox-input", "sandbox-output", "sandbox-input.dlq", "sandbox-output.dlq"]
CONSUMER_GROUP = "ak-sandbox-demo-input"
KIND_CLUSTER = "ak-sandbox-demo"
SANDBOX_IMAGE = "alpine/k8s:1.33.4"
HERE = Path(__file__).parent
COMPOSE_FILE = HERE / "docker-compose.yaml"
RBAC_FILE = HERE / "k8s" / "rbac.yaml"
KUBECONFIG_FILE = HERE / "kind-kubeconfig"

pytestmark = pytest.mark.asyncio(loop_scope="session")  # uses a single session for all tests


def _run(*args: str) -> None:
    subprocess.run(list(args), check=True)


def _ensure_topics() -> None:
    """Provision the four sandbox topics; Agent Kernel never creates topics itself."""
    admin = AdminClient({"bootstrap.servers": BOOTSTRAP_SERVERS})
    deadline = time.monotonic() + 90
    while True:
        try:
            existing = set(admin.list_topics(timeout=5).topics)
            break
        except Exception:
            if time.monotonic() > deadline:
                raise
            time.sleep(1)
    missing = [name for name in TOPICS if name not in existing]
    if missing:
        for name, future in admin.create_topics(
            [NewTopic(t, num_partitions=4, replication_factor=1) for t in missing]
        ).items():
            future.result()


def _kind_cluster_up() -> bool:
    """Create the kind cluster if absent (returning whether this run created it), export a
    local kubeconfig for the worker, apply the RBAC, and pre-pull the sandbox image so the
    first pod start stays inside the bounded wait."""
    clusters = subprocess.run(["kind", "get", "clusters"], capture_output=True, text=True, check=True).stdout.split()
    created = KIND_CLUSTER not in clusters
    if created:
        _run("kind", "create", "cluster", "--name", KIND_CLUSTER, "--wait", "120s")
    _run("kind", "export", "kubeconfig", "--name", KIND_CLUSTER, "--kubeconfig", str(KUBECONFIG_FILE))
    _run("kubectl", "--kubeconfig", str(KUBECONFIG_FILE), "apply", "-f", str(RBAC_FILE))
    # Pre-pull the sandbox image INSIDE the kind node (kind load docker-image chokes on
    # multi-arch images under docker's containerd image store), so the first pod create
    # stays inside the profile's create_timeout.
    _run("docker", "exec", f"{KIND_CLUSTER}-control-plane", "crictl", "pull", f"docker.io/{SANDBOX_IMAGE}")
    return created


def _wait_for_worker(timeout: float = 60.0) -> None:
    """The worker is ready once its input consumer group exists on the broker."""
    admin = AdminClient({"bootstrap.servers": BOOTSTRAP_SERVERS})
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            groups = admin.list_consumer_groups(request_timeout=5).result(timeout=10)
            if any(group.group_id == CONSUMER_GROUP for group in groups.valid):
                return
        except Exception:
            pass
        time.sleep(1)
    raise TimeoutError(f"the sandbox worker never joined consumer group {CONSUMER_GROUP}")


@pytest.fixture(scope="session")
def stack():
    """Kafka + Valkey, the kind cluster with RBAC, the topics, and the worker process."""
    for tool in ("docker", "kind", "kubectl"):
        if shutil.which(tool) is None:
            pytest.skip(f"{tool} is not installed or not in PATH")
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY is not set; skipping integration test")

    # Clean slate: a stack left behind by an interrupted run can hold a wedged broker.
    subprocess.run(["docker", "compose", "-f", str(COMPOSE_FILE), "down", "-v"], check=False)
    _run("docker", "compose", "-f", str(COMPOSE_FILE), "up", "-d", "--wait")
    created_cluster = _kind_cluster_up()
    _ensure_topics()
    worker = subprocess.Popen([sys.executable, "app.py", "worker"], stdout=sys.stdout, stderr=sys.stderr)
    try:
        _wait_for_worker()
        yield
    finally:
        worker.terminate()
        try:
            worker.wait(timeout=30)
        except subprocess.TimeoutExpired:
            worker.kill()
            worker.wait(timeout=10)
        subprocess.run(["docker", "compose", "-f", str(COMPOSE_FILE), "down", "-v"], check=False)
        if created_cluster:
            subprocess.run(["kind", "delete", "cluster", "--name", KIND_CLUSTER], check=False)


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def test_client(stack):
    test = Test("app.py")
    await test.start()
    try:
        yield test
    finally:
        await test.stop()


@pytest.mark.order(1)
async def test_readonly_kubectl_within_the_bounded_wait(test_client):
    # The whole path in one bounded call: CLI -> sandbox-input -> worker -> pod exec ->
    # sandbox-output -> response store -> CLI, all inside broker.wait_timeout.
    await test_client.send(
        "In the sandbox, run this shell command: kubectl get serviceaccount ak-sandbox-pod -o name . "
        "Reply with only the command's output."
    )
    await test_client.expect(["serviceaccount/ak-sandbox-pod"])


@pytest.mark.order(2)
async def test_write_rejected_by_rbac(test_client):
    # The `view` binding is the boundary: the API server rejects the write no matter what the
    # command string says. The sentinel keeps the assertion deterministic.
    await test_client.send(
        "In the sandbox, run this shell command: kubectl create namespace should-not-exist . "
        "If the output contains the word forbidden (any casing), reply with only the single word: DENIED. "
        "Otherwise reply with only the single word: ALLOWED."
    )
    await test_client.expect(["DENIED"])


@pytest.mark.order(3)
async def test_long_execution_promotes_and_recovers(test_client):
    # Longer than wait_timeout (8 s): the tool returns a pending task and the turn ends; the
    # recovery contract is check_sandbox_task, which returns the finished output later.
    marker = f"MARKER-{uuid.uuid4().hex[:8]}"
    response = await test_client.send(
        f"In the sandbox, run this shell command: sleep 20 && echo {marker} . "
        "If the sandbox reports the execution as pending, reply with exactly: PENDING and the task id."
    )
    assert "PENDING" in response.upper()
    await asyncio.sleep(25)
    await test_client.send(
        "Check that pending sandbox task now with check_sandbox_task and reply with only the output it captured."
    )
    await test_client.expect([marker])
