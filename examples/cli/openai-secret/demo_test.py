import os

import pytest
import pytest_asyncio
from agentkernel.core import Config
from agentkernel.secret import SecretManager, SecretNotFoundError
from agentkernel.test import Test

pytestmark = pytest.mark.asyncio(loop_scope="session")  # uses a single session for all tests

# The stub weather service only needs the secret to be present; its value is never sent anywhere.
WEATHER_API_KEY = "demo-weather-key"


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def test_client():
    # The CLI subprocess inherits this environment, which is the `env` provider's store.
    os.environ["WEATHER_API_KEY"] = WEATHER_API_KEY
    test = Test("demo.py")
    await test.start()
    try:
        yield test
    finally:
        await test.stop()
        os.environ.pop("WEATHER_API_KEY", None)


@pytest.fixture
def secret_manager():
    # config.yaml (read from this directory) selects the env provider
    SecretManager.reset()
    yield SecretManager.current()
    SecretManager.reset()


@pytest.mark.order(1)
def test_config_selects_env_provider():
    assert Config.get().secret.provider.type == "env"


@pytest.mark.order(2)
def test_resolves_from_environment(secret_manager, monkeypatch):
    monkeypatch.setenv("DEMO_SECRET", "from-env")
    assert secret_manager.get("DEMO_SECRET") == "from-env"


@pytest.mark.order(3)
def test_missing_secret(secret_manager, monkeypatch):
    monkeypatch.delenv("DEMO_SECRET", raising=False)
    assert secret_manager.get("DEMO_SECRET", default=None) is None
    with pytest.raises(SecretNotFoundError):
        secret_manager.get("DEMO_SECRET")


@pytest.mark.order(4)
async def test_agent_uses_env_secret(test_client):
    # Proves both secrets resolved inside the CLI: OPENAI_API_KEY (the model answered at all) and
    # WEATHER_API_KEY (the tool returned the forecast rather than "not configured").
    await test_client.send("What is the weather in Tokyo?")
    await test_client.expect(["The weather in Tokyo is sunny."])
