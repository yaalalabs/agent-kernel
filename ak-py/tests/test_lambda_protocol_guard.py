"""LambdaProtocolGuard: the cold-start checks the A2A / MCP request-Lambda host runs (#932).

Every check passes on a deployment the host accepts and fails on one that would otherwise fail later, on the first
call, with a message that names the setting and the fix.
"""

import pytest

from agentkernel.core.config import AKConfig
from agentkernel.core.util.factory import AKConfigError
from agentkernel.deployment.aws.serverless.core.protocol_host import LambdaProtocolGuard

PUBLIC_A2A_URL = "https://abc.execute-api.us-east-1.amazonaws.com/agents/api/v1/a2a"
PUBLIC_MCP_URL = "https://abc.execute-api.us-east-1.amazonaws.com/agents/api/v1/mcp"

# A deployment the host accepts: rest_sync on sqs with a shared response store, A2A and stateless MCP on, public URLs.
ACCEPTED = {
    "AK_CONFIG_PATH_OVERRIDE": "/nonexistent/config.yaml",
    "AK_EXECUTION__MODE": "rest_sync",
    "AK_EXECUTION__QUEUES__TYPE": "sqs",
    "AK_EXECUTION__RESPONSE_STORE__TYPE": "dynamodb",
    "AK_A2A__ENABLED": "true",
    "AK_A2A__URL": PUBLIC_A2A_URL,
    "AK_MCP__ENABLED": "true",
    "AK_MCP__EXPOSE_AGENTS": "true",
    "AK_MCP__STATELESS_HTTP": "true",
    "AK_MCP__URL": PUBLIC_MCP_URL,
    "API_BASE_PATH": "api",
    "API_VERSION": "v1",
    "AGENT_ENDPOINT": "agent",
}


@pytest.fixture(autouse=True)
def _deployment(monkeypatch):
    """The accepted deployment."""
    for name, value in ACCEPTED.items():
        monkeypatch.setenv(name, value)
    AKConfig._reset()
    yield
    AKConfig._reset()


def _set(monkeypatch, **env: str) -> None:
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    AKConfig._reset()


def _unset(monkeypatch, *names: str) -> None:
    for name in names:
        monkeypatch.delenv(name, raising=False)
    AKConfig._reset()


def _refuses(match: str) -> None:
    with pytest.raises(AKConfigError, match=match):
        LambdaProtocolGuard().check()


class TestAnAcceptedDeployment:
    def test_every_check_passes(self):
        LambdaProtocolGuard().check()

    @pytest.mark.parametrize("mode", ["rest_sync", "rest_async"])
    def test_both_rest_modes_pass(self, monkeypatch, mode):
        _set(monkeypatch, AK_EXECUTION__MODE=mode)

        LambdaProtocolGuard().check()

    def test_a2a_alone_passes_without_mcp(self, monkeypatch):
        """The stateless check applies only while MCP is on: its default (stateful) is no objection when it is off."""
        _set(monkeypatch, AK_MCP__ENABLED="false", AK_MCP__STATELESS_HTTP="false")

        LambdaProtocolGuard().check()

    def test_mcp_alone_passes_without_a2a(self, monkeypatch):
        _set(monkeypatch, AK_A2A__ENABLED="false")

        LambdaProtocolGuard().check()


class TestMode:
    def test_async_is_refused_because_it_has_no_rest_api(self, monkeypatch):
        """The follow-up issue (#985) is in the code, not in the message a deployer reads."""
        _set(monkeypatch, AK_EXECUTION__MODE="async")

        with pytest.raises(AKConfigError, match=r"execution\.mode rest_sync or rest_async only; got async.*no REST API") as refused:
            LambdaProtocolGuard().check()

        assert "#985" not in str(refused.value)

    @pytest.mark.parametrize("mode", ["realtime"])
    def test_a_mode_with_no_rest_api_is_refused(self, monkeypatch, mode):
        _set(monkeypatch, AK_EXECUTION__MODE=mode, AK_EXECUTION__MESSAGE_TYPE="delta")

        _refuses(f"got {mode}")

    def test_an_unset_mode_runs_as_rest_sync_and_passes(self, monkeypatch):
        """The pipeline treats an unset mode as rest_sync (``execution.mode`` documents it), so the guard does too."""
        _unset(monkeypatch, "AK_EXECUTION__MODE")

        LambdaProtocolGuard().check()


class TestTransport:
    def test_a_transport_other_than_sqs_is_refused(self, monkeypatch):
        _set(monkeypatch, AK_EXECUTION__QUEUES__TYPE="kafka")

        _refuses(r"needs the sqs queue transport, but execution\.queues resolves to 'kafka'")

    def test_no_queues_block_resolves_to_in_memory_and_is_refused(self, monkeypatch):
        """Without a block the transport is in_memory: every call would be enqueued where no runner reads it, and time out."""
        _unset(monkeypatch, "AK_EXECUTION__QUEUES__TYPE")

        _refuses(r"resolves to 'in_memory'.*execution\.queues\.type: sqs")


class TestBasePathEnvironment:
    @pytest.mark.parametrize("name", ["API_BASE_PATH", "API_VERSION", "AGENT_ENDPOINT"])
    def test_each_missing_variable_is_named(self, monkeypatch, name):
        _unset(monkeypatch, name)

        _refuses(f"needs {name} in the environment")

    def test_all_missing_variables_are_named_at_once(self, monkeypatch):
        _unset(monkeypatch, "API_BASE_PATH", "API_VERSION", "AGENT_ENDPOINT")

        _refuses("needs API_BASE_PATH, API_VERSION, AGENT_ENDPOINT in the environment")


