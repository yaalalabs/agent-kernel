from decimal import Decimal

import pytest
from pydantic import ValidationError

from agentkernel.core.config import (
    AKConfig,
    _CostBudgetLimit,
    _CostBudgetPeriod,
    _CostBudgetsConfig,
    _CostConfig,
    _CostGatewayConfig,
    _CostLedgerConfig,
    _CostStaticPricingConfig,
)
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


_GATEWAY = {"type": "litellm", "base_url": "http://x"}


def test_cost_sections_default():
    cost = _CostConfig(gateway=_GATEWAY)
    assert cost.attribution.type == "default"
    assert cost.view.type == "default"
    assert cost.pricing.type == "passthrough"
    assert cost.pricing.static is None
    assert cost.budgets is None


def test_full_cost_block_from_yaml(tmp_path, monkeypatch):
    cfg = _load_yaml(
        tmp_path,
        monkeypatch,
        """
cost:
  gateway: {type: litellm, base_url: "http://litellm:4000"}
  pricing:
    type: static
    static:
      markup: 1.2
      models:
        openai/gpt-4o-mini: {input: 0.15, output: 0.60, cached_input: 0.075}
  budgets:
    default: {amount: 10}
    users:
      alice: {amount: 2.5, currency: EUR, period: daily, action: warn, message: slow down}
    ledger:
      type: redis
      redis: {url: "redis://cache:6379"}
""",
    )
    cost = cfg.cost
    rate = cost.pricing.static.models["openai/gpt-4o-mini"]
    assert cost.pricing.static.markup == Decimal("1.2")
    assert (rate.input, rate.output, rate.cached_input) == (Decimal("0.15"), Decimal("0.60"), Decimal("0.075"))

    budgets = cost.budgets
    assert budgets.on_error == "block"
    assert budgets.policy.type == "static"
    assert budgets.default == _CostBudgetLimit(amount=Decimal(10))
    assert budgets.default.period is _CostBudgetPeriod.MONTHLY
    assert budgets.default.currency == "USD"
    alice = budgets.users["alice"]
    assert (alice.amount, alice.currency, alice.period, alice.action, alice.message) == (
        Decimal("2.5"),
        "EUR",
        _CostBudgetPeriod.DAILY,
        "warn",
        "slow down",
    )
    assert budgets.ledger.type == "redis"
    assert budgets.ledger.redis.url == "redis://cache:6379"
    assert budgets.ledger.redis.prefix == "ak:cost:ledger:"
    assert budgets.ledger.redis.ttl == 0


def test_ledger_store_defaults():
    ledger = _CostLedgerConfig(
        dynamodb={},
        firestore={},
        cosmosdb={"connection_string": "cs"},
        valkey={},
    )
    assert ledger.type == "in_memory"
    assert (ledger.dynamodb.table_name, ledger.dynamodb.ttl) == ("ak-cost-ledger", 0)
    assert (ledger.firestore.collection_name, ledger.firestore.ttl) == ("ak_cost_ledger", 0)
    assert (ledger.cosmosdb.table_name, ledger.cosmosdb.ttl) == ("akcostledger", 0)
    assert (ledger.valkey.prefix, ledger.valkey.ttl) == ("ak:cost:ledger:", 0)


@pytest.mark.parametrize("key, reason", [("", "empty"), ("  ", "empty"), ("ak-system", "reserved"), (" ak-system ", "reserved")])
def test_budget_users_refuses_empty_and_reserved_keys(key, reason):
    with pytest.raises(AKConfigError, match=f"{key!r} is {reason}"):
        _CostBudgetsConfig(users={key: {"amount": 1}})


@pytest.mark.parametrize(
    "limit",
    [{"amount": 0}, {"amount": -1}, {"amount": 1, "action": "other"}, {"amount": 1, "period": "yearly"}],
)
def test_budget_limit_constraints(limit):
    with pytest.raises(ValidationError):
        _CostBudgetLimit(**limit)


@pytest.mark.parametrize(
    "static",
    [
        {"markup": 0},
        {"models": {"m": {"input": -1, "output": 0}}},
        {"models": {"m": {"input": 0, "output": 0, "typo": 1}}},
    ],
)
def test_static_pricing_constraints(static):
    with pytest.raises(ValidationError):
        _CostStaticPricingConfig(**static)


def test_pluggable_sections_keep_extra_settings():
    cost = _CostConfig(
        gateway=_GATEWAY,
        attribution={"type": "my.Attributor", "header": "x-tenant"},
        view={"type": "my.View", "limit": 5},
        pricing={"type": "my.Pricing", "table": "rates"},
        budgets={"policy": {"type": "my.Policy", "tier": "gold"}},
    )
    assert cost.attribution.model_extra == {"header": "x-tenant"}
    assert cost.view.model_extra == {"limit": 5}
    assert cost.pricing.model_extra == {"table": "rates"}
    assert cost.budgets.policy.model_extra == {"tier": "gold"}


def test_budgets_from_env(monkeypatch):
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
    monkeypatch.setenv("AK_COST__GATEWAY__TYPE", "litellm")
    monkeypatch.setenv("AK_COST__GATEWAY__BASE_URL", "http://litellm:4000")
    monkeypatch.setenv("AK_COST__BUDGETS__ON_ERROR", "allow")
    monkeypatch.setenv("AK_COST__BUDGETS__DEFAULT__AMOUNT", "5")

    budgets = AKConfig.get().cost.budgets
    assert budgets.on_error == "allow"
    assert budgets.default.amount == Decimal(5)
