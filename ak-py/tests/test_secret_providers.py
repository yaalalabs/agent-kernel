import os
import subprocess
import sys

import pytest
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError
from test_secret_manager import _DictSecretProvider

import agentkernel.secret
from agentkernel.core.util.factory import AKConfigError
from agentkernel.secret import EnvSecretProvider, SecretError
from agentkernel.secret.providers.aws_ssm import AWSSMSecretProvider
from agentkernel.secret.providers.kubernetes import KubernetesSecretProvider
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


class TestKubernetesProviderContract(SecretProviderContract):
    @pytest.fixture(autouse=True)
    def _keep_root(self, tmp_path):
        self._root = tmp_path
        self._seeds = 0

    @pytest.fixture
    def provider(self, tmp_path):
        return KubernetesSecretProvider(str(tmp_path))

    def seed(self, provider, key, value):
        # Alternate Secret directories so the contract runs against the multi-Secret layout.
        directory = self._root / ("openai-credentials", "slack-credentials")[self._seeds % 2]
        self._seeds += 1
        directory.mkdir(exist_ok=True)
        (directory / key).write_bytes(value.encode("utf-8"))


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


def test_kubernetes_needs_no_sdk(tmp_path):
    # Fresh interpreter: the eager export and the factory branch must not pull in any SDK.
    code = (
        "import sys\n"
        "import agentkernel.secret\n"
        "from agentkernel.core.config import _SecretConfig\n"
        "from agentkernel.secret.factory import SecretProviderFactory\n"
        "SecretProviderFactory.get(_SecretConfig.model_validate({'provider': {'type': 'kubernetes'}}))\n"
        "assert 'kubernetes' not in sys.modules, 'kubernetes SDK imported'\n"
        "assert 'boto3' not in sys.modules, 'boto3 imported'\n"
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


# -- KubernetesSecretProvider --------------------------------------------------------------


def _write(path, value="v"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value.encode("utf-8"))


def _kubelet_secret(directory, revision, files):
    """Lay out a Secret directory the way the kubelet does: ..<rev>/KEY, ..data -> ..<rev>, KEY -> ..data/KEY."""
    directory.mkdir(parents=True, exist_ok=True)
    for name, value in files.items():
        _write(directory / revision / name, value)
    data = directory / "..data"
    if data.is_symlink():
        data.unlink()
    data.symlink_to(revision)
    for name in files:
        link = directory / name
        if not link.is_symlink():
            link.symlink_to(f"..data/{name}")


def test_kubernetes_resolves_kubelet_layout_and_repointed_data(tmp_path):
    secret = tmp_path / "creds"
    _kubelet_secret(secret, "..2026_10_08_00_00_00.1", {"KEY": "old"})
    provider = KubernetesSecretProvider(str(tmp_path))
    assert provider.get_secret("KEY") == "old"

    _kubelet_secret(secret, "..2026_10_08_00_00_01.2", {"KEY": "new", "ADDED": "added"})
    assert provider.get_secret("KEY") == "new"
    assert provider.get_secret("ADDED") == "added"


def test_kubernetes_reads_top_level_key(tmp_path):
    _write(tmp_path / "KEY", "top")
    assert KubernetesSecretProvider(str(tmp_path)).get_secret("KEY") == "top"


@pytest.mark.parametrize(
    "layout",
    [
        {"a/KEY": "one-secret", "b/KEY": "two-secret"},
        {"KEY": "one-secret", "b/KEY": "two-secret"},
        {"a/KEY": "", "b/KEY": "two-secret"},
    ],
)
def test_kubernetes_duplicates_raise_without_leaking_values(tmp_path, layout):
    for rel, value in layout.items():
        _write(tmp_path / rel, value)
    with pytest.raises(SecretError) as info:
        KubernetesSecretProvider(str(tmp_path)).get_secret("KEY")
    message = str(info.value)
    assert "one-secret" not in message and "two-secret" not in message
    assert all(str(tmp_path / rel) in message for rel in layout)


def test_kubernetes_skips_dot_entries_when_secret_is_mounted_directly(tmp_path):
    _kubelet_secret(tmp_path, "..ts", {"KEY": "direct"})
    assert KubernetesSecretProvider(str(tmp_path)).get_secret("KEY") == "direct"


def test_kubernetes_hidden_directory_is_not_searched(tmp_path):
    _write(tmp_path / ".hidden" / "KEY")
    assert KubernetesSecretProvider(str(tmp_path)).get_secret("KEY") is None


def test_kubernetes_does_not_search_deeper_than_one_level(tmp_path):
    _write(tmp_path / "a" / "b" / "KEY")
    assert KubernetesSecretProvider(str(tmp_path)).get_secret("KEY") is None


def test_kubernetes_directory_named_like_key_is_not_a_candidate(tmp_path):
    (tmp_path / "a" / "KEY").mkdir(parents=True)
    assert KubernetesSecretProvider(str(tmp_path)).get_secret("KEY") is None


def test_kubernetes_empty_file_is_a_miss(tmp_path):
    _write(tmp_path / "a" / "KEY", "")
    assert KubernetesSecretProvider(str(tmp_path)).get_secret("KEY") is None


def test_kubernetes_missing_mount_path_names_path_and_secret_store(tmp_path):
    missing = tmp_path / "absent"
    with pytest.raises(SecretError) as info:
        KubernetesSecretProvider(str(missing)).get_secret("KEY")
    assert str(missing) in str(info.value) and "secretStore" in str(info.value)


def test_kubernetes_mount_path_that_is_a_file_raises(tmp_path):
    target = tmp_path / "file"
    target.write_text("x")
    with pytest.raises(SecretError) as info:
        KubernetesSecretProvider(str(target)).get_secret("KEY")
    assert str(target) in str(info.value) and "secretStore" in str(info.value)


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root ignores directory permissions")
def test_kubernetes_unreadable_directory_raises(tmp_path):
    mount = tmp_path / "mount"
    mount.mkdir()
    mount.chmod(0)
    try:
        with pytest.raises(SecretError, match="PermissionError"):
            KubernetesSecretProvider(str(mount)).get_secret("KEY")
    finally:
        mount.chmod(0o700)


def test_kubernetes_invalid_utf8_raises_without_chaining_or_leaking(tmp_path):
    path = tmp_path / "a" / "KEY"
    path.parent.mkdir()
    path.write_bytes(b"\xffSECRETBYTES\xfe")
    with pytest.raises(SecretError) as info:
        KubernetesSecretProvider(str(tmp_path)).get_secret("KEY")
    assert info.value.__cause__ is None and info.value.__suppress_context__
    assert "SECRETBYTES" not in str(info.value) and str(path) in str(info.value)


def test_kubernetes_file_vanishing_before_read_is_a_miss(tmp_path, monkeypatch):
    _write(tmp_path / "a" / "KEY")

    def _gone(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr("agentkernel.secret.providers.kubernetes.open", _gone, raising=False)
    assert KubernetesSecretProvider(str(tmp_path)).get_secret("KEY") is None


@pytest.mark.parametrize("key", ["..", ".env", "a/b", ""])
def test_kubernetes_rejects_keys_that_could_leave_mount_path(tmp_path, key):
    with pytest.raises(ValueError):
        KubernetesSecretProvider(str(tmp_path)).get_secret(key)


@pytest.mark.parametrize("mount_path", ["", "relative/path"])
def test_kubernetes_rejects_empty_or_relative_mount_path(mount_path):
    with pytest.raises(AKConfigError, match="secret.provider.kubernetes.mount_path"):
        KubernetesSecretProvider(mount_path)


def test_kubernetes_construction_touches_no_file(monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("filesystem touched at construction")

    monkeypatch.setattr(os, "scandir", _boom)
    KubernetesSecretProvider("/nonexistent/mount")


def test_kubernetes_rediscovers_a_key_moved_between_secrets(tmp_path):
    provider = KubernetesSecretProvider(str(tmp_path))
    _write(tmp_path / "a" / "KEY", "first")
    assert provider.get_secret("KEY") == "first"
    (tmp_path / "a" / "KEY").unlink()
    _write(tmp_path / "b" / "KEY", "second")
    assert provider.get_secret("KEY") == "second"
