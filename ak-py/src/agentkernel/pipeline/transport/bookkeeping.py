"""Delivery bookkeeping for transports that do not track it themselves (spec #495 §6).

Kafka's classic consumer model has no ``ApproximateReceiveCount`` and no publish-time
deduplication, so the transport rebuilds both: a per-record attempt counter and a dedup claim.
Both need to survive a pod restart for the guarantees to hold (an in-process counter resets, so
a message that *crashes* the worker would retry forever), which is why the backing store follows
the session storage configuration (design decision Q5): a deployment that already runs
Redis/Valkey for sessions gets durable bookkeeping for free.
"""

import logging
import threading
import time
from abc import ABC, abstractmethod
from typing import Dict, Optional

from ...core.config import AKConfig
from ...core.util.factory import require_extra

_log = logging.getLogger("ak.pipeline.transport.bookkeeping")

# Attempt counters outlive a single delivery but must not leak: an hour covers any realistic
# retry cycle of an agent turn. Dedup mirrors the SQS content-dedup window.
DEFAULT_ATTEMPTS_TTL_SECONDS = 3600
DEFAULT_DEDUP_TTL_SECONDS = 300

ATTEMPTS_KEY_PREFIX = "ak:qattempts:"
DEDUP_KEY_PREFIX = "ak:qdedup:"


class BookkeepingStore(ABC):
    """Per-record attempt counts and dedup claims for a transport."""

    @abstractmethod
    def incr_attempts(self, key: str) -> int:
        """Count this delivery of ``key`` and return the running total (1 on first delivery)."""
        raise NotImplementedError

    @abstractmethod
    def clear_attempts(self, key: str) -> None:
        """Forget ``key``'s attempt count (the record reached a terminal state)."""
        raise NotImplementedError

    @abstractmethod
    def claim_dedup(self, dedup_id: str, owner: str) -> bool:
        """Claim ``dedup_id`` for ``owner``, returning whether this owner holds the claim.

        True means "process this record": either the claim was free, or ``owner`` already holds
        it (a redelivery of the same record, which must still be retried). False means a
        *different* record already claimed the id, so this one is a duplicate and should be
        dropped. Keying the claim by owner is what keeps deduplication from swallowing retries.
        """
        raise NotImplementedError


class InMemoryBookkeepingStore(BookkeepingStore):
    """Process-local bookkeeping: correct while the process lives, lost on restart."""

    def __init__(self, dedup_ttl: float = DEFAULT_DEDUP_TTL_SECONDS):
        self._dedup_ttl = dedup_ttl
        self._lock = threading.Lock()
        self._attempts: Dict[str, int] = {}
        self._dedup: Dict[str, tuple[str, float]] = {}  # dedup_id -> (owner, expiry)

    def incr_attempts(self, key: str) -> int:
        with self._lock:
            self._attempts[key] = self._attempts.get(key, 0) + 1
            return self._attempts[key]

    def clear_attempts(self, key: str) -> None:
        with self._lock:
            self._attempts.pop(key, None)

    def claim_dedup(self, dedup_id: str, owner: str) -> bool:
        now = time.monotonic()
        with self._lock:
            for expired in [d for d, (_, expiry) in self._dedup.items() if expiry <= now]:
                del self._dedup[expired]
            existing = self._dedup.get(dedup_id)
            if existing is None:
                self._dedup[dedup_id] = (owner, now + self._dedup_ttl)
                return True
            return existing[0] == owner


class RedisLikeBookkeepingStore(BookkeepingStore):
    """Bookkeeping over a shared Redis/Valkey driver: survives pod restarts."""

    def __init__(self, attempts_driver, dedup_driver):
        """
        :param attempts_driver: Driver for attempt counters (its TTL bounds a counter's life).
        :param dedup_driver: Driver for dedup claims (its TTL is the dedup window).
        """
        self._attempts = attempts_driver
        self._dedup = dedup_driver

    def incr_attempts(self, key: str) -> int:
        return self._attempts.incr(self._attempts.key(key))

    def clear_attempts(self, key: str) -> None:
        self._attempts.delete(self._attempts.key(key))

    def claim_dedup(self, dedup_id: str, owner: str) -> bool:
        full_key = self._dedup.key(dedup_id)
        if self._dedup.set(full_key, owner, nx=True):
            return True
        existing = self._dedup.get(full_key)
        if isinstance(existing, (bytes, bytearray)):
            existing = existing.decode()
        return existing == owner


class BookkeepingStoreFactory:
    """Builds the :class:`BookkeepingStore` from the session storage configuration (Q5).

    Redis/Valkey session backends give durable bookkeeping using the same connection settings;
    every other session type (including the default ``in_memory``) falls back to process-local
    bookkeeping with a one-time warning, since the alternative would be forcing an unrelated
    infrastructure dependency on a deployment that has not asked for one.
    """

    _fallback_warned = False

    @classmethod
    def create(cls, feature: str = "execution.queues.type: kafka") -> BookkeepingStore:
        """Create the bookkeeping store for the current configuration.

        :param feature: Config path quoted in the missing-extra error, for the operator.
        """
        session_config = AKConfig.get().session
        session_type = session_config.type if session_config is not None else None

        if session_type == "redis" and getattr(session_config, "redis", None) is not None:
            with require_extra("redis", feature):
                from ...core.util.driver.redis import RedisDriver

            return cls._redis_like(RedisDriver, session_config.redis.url)

        if session_type == "valkey" and getattr(session_config, "valkey", None) is not None:
            with require_extra("valkey", feature):
                from ...core.util.driver.valkey import ValkeyDriver

            return cls._redis_like(ValkeyDriver, session_config.valkey.url)

        if not cls._fallback_warned:
            cls._fallback_warned = True
            _log.warning(
                f"Queue retry bookkeeping is process-local: session.type '{session_type}' has no shared key store. "
                "Delivery counts and deduplication reset when a worker restarts, so a message that crashes its worker "
                "can exceed max_receive_count without being permanently failed. Configure session.type redis or valkey "
                "for bookkeeping that survives restarts."
            )
        return InMemoryBookkeepingStore()

    @staticmethod
    def _redis_like(driver_class, url: str) -> RedisLikeBookkeepingStore:
        """Build two drivers off one connection URL: separate prefixes and TTLs per concern."""
        return RedisLikeBookkeepingStore(
            attempts_driver=driver_class(url=url, prefix=ATTEMPTS_KEY_PREFIX, ttl=DEFAULT_ATTEMPTS_TTL_SECONDS, decode_responses=True),
            dedup_driver=driver_class(url=url, prefix=DEDUP_KEY_PREFIX, ttl=DEFAULT_DEDUP_TTL_SECONDS, decode_responses=True),
        )


def reset_fallback_warning(state: Optional[bool] = False) -> None:
    """Test helper: reset the one-time fallback warning latch."""
    BookkeepingStoreFactory._fallback_warned = bool(state)
