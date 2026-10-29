import sys

import pytest

from agentkernel.core.config import AKConfig, _SecretConfig
from agentkernel.core.util.factory import AKConfigError
from agentkernel.secret import EnvSecretProvider, KubernetesSecretProvider, SecretManager, SecretProvider
from agentkernel.secret.factory import SecretProviderFactory
from agentkernel.secret.providers.aws_ssm import AWSSMSecretProvider


class _RecordingSecretProvider(SecretProvider):
    """Records the config block its create received."""

    def __init__(self, config=None) -> None:
        self.config = config

    @classmethod
    def create(cls, config):
        return cls(config)

    def get_secret(self, key):
        return None


class _NotAProvider:
    pass


# Built from __name__ so the path resolves however pytest imported this module.
_RECORDING = f"{__name__}._RecordingSecretProvider"
_NOT_A_PROVIDER = f"{__name__}._NotAProvider"


@pytest.fixture(autouse=True)
def _reset_manager():
    SecretManager.reset()
    yield
    SecretManager.reset()


def _config(**fields) -> _SecretConfig:
    return _SecretConfig.model_validate(fields)


def test_env_builds_env_provider():
    assert isinstance(SecretProviderFactory.get(_config(provider={"type": "env"})), EnvSecretProvider)


def test_short_name_is_case_insensitive():
    assert isinstance(SecretProviderFactory.get(_config(provider={"type": "ENV"})), EnvSecretProvider)


def test_default_config_builds_env_provider():
    assert isinstance(SecretProviderFactory.get(_config()), EnvSecretProvider)


def test_dotted_path_builds_subclass():
    provider = SecretProviderFactory.get(_config(provider={"type": _RECORDING}))
    assert isinstance(provider, _RecordingSecretProvider)


@pytest.mark.parametrize("name", ["unknown", "noop", "in_memory", "awssm"])
def test_unknown_short_name_rejected(name):
    with pytest.raises(AKConfigError) as exc_info:
        SecretProviderFactory.get(_config(provider={"type": name}))
    assert "env" in str(exc_info.value)
    assert "aws_ssm" in str(exc_info.value)
    assert "kubernetes" in str(exc_info.value)


def test_dotted_path_to_non_subclass_rejected():
    with pytest.raises(AKConfigError):
        SecretProviderFactory.get(_config(provider={"type": _NOT_A_PROVIDER}))


def test_unimportable_dotted_path_rejected():
    with pytest.raises(AKConfigError):
        SecretProviderFactory.get(_config(provider={"type": "no_such_package.module.Provider"}))


def test_kubernetes_builds_kubernetes_provider():
    default = SecretProviderFactory.get(_config(provider={"type": "kubernetes"}))
    assert isinstance(default, KubernetesSecretProvider)
    assert default._mount_path == "/var/run/secrets/agentkernel"

    override = SecretProviderFactory.get(_config(provider={"type": "kubernetes", "kubernetes": {"mount_path": "/run/secrets"}}))
    assert override._mount_path == "/run/secrets"


def test_kubernetes_empty_mount_path_raises_config_error():
    with pytest.raises(AKConfigError, match="secret.provider.kubernetes.mount_path"):
        SecretProviderFactory.get(_config(provider={"type": "kubernetes", "kubernetes": {"mount_path": ""}}))


def test_aws_ssm_builds_aws_ssm_provider():
    provider = SecretProviderFactory.get(_config(prefix="myproduct-dev", provider={"type": "aws_ssm"}))
    assert isinstance(provider, AWSSMSecretProvider)
    assert provider._compose_path("OPENAI_API_KEY") == "/ak/myproduct-dev/openai_api_key"


def test_aws_ssm_without_prefix_raises_config_error():
    with pytest.raises(AKConfigError) as exc_info:
        SecretProviderFactory.get(_config(provider={"type": "aws_ssm"}))
    assert "secret.prefix" in str(exc_info.value)


def test_aws_ssm_missing_extra_raises_before_prefix_check(monkeypatch):
    # Empty prefix too: a missing dependency must not be reported as a misconfiguration.
    monkeypatch.delitem(sys.modules, "agentkernel.secret.providers.aws_ssm", raising=False)
    monkeypatch.setitem(sys.modules, "boto3", None)  # simulate boto3 not being installed
    with pytest.raises(ImportError) as exc_info:
        SecretProviderFactory.get(_config(prefix="", provider={"type": "aws_ssm"}))
    assert "agentkernel[aws]" in str(exc_info.value)
    assert "secret.provider.type: aws_ssm" in str(exc_info.value)


@pytest.mark.parametrize("provider_type", ["env", "kubernetes", _RECORDING])
def test_empty_prefix_is_fine_outside_aws_ssm(provider_type):
    assert SecretProviderFactory.get(_config(prefix="", provider={"type": provider_type})) is not None


def test_get_never_reads_akconfig(monkeypatch):
    def _boom(cls):
        raise AssertionError("SecretProviderFactory.get must not call AKConfig.get()")

    monkeypatch.setattr(AKConfig, "get", classmethod(_boom))
    SecretProviderFactory.get(_config(provider={"type": "env"}))
    SecretProviderFactory.get(_config(provider={"type": "kubernetes"}))
    SecretProviderFactory.get(_config(provider={"type": _RECORDING}))


def test_dotted_path_provider_receives_whole_block():
    config = _config(prefix="myproduct-dev", provider={"type": _RECORDING}, cache_ttl=5)
    provider = SecretProviderFactory.get(config)
    assert provider.config is config
    assert provider.config.prefix == "myproduct-dev"
