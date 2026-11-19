import pytest

from agentkernel.core.config import AKConfig, _CostConfig, _CostGatewayConfig
from agentkernel.core.util.factory import AKConfigError


@pytest.fixture(autouse=True)
def reset_config_singleton():
    AKConfig._reset()
    yield
    AKConfig._reset()


def _load_yaml(tmp_path, monkeypatch, text: str) -> AKConfig:
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(text)
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", str(cfg_path))
    return AKConfig()


def test_cost_absent_by_default(monkeypatch):
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
    assert AKConfig.get().cost is None


def test_cost_gateway_yaml_defaults(tmp_path, monkeypatch):
    cfg = _load_yaml(tmp_path, monkeypatch, "cost:\n  gateway:\n    type: litellm\n    base_url: http://litellm:4000\n")
    gateway = cfg.cost.gateway
    assert gateway.type == "litellm"
    assert gateway.base_url == "http://litellm:4000"
    assert gateway.api_key == ""
    assert gateway.api_key_key == "COST_GATEWAY_API_KEY"
    assert gateway.admin_key_key == "COST_GATEWAY_ADMIN_KEY"
    assert gateway.litellm.api == "end_user"
    assert gateway.database is None


def test_cost_gateway_from_env(monkeypatch):
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
    monkeypatch.setenv("AK_COST__GATEWAY__TYPE", "litellm")
    monkeypatch.setenv("AK_COST__GATEWAY__BASE_URL", "http://litellm:4000")
    monkeypatch.setenv("AK_COST__GATEWAY__API_KEY_KEY", "MY_KEY")
    monkeypatch.setenv("AK_COST__GATEWAY__LITELLM__API", "customer_management")
    monkeypatch.setenv("AK_COST__GATEWAY__LITELLM__CUSTOMER_ORG_ALIAS", "acme")

    gateway = AKConfig.get().cost.gateway
    assert gateway.type == "litellm"
    assert gateway.base_url == "http://litellm:4000"
    assert gateway.api_key_key == "MY_KEY"
    assert gateway.litellm.api == "customer_management"
    assert gateway.litellm.customer_org_alias == "acme"


def test_partial_cost_env_fails_loudly(monkeypatch):
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
    monkeypatch.setenv("AK_COST__GATEWAY__API_KEY_KEY", "MY_KEY")
    with pytest.raises(AKConfigError, match=r"cost\.gateway\.type and cost\.gateway\.base_url"):
        AKConfig.get()


@pytest.mark.parametrize(
    "data, missing",
    [
        ({}, "cost.gateway.type and cost.gateway.base_url"),
        ({"gateway": None}, "cost.gateway.type and cost.gateway.base_url"),
        ({"gateway": {"type": "litellm"}}, "cost.gateway.base_url"),
        ({"gateway": {"type": "  ", "base_url": "http://x"}}, "cost.gateway.type"),
    ],
)
def test_gateway_type_and_base_url_required(data, missing):
    with pytest.raises(AKConfigError, match=missing):
        _CostConfig.model_validate(data)


def test_agentgateway_requires_database():
    with pytest.raises(AKConfigError, match="cost.gateway.database"):
        _CostGatewayConfig(type="agentgateway", base_url="http://agw:3000")

    gateway = _CostGatewayConfig(type="agentgateway", base_url="http://agw:3000", database={"url": "postgres://db/agw"})
    assert gateway.database.url == "postgres://db/agw"
    assert gateway.database.url_key == "AGW_DB_URL"


def test_customer_management_requires_org_alias():
    with pytest.raises(AKConfigError, match="customer_org_alias"):
        _CostGatewayConfig(type="litellm", base_url="http://x", litellm={"api": "customer_management", "customer_org_alias": " "})

    gateway = _CostGatewayConfig(type="litellm", base_url="http://x", litellm={"api": "customer_management", "customer_org_alias": "acme"})
    assert gateway.litellm.customer_org_alias == "acme"


def test_gateway_keeps_extra_settings_for_dotted_path_gateways():
    gateway = _CostGatewayConfig(type="my.module.MyGateway", base_url="http://x", region="eu")
    assert gateway.model_extra == {"region": "eu"}


def test_cost_config_accepts_built_gateway():
    gateway = _CostGatewayConfig(type="litellm", base_url="http://x")
    assert _CostConfig(gateway=gateway).gateway is gateway
