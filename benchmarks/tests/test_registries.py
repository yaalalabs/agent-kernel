import pytest
from mocks.fetchers import MockResourceFetcher
from mocks.host import mock_host

from ak_bench.errors import BenchConfigError, HostRefused
from ak_bench.fetchers.core.stage_fetchers import StageFetchers
from ak_bench.hosts.host import Host
from ak_bench.hosts.registry import HostRegistry
from ak_bench.load.driver.factory import DriverFactory
from ak_bench.load.driver.ws_complete import WebSocketCompleteDriver


def test_unknown_host_lists_builtins(monkeypatch):
    monkeypatch.setitem(HostRegistry._BUILTINS, "mock", mock_host())
    with pytest.raises(BenchConfigError, match="unknown host 'ecs'; built-ins: mock"):
        HostRegistry.get("ecs")


def test_unknown_host_with_no_builtins():
    with pytest.raises(BenchConfigError, match=r"built-ins: \(none\)"):
        HostRegistry.get("ecs")


def test_get_returns_validated_host(monkeypatch):
    host = mock_host()
    monkeypatch.setitem(HostRegistry._BUILTINS, "mock", host)
    assert HostRegistry.get("mock") is host
    assert HostRegistry.names() == ["mock"]


def test_get_runs_validate(monkeypatch):
    bad = Host("mock", StageFetchers(cooldown_checks=[MockResourceFetcher("resource")]))
    monkeypatch.setitem(HostRegistry._BUILTINS, "bad", bad)
    with pytest.raises(HostRefused, match="host 'bad'.*'resource'"):
        HostRegistry.get("bad")


def test_driver_factory_returns_ws_complete_driver():
    assert DriverFactory.driver_class("async", "complete") is WebSocketCompleteDriver


def test_unknown_driver_lists_builtins():
    with pytest.raises(BenchConfigError, match=r"no client driver for sync \+ streaming; built-ins: async \+ complete"):
        DriverFactory.driver_class("sync", "streaming")
