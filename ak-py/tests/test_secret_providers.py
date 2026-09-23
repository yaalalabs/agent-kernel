import subprocess
import sys

import pytest
from test_secret_manager import _DictSecretProvider

import agentkernel.secret
from agentkernel.secret import EnvSecretProvider
from agentkernel.secret.testing import SecretProviderContract


class TestEnvProviderContract(SecretProviderContract):
    reads_environment = True

    @pytest.fixture(autouse=True)
    def _keep_monkeypatch(self, monkeypatch):
        # seed writes the environment, so it needs the test's monkeypatch to undo the write.
        self._monkeypatch = monkeypatch

    @pytest.fixture
    def provider(self):
        return EnvSecretProvider()

    def seed(self, provider, key, value):
        self._monkeypatch.setenv(key, value)


class TestDictProviderContract(SecretProviderContract):
    """Holds the double the manager tests rely on to the same contract."""

    @pytest.fixture
    def provider(self):
        return _DictSecretProvider()

    def seed(self, provider, key, value):
        provider.seed(key, value)


def test_env_provider_treats_empty_variable_as_absent(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    assert EnvSecretProvider().get_secret("OPENAI_API_KEY") is None


def test_contract_suite_is_not_exported():
    assert "SecretProviderContract" not in agentkernel.secret.__all__
    assert not hasattr(agentkernel.secret, "SecretProviderContract")


def test_import_does_not_load_testing_module(tmp_path):
    # Fresh interpreter so the check sees only what `import agentkernel.secret` itself pulls in.
    code = (
        "import sys\n"
        "import agentkernel.secret\n"
        "assert 'agentkernel.secret.testing' not in sys.modules, 'testing loaded by import agentkernel.secret'\n"
        "assert 'pytest' not in sys.modules, 'pytest loaded by import agentkernel.secret'\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
