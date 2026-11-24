import hashlib
import hmac
from pathlib import Path

import pytest
from agentkernel.core.config import AKConfig, _IdentityProviderConfig
from agentkernel.core.model import Principal
from agentkernel.core.util.factory import AKConfigError
from agentkernel.identity.errors import AuthenticationError
from agentkernel.identity.provider.factory import IdentityProviderFactory
from agentkernel.secret import EnvSecretProvider, SecretManager
from bench_identity import BenchIdentityProvider

SECRET = "s3cret"
CONFIG = Path(__file__).resolve().parent.parent / "config.yaml"


def sign(user: str, secret: str = SECRET) -> str:
    # Same signing line as the harness's TokenSigner; test_token_cross_check.py checks the two agree.
    return f"{user}.{hmac.new(secret.encode(), user.encode(), hashlib.sha256).hexdigest()}"


def provider(monkeypatch, value: str | None = SECRET, **extra) -> BenchIdentityProvider:
    key = extra.get("secret_key", "AK_BENCH_AUTH_SECRET")
    if value is None:
        monkeypatch.delenv(key, raising=False)
    else:
        monkeypatch.setenv(key, value)
    return BenchIdentityProvider(_IdentityProviderConfig(type="bench_identity.BenchIdentityProvider", **extra), SecretManager(EnvSecretProvider()))


@pytest.mark.asyncio
async def test_signed_token_authenticates(monkeypatch):
    principal = await provider(monkeypatch).authenticate(sign("bench-7"))
    assert principal == Principal(subject="bench-7", kind="user", provider="bench", namespace="bench")


@pytest.mark.asyncio
async def test_custom_secret_key(monkeypatch):
    principal = await provider(monkeypatch, secret_key="OTHER_SECRET").authenticate(sign("bench-1"))
    assert principal.subject == "bench-1"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "credential",
    [
        sign("bench-7").replace("bench-7", "bench-8", 1),  # changed user
        sign("bench-7")[:-1] + ("0" if sign("bench-7")[-1] != "0" else "1"),  # changed signature
        sign("bench-7", secret="other"),  # signed with another secret
        "bench-7",  # no "."
        "." + sign("bench-7").split(".")[1],  # empty user
        "bench-7.",  # empty signature
        "",
    ],
)
async def test_bad_tokens_refused(monkeypatch, credential):
    with pytest.raises(AuthenticationError):
        await provider(monkeypatch).authenticate(credential)


@pytest.mark.parametrize("value", [None, ""])
def test_missing_or_empty_secret_fails_at_build(monkeypatch, value):
    with pytest.raises(AKConfigError, match="AK_BENCH_AUTH_SECRET"):
        provider(monkeypatch, value)


@pytest.mark.asyncio
async def test_app_config_builds_provider_through_ak_factory(monkeypatch):
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", str(CONFIG))
    monkeypatch.setenv("AK_BENCH_AUTH_SECRET", SECRET)
    AKConfig._reset()
    SecretManager.reset()
    try:
        built = IdentityProviderFactory.create(AKConfig.get().identity)
        assert isinstance(built, BenchIdentityProvider)
        assert (await built.authenticate(sign("bench-2"))).subject == "bench-2"
    finally:
        AKConfig._reset()
        SecretManager.reset()
