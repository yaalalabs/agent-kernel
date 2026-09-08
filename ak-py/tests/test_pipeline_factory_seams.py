"""The #503 factory seams: ``QueueTransportFactory`` and ``ResponseStoreFactory`` accept an
explicit config block (the sandbox broker's own queue/store blocks) while their no-argument
paths keep reading ``execution.*`` exactly as before."""

import pytest
from pydantic import ValidationError

from agentkernel.core.config import (
    _InMemoryQueueConfig,
    _QueuesConfig,
    _ResponseStoreConfig,
    _ResponseStoreRedisConfig,
    _ResponseStoreValkeyConfig,
)
from agentkernel.core.util.factory import AKConfigError
from agentkernel.pipeline.envelope import QueueName
from agentkernel.pipeline.response_store.factory import ResponseStoreFactory
from agentkernel.pipeline.response_store.in_memory import InMemoryResponseStore
from agentkernel.pipeline.transport.base import QueueTransportFactory
from agentkernel.pipeline.transport.in_memory import InMemoryTransport


@pytest.fixture(autouse=True)
def _no_global_config_reads(monkeypatch):
    """Explicit-block paths must never consult AKConfig; a read fails the test loudly."""

    def _fail(cls):
        raise AssertionError("the explicit-config seam must not read AKConfig")

    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(_fail))
    InMemoryTransport.reset()
    yield
    InMemoryTransport.reset()


def _sqs_block(input_url=None, output_url=None):
    # url is typed str with a None *default*: pass the key only when set (the config quirk).
    data = {"type": "sqs", "input": {}, "output": {}}
    if input_url:
        data["input"]["url"] = input_url
    if output_url:
        data["output"]["url"] = output_url
    return _QueuesConfig.model_validate(data)


class TestTransportFactorySeam:
    def test_resolve_type_from_explicit_block(self):
        assert QueueTransportFactory.resolve_type(_QueuesConfig(type="kafka")) == "kafka"

    def test_queues_block_requires_a_declared_type(self):
        # The transport is declared, never inferred from queue coordinates: a queues block
        # without `type` is invalid (the same rule the execution.queues block enforces).
        with pytest.raises(ValidationError):
            _QueuesConfig()

    def test_create_in_memory_from_explicit_block(self):
        block = _QueuesConfig(type="in_memory", in_memory=_InMemoryQueueConfig(ack_wait=7.0, dedup_window=9.0))
        transport = QueueTransportFactory.create(queues_config=block)
        assert isinstance(transport, InMemoryTransport)

    def test_create_sqs_from_explicit_block(self):
        transport = QueueTransportFactory.create(queues_config=_sqs_block(input_url="https://sqs.example/in", output_url="https://sqs.example/out"))
        assert type(transport).__name__ == "SQSTransport"

    def test_create_sqs_requires_both_urls(self):
        with pytest.raises(AKConfigError, match="requires both execution.queues.input.url and execution.queues.output.url"):
            QueueTransportFactory.create(queues_config=_sqs_block(input_url="https://sqs.example/in"))

    def test_error_messages_name_the_callers_block(self):
        # config_path relabels the factory's errors so a sandbox.broker.queue misconfiguration
        # is not reported as an execution.queues one.
        with pytest.raises(AKConfigError, match=r"sandbox\.broker\.queue\.input\.url"):
            QueueTransportFactory.create(queues_config=_sqs_block(input_url="https://sqs.example/in"), config_path="sandbox.broker.queue")

    def test_create_consumer_threads_the_block_through(self):
        block = _QueuesConfig(type="in_memory")
        consumer = QueueTransportFactory.create_consumer(QueueName.INPUT, queues_config=block)
        try:
            assert consumer.fetch(1, 0.01) == []
        finally:
            consumer.close()


class TestResponseStoreFactorySeam:
    def test_explicit_in_memory_pairing_rule(self):
        assert isinstance(
            ResponseStoreFactory.create(response_store_config=_ResponseStoreConfig(), transport_type="in_memory"), InMemoryResponseStore
        )

    def test_unconfigured_store_on_broker_transport_raises(self):
        with pytest.raises(AKConfigError, match="execution.response_store is required on broker transports"):
            ResponseStoreFactory.create(response_store_config=_ResponseStoreConfig(), transport_type="kafka")

    def test_error_messages_name_the_callers_block(self):
        # config_path relabels the factory's errors so a sandbox.broker.response_store
        # misconfiguration is not reported as an execution.response_store one.
        with pytest.raises(AKConfigError, match=r"sandbox\.broker\.response_store is required"):
            ResponseStoreFactory.create(
                response_store_config=_ResponseStoreConfig(), transport_type="kafka", config_path="sandbox.broker.response_store"
            )

    def test_explicit_in_memory_type_skips_the_transport_check(self):
        # Explicit in_memory never consults the transport (the pre-seam short-circuit).
        store = ResponseStoreFactory.create(response_store_config=_ResponseStoreConfig(type="in_memory"), transport_type="kafka")
        assert isinstance(store, InMemoryResponseStore)

    def test_redis_ttl_override_wins(self):
        block = _ResponseStoreConfig(type="redis", redis=_ResponseStoreRedisConfig(url="redis://localhost:6379", ttl=100))
        store = ResponseStoreFactory.create(response_store_config=block, transport_type="kafka", ttl=86400)
        assert store._driver.ttl == 86400

    def test_redis_ttl_falls_back_to_the_block(self):
        block = _ResponseStoreConfig(type="redis", redis=_ResponseStoreRedisConfig(url="redis://localhost:6379", ttl=100))
        store = ResponseStoreFactory.create(response_store_config=block, transport_type="kafka")
        assert store._driver.ttl == 100

    def test_valkey_ttl_override_wins(self):
        pytest.importorskip("valkey")
        block = _ResponseStoreConfig(type="valkey", valkey=_ResponseStoreValkeyConfig(url="valkey://localhost:6379", ttl=100))
        store = ResponseStoreFactory.create(response_store_config=block, transport_type="kafka", ttl=86400)
        assert store._driver.ttl == 86400