class TestResponseStore:
    def test_no_response_store_is_refused(self, monkeypatch):
        _unset(monkeypatch, "AK_EXECUTION__RESPONSE_STORE__TYPE")

        _refuses(r"need a shared response store")

    def test_an_in_memory_response_store_is_refused(self, monkeypatch):
        _set(monkeypatch, AK_EXECUTION__RESPONSE_STORE__TYPE="in_memory")

        _refuses(r"need a shared response store")

    @pytest.mark.parametrize("store", ["dynamodb", "redis", "valkey"])
    def test_a_shared_store_passes(self, monkeypatch, store):
        _set(monkeypatch, AK_EXECUTION__RESPONSE_STORE__TYPE=store)

        LambdaProtocolGuard().check()


class TestToolOnlyMcp:
    """MCP serving only the application's own tools runs no agent and enqueues nothing: no queue is needed."""

    @pytest.fixture(autouse=True)
    def _tool_only_mcp(self, monkeypatch):
        _set(monkeypatch, AK_A2A__ENABLED="false", AK_MCP__EXPOSE_AGENTS="false")

    def test_it_passes_without_a_queue_or_a_response_store(self, monkeypatch):
        _unset(monkeypatch, "AK_EXECUTION__QUEUES__TYPE", "AK_EXECUTION__RESPONSE_STORE__TYPE")

        LambdaProtocolGuard().check()

    def test_stateful_mcp_is_still_refused(self, monkeypatch):
        """Tool-only MCP has sessions too: the stateless rule is outside the agent-protocol block."""
        _set(monkeypatch, AK_MCP__STATELESS_HTTP="false")

        _refuses("needs mcp.stateless_http")

    def test_a_wait_budget_over_the_gateway_limit_is_no_objection(self, monkeypatch):
        """Nothing waits for a reply, so the 29 s limit does not matter: the same budget is refused when agents run."""
        _set(monkeypatch, AK_EXECUTION__RESPONSE_STORE__RETRY_COUNT="31", AK_EXECUTION__RESPONSE_STORE__DELAY="1")

        LambdaProtocolGuard().check()

    def test_the_lambda_checks_still_apply(self, monkeypatch):
        _set(monkeypatch, AK_EXECUTION__MODE="async")

        _refuses("got async")


class TestNoAgents:
    def test_a_registry_with_no_agents_warns_and_carries_on(self, caplog):
        with caplog.at_level("WARNING"):
            LambdaProtocolGuard().check()

        assert "no agents" in caplog.text.lower()


class TestStatelessMcp:
    def test_stateful_mcp_is_refused(self, monkeypatch):
        _set(monkeypatch, AK_MCP__STATELESS_HTTP="false")

        _refuses(r"mcp\.stateless_http: true.*another Lambda instance")


class TestWaitBudget:
    """The first read of the response store is immediate, so the wait is ``(retry_count - 1) x delay``."""

    @pytest.mark.parametrize(
        "retry_count, delay, budget",
        [(5, 5, 20), (30, 1, 29), (1, 100, 0), (2, 0.5, 0.5)],
    )
    def test_the_budget_is_one_read_fewer_than_the_retries(self, monkeypatch, retry_count, delay, budget):
        _set(monkeypatch, AK_EXECUTION__RESPONSE_STORE__RETRY_COUNT=str(retry_count), AK_EXECUTION__RESPONSE_STORE__DELAY=str(delay))

        assert LambdaProtocolGuard.wait_budget_seconds() == budget

    def test_the_gateway_limit_itself_passes(self, monkeypatch):
        _set(monkeypatch, AK_EXECUTION__RESPONSE_STORE__RETRY_COUNT="30", AK_EXECUTION__RESPONSE_STORE__DELAY="1")

        LambdaProtocolGuard().check()

    def test_a_wait_longer_than_the_gateway_limit_is_refused(self, monkeypatch):
        _set(monkeypatch, AK_EXECUTION__RESPONSE_STORE__RETRY_COUNT="31", AK_EXECUTION__RESPONSE_STORE__DELAY="1")

        _refuses(r"waits up to 30s.*API Gateway stops waiting at 29s.*retry_count or delay")

    def test_the_default_budget_passes(self):
        """5 reads 5 s apart wait 20 s, inside the gateway limit."""
        assert AKConfig.get().execution.response_store.retry_count == 5
        assert LambdaProtocolGuard.wait_budget_seconds() == 20


class TestOrder:
    """The first failing check is the one reported, in the order the guard runs them."""

    def test_the_mode_comes_before_the_base_path_variables(self, monkeypatch):
        _set(monkeypatch, AK_EXECUTION__MODE="async", AK_EXECUTION__QUEUES__TYPE="kafka")
        _unset(monkeypatch, "API_VERSION")

        _refuses("got async")

    def test_the_base_path_variables_come_before_the_stateless_check(self, monkeypatch):
        _set(monkeypatch, AK_MCP__STATELESS_HTTP="false")
        _unset(monkeypatch, "API_VERSION")

        _refuses("needs API_VERSION in the environment")

    def test_the_base_path_variables_come_before_the_transport(self, monkeypatch):
        _set(monkeypatch, AK_EXECUTION__QUEUES__TYPE="kafka")
        _unset(monkeypatch, "API_VERSION")

        _refuses("needs API_VERSION in the environment")

    def test_the_transport_comes_before_the_response_store(self, monkeypatch):
        _set(monkeypatch, AK_EXECUTION__QUEUES__TYPE="kafka")
        _unset(monkeypatch, "AK_EXECUTION__RESPONSE_STORE__TYPE")

        _refuses("needs the sqs queue transport")
