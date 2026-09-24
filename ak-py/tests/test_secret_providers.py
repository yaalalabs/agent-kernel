import subprocess
import sys

import pytest
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError
from test_secret_manager import _DictSecretProvider

import agentkernel.secret
from agentkernel.core.util.factory import AKConfigError
from agentkernel.secret import EnvSecretProvider, SecretError
from agentkernel.secret.providers.aws_ssm import AWSSMSecretProvider
from agentkernel.secret.testing import SecretProviderContract

_PREFIX = "myproduct-dev-agents"


class _FakeSSMClient:
    """Stands in for a boto3 SSM client: a parameter dict, a call log, and an optional forced error.

    An unknown name raises a real botocore ClientError with code ParameterNotFound, as SSM does.
    """

    def __init__(self) -> None:
        self.parameters: dict[str, str] = {}
        self.calls: list[dict] = []
        self.error: Exception | None = None

    def get_parameter(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        name = kwargs["Name"]
        if name not in self.parameters:
            raise _client_error("ParameterNotFound")
        return {"Parameter": {"Name": name, "Type": "SecureString", "Value": self.parameters[name]}}


def _client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": f"{code} message"}}, "GetParameter")


@pytest.fixture
def ssm_client(monkeypatch):
    fake = _FakeSSMClient()
    created = []

    def _client(service, **kwargs):
        created.append(service)
        return fake

    monkeypatch.setattr("agentkernel.secret.providers.aws_ssm.boto3.client", _client)
    fake.created = created
    return fake


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


class TestAWSSMProviderContract(SecretProviderContract):
    @pytest.fixture(autouse=True)
    def _keep_client(self, ssm_client):
        self._client = ssm_client

    @pytest.fixture
    def provider(self):
        return AWSSMSecretProvider(prefix=_PREFIX)

    def seed(self, provider, key, value):
        self._client.parameters[f"/ak/{_PREFIX}/{key.lower()}"] = value


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


# -- AWSSMSecretProvider -------------------------------------------------------------------


def test_aws_ssm_addresses_lowercased_key_under_prefix(ssm_client):
    ssm_client.parameters[f"/ak/{_PREFIX}/openai_api_key"] = "sk-test"

    assert AWSSMSecretProvider(prefix=_PREFIX).get_secret("OPENAI_API_KEY") == "sk-test"
    assert ssm_client.calls == [{"Name": f"/ak/{_PREFIX}/openai_api_key", "WithDecryption": True}]


@pytest.mark.parametrize("prefix", ["p", "/p", "p/", "/p/"])
def test_aws_ssm_strips_leading_and_trailing_slashes(ssm_client, prefix):
    AWSSMSecretProvider(prefix=prefix).get_secret("OPENAI_API_KEY")
    assert ssm_client.calls[-1]["Name"] == "/ak/p/openai_api_key"


@pytest.mark.parametrize("prefix", ["", "/", "a/b", "/a/b/"])
def test_aws_ssm_rejects_empty_or_nested_prefix(prefix):
    with pytest.raises(AKConfigError) as exc_info:
        AWSSMSecretProvider(prefix=prefix)
    assert "secret.prefix" in str(exc_info.value)


def test_aws_ssm_empty_prefix_message_names_the_env_var():
    with pytest.raises(AKConfigError) as exc_info:
        AWSSMSecretProvider(prefix="")
    assert "AK_SECRET__PREFIX" in str(exc_info.value)


def test_aws_ssm_parameter_not_found_is_a_miss(ssm_client):
    assert AWSSMSecretProvider(prefix=_PREFIX).get_secret("OPENAI_API_KEY") is None


@pytest.mark.parametrize(
    "error",
    [
        _client_error("AccessDeniedException"),
        _client_error("ThrottlingException"),
        _client_error("SomethingNobodyHasSeen"),
        NoCredentialsError(),
    ],
    ids=["access-denied", "throttling", "unrecognized-code", "botocore-error"],
)
def test_aws_ssm_failures_raise_secret_error(ssm_client, error):
    ssm_client.error = error
    with pytest.raises(SecretError) as exc_info:
        AWSSMSecretProvider(prefix=_PREFIX).get_secret("OPENAI_API_KEY")
    assert f"/ak/{_PREFIX}/openai_api_key" in str(exc_info.value)
    assert exc_info.value.__cause__ is error


def test_aws_ssm_botocore_error_is_named_by_type(ssm_client):
    ssm_client.error = NoCredentialsError()
    with pytest.raises(SecretError) as exc_info:
        AWSSMSecretProvider(prefix=_PREFIX).get_secret("OPENAI_API_KEY")
    assert "NoCredentialsError" in str(exc_info.value)
    assert isinstance(ssm_client.error, BotoCoreError)


def test_aws_ssm_value_never_appears_in_a_later_error(ssm_client):
    provider = AWSSMSecretProvider(prefix=_PREFIX)
    ssm_client.parameters[f"/ak/{_PREFIX}/openai_api_key"] = "sk-very-secret"
    assert provider.get_secret("OPENAI_API_KEY") == "sk-very-secret"

    ssm_client.error = _client_error("ThrottlingException")
    with pytest.raises(SecretError) as exc_info:
        provider.get_secret("OPENAI_API_KEY")
    assert "sk-very-secret" not in str(exc_info.value)
    assert "sk-very-secret" not in repr(exc_info.value)


def test_aws_ssm_client_is_created_lazily_and_once(ssm_client):
    provider = AWSSMSecretProvider(prefix=_PREFIX)
    assert ssm_client.created == []

    provider.get_secret("OPENAI_API_KEY")
    provider.get_secret("OTHER_KEY")
    assert ssm_client.created == ["ssm"]
