"""LambdaProtocolGuard: the cold-start checks the A2A / MCP request-Lambda host runs (#932).

Every check passes on a deployment the host accepts and fails on one that would otherwise fail later, on the first
call, with a message that names the setting and the fix.
"""

import pytest

from agentkernel.core.config import AKConfig
from agentkernel.core.util.factory import AKConfigError
from agentkernel.deployment.aws.serverless.core.protocol_host import LambdaProtocolGuard
from agentkernel.identity import IdentityProviderFactory

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
def _deployment(monkeypatch, static_identity):
    """The accepted deployment, with an identity provider installed (``static_identity``)."""
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
        """MCP's own checks apply only while MCP is on: its default (stateful, localhost) is no objection when it is off."""
        _set(monkeypatch, AK_MCP__ENABLED="false", AK_MCP__STATELESS_HTTP="false", AK_MCP__URL="http://localhost:8000/mcp")

        LambdaProtocolGuard().check()

    def test_mcp_alone_passes_without_a2a(self, monkeypatch):
        _set(monkeypatch, AK_A2A__ENABLED="false", AK_A2A__URL="http://localhost:8000/a2a")

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

    def test_an_unset_mode_is_refused(self, monkeypatch):
        _unset(monkeypatch, "AK_EXECUTION__MODE")

        _refuses("got unset")

    def test_delta_replies_are_refused(self, monkeypatch):
        _set(monkeypatch, AK_EXECUTION__MESSAGE_TYPE="delta")

        _refuses(r"execution\.message_type complete only; got delta")


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


class TestSomethingToServe:
    def test_neither_a2a_nor_mcp_is_refused(self, monkeypatch):
        _set(monkeypatch, AK_A2A__ENABLED="false", AK_MCP__ENABLED="false")

        _refuses(r"nothing to serve.*a2a\.enabled or mcp\.enabled")


class TestIdentity:
    def test_no_identity_provider_is_refused(self, monkeypatch):
        monkeypatch.setattr(IdentityProviderFactory, "get", classmethod(lambda cls: None))

        _refuses(r"needs an identity block.*identity\.provider")


class TestResponseStore:
    def test_no_response_store_is_refused(self, monkeypatch):
        _unset(monkeypatch, "AK_EXECUTION__RESPONSE_STORE__TYPE")

        _refuses(r"shared execution\.response_store, but its type is 'unset'")

    def test_an_in_memory_response_store_is_refused(self, monkeypatch):
        _set(monkeypatch, AK_EXECUTION__RESPONSE_STORE__TYPE="in_memory")

        _refuses(r"shared execution\.response_store, but its type is 'in_memory'")

    @pytest.mark.parametrize("store", ["dynamodb", "redis", "valkey"])
    def test_a_shared_store_passes(self, monkeypatch, store):
        _set(monkeypatch, AK_EXECUTION__RESPONSE_STORE__TYPE=store)

        LambdaProtocolGuard().check()


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


class TestPublicUrls:
    @pytest.mark.parametrize("url", ["http://localhost:8000/a2a", "http://127.0.0.1:8000/a2a", "http://0.0.0.0:8000/a2a"])
    def test_a_local_a2a_url_is_refused(self, monkeypatch, url):
        _set(monkeypatch, AK_A2A__URL=url)

        _refuses(rf"a2a\.url is still '{url}'.*AK_A2A__URL")

    @pytest.mark.parametrize("url", ["http://localhost:8000/mcp", "http://127.0.0.1:8000/mcp", "http://0.0.0.0:8000/mcp"])
    def test_a_local_mcp_url_is_refused(self, monkeypatch, url):
        _set(monkeypatch, AK_MCP__URL=url)

        _refuses(rf"mcp\.url is still '{url}'.*AK_MCP__URL")

    def test_the_default_urls_are_local_and_refused(self, monkeypatch):
        _unset(monkeypatch, "AK_A2A__URL")

        _refuses(r"a2a\.url is still 'http://localhost:8000/a2a'")


class TestOrder:
    """The first failing check is the one reported, in the order the guard runs them."""

    def test_what_there_is_to_serve_comes_before_everything_else(self, monkeypatch):
        """A deployment that serves nothing is told so, whatever else is also wrong with it."""
        _set(monkeypatch, AK_A2A__ENABLED="false", AK_MCP__ENABLED="false", AK_EXECUTION__MODE="async", AK_EXECUTION__QUEUES__TYPE="kafka")
        _unset(monkeypatch, "API_VERSION")

        _refuses("nothing to serve")

    def test_the_mode_comes_before_the_transport_and_the_base_path_variables(self, monkeypatch):
        _set(monkeypatch, AK_EXECUTION__MODE="async", AK_EXECUTION__QUEUES__TYPE="kafka")
        _unset(monkeypatch, "API_VERSION")

        _refuses("got async")

    def test_the_transport_comes_before_the_base_path_variables(self, monkeypatch):
        _set(monkeypatch, AK_EXECUTION__QUEUES__TYPE="kafka")
        _unset(monkeypatch, "API_VERSION")

        _refuses("needs the sqs queue transport")

    def test_the_base_path_variables_come_before_the_a2a_and_mcp_settings(self, monkeypatch):
        _set(monkeypatch, AK_MCP__STATELESS_HTTP="false")
        _unset(monkeypatch, "API_VERSION")

        _refuses("needs API_VERSION in the environment")

    def test_the_identity_comes_before_the_response_store(self, monkeypatch):
        monkeypatch.setattr(IdentityProviderFactory, "get", classmethod(lambda cls: None))
        _unset(monkeypatch, "AK_EXECUTION__RESPONSE_STORE__TYPE")

        _refuses("needs an identity block")
