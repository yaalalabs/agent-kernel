"""
The CLI's token (spec `docs/specs/603-identity-rbac-registry/` 8.8, iteration 7).

`--token` (or `AK_CLI_TOKEN`) is authenticated once at start through the configured identity
provider, and the resulting principal rides every prompt the REPL runs. Without an identity block
the token is ignored with a warning and the CLI runs as the anonymous principal, as every other
surface does; a refused token exits with the reason instead of starting a REPL nobody can use.
"""

import builtins
import sys

import pytest
from test_cli import ScriptedInput, StubService

from agentkernel.cli import cli as cli_module
from agentkernel.cli.cli import CLI
from agentkernel.core.model import Principal
from agentkernel.identity import AuthenticationError, IdentityProvider, IdentityProviderFactory


class _Provider(IdentityProvider):
    name = "test"

    def __init__(self):
        self.calls = 0

    async def authenticate(self, credential, context=None):
        self.calls += 1
        if credential == "alice-secret":
            return Principal(subject="alice", provider=self.name, namespace="test")
        raise AuthenticationError("unknown token")


@pytest.fixture
def stub_service(monkeypatch):
    service = StubService()
    monkeypatch.setattr(cli_module, "AgentService", lambda: service)
    return service


@pytest.fixture
def provider(monkeypatch):
    instance = _Provider()
    monkeypatch.setattr(IdentityProviderFactory, "get", classmethod(lambda cls: instance))
    return instance


@pytest.fixture(autouse=True)
def _no_ambient_token(monkeypatch):
    monkeypatch.delenv("AK_CLI_TOKEN", raising=False)


def _runs(service: StubService) -> list[tuple]:
    return [call for call in service.calls if call[0] == "run_multi"]


class TestToken:
    @pytest.mark.asyncio
    async def test_the_token_is_authenticated_once_and_the_principal_rides_every_run(self, stub_service, provider, monkeypatch):
        monkeypatch.setattr(builtins, "input", ScriptedInput(["hello", "again", "!q"]))

        await CLI(token="alice-secret").run()

        assert [(prompt, principal.subject) for _, prompt, principal in _runs(stub_service)] == [("hello", "alice"), ("again", "alice")]
        assert provider.calls == 1

    @pytest.mark.asyncio
    async def test_the_environment_variable_is_the_default(self, stub_service, provider, monkeypatch):
        monkeypatch.setenv("AK_CLI_TOKEN", "alice-secret")
        monkeypatch.setattr(builtins, "input", ScriptedInput(["hello", "!q"]))

        await CLI().run()

        assert _runs(stub_service)[0][2].subject == "alice"

    @pytest.mark.asyncio
    async def test_an_explicit_token_wins_over_the_environment(self, stub_service, provider, monkeypatch):
        monkeypatch.setenv("AK_CLI_TOKEN", "nope")
        monkeypatch.setattr(builtins, "input", ScriptedInput(["hello", "!q"]))

        await CLI(token="alice-secret").run()

        assert _runs(stub_service)[0][2].subject == "alice"

    @pytest.mark.asyncio
    async def test_a_refused_token_exits_with_the_reason(self, stub_service, provider, monkeypatch):
        monkeypatch.setattr(builtins, "input", ScriptedInput(["hello", "!q"]))

        with pytest.raises(SystemExit, match="unknown token"):
            await CLI(token="nope").run()

        assert _runs(stub_service) == []

    @pytest.mark.asyncio
    async def test_no_token_runs_anonymous(self, stub_service, provider, monkeypatch):
        monkeypatch.setattr(builtins, "input", ScriptedInput(["hello", "!q"]))

        await CLI().run()

        assert _runs(stub_service)[0][2] is None
        assert provider.calls == 0

    @pytest.mark.asyncio
    async def test_a_token_without_an_identity_block_is_ignored_with_a_warning(self, stub_service, monkeypatch, caplog):
        monkeypatch.setattr(IdentityProviderFactory, "get", classmethod(lambda cls: None))
        monkeypatch.setattr(builtins, "input", ScriptedInput(["hello", "!q"]))

        with caplog.at_level("WARNING", logger="ak.cli"):
            await CLI(token="alice-secret").run()

        assert _runs(stub_service)[0][2] is None
        assert any("identity block" in record.getMessage() for record in caplog.records if record.name == "ak.cli")


class TestMain:
    def test_main_passes_the_token_flag(self, monkeypatch, stub_service):
        seen = {}

        async def _run(self):
            seen["token"] = self._token

        monkeypatch.setattr(CLI, "run", _run)
        monkeypatch.setattr(sys, "argv", ["agentkernel-cli", "--token", "alice-secret"])

        CLI.main()

        assert seen == {"token": "alice-secret"}

    def test_main_without_the_flag_leaves_the_token_to_the_environment(self, monkeypatch, stub_service):
        seen = {}

        async def _run(self):
            seen["token"] = self._token

        monkeypatch.setattr(CLI, "run", _run)
        monkeypatch.setattr(sys, "argv", ["agentkernel-cli"])
        monkeypatch.setenv("AK_CLI_TOKEN", "from-env")

        CLI.main()

        assert seen == {"token": "from-env"}
