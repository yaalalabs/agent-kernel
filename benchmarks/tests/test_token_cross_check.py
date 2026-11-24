import importlib.util
from pathlib import Path

import pytest
from agentkernel.core.config import _IdentityProviderConfig
from agentkernel.secret import EnvSecretProvider, SecretManager

from ak_bench.load.token import TokenSigner

APP_MODULE = Path(__file__).resolve().parent.parent / "app" / "bench_identity.py"


def bench_identity():
    spec = importlib.util.spec_from_file_location("bench_identity", APP_MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_signer_token_accepted_by_app_provider(monkeypatch):
    monkeypatch.setenv("AK_BENCH_AUTH_SECRET", "s3cret")
    provider = bench_identity().BenchIdentityProvider(
        _IdentityProviderConfig(type="bench_identity.BenchIdentityProvider"), SecretManager(EnvSecretProvider())
    )
    signer = TokenSigner("s3cret")
    principal = await provider.authenticate(signer.token(TokenSigner.user(7)))
    assert principal.subject == "bench-7"
    assert signer.token("bench-7") == signer.token("bench-7")
