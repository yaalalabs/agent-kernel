"""Delivery bookkeeping for transports that do not track it themselves (spec #495 §6).

Kafka's classic consumer model has no ``ApproximateReceiveCount`` and no publish-time
deduplication, so the transport rebuilds both: a per-record attempt counter and a dedup claim.
Pub/Sub (#886) also needs a memory of acknowledged records, because it redelivers acked messages
when an earlier message with the same ordering key is redelivered.

All of it needs to survive a pod restart for the guarantees to hold (an in-process counter
resets, so a message that *crashes* the worker would retry forever). The backing store therefore
follows Redis/Valkey configuration the deployment already has: the session store first (design
decision Q5), then the response store (#886), so a deployment that runs either on Redis/Valkey
gets durable bookkeeping for free.
"""

import logging
import threading
import time
from abc import ABC, abstractmethod

from ...core.config import AKConfig
from ...core.util.factory import require_extra

_log = logging.getLogger("ak.pipeline.transport.bookkeeping")

# Attempt counters outlive a single delivery but must not leak: an hour covers any realistic
# retry cycle of an agent turn. Dedup mirrors the SQS content-dedup window.
DEFAULT_ATTEMPTS_TTL_SECONDS = 3600
DEFAULT_DEDUP_TTL_SECONDS = 300

ATTEMPTS_KEY_PREFIX = "ak:qattempts:"
DEDUP_KEY_PREFIX = "ak:qdedup:"
ACKED_KEY_PREFIX = "ak:qacked:"


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

    @abstractmethod
    def mark_acked(self, key: str) -> None:
        """Remember that ``key``'s record was acknowledged, for the dedup window."""
        raise NotImplementedError

    @abstractmethod
    def was_acked(self, key: str) -> bool:
        """Whether ``key``'s record was acknowledged within the dedup window.

        A transport that redelivers acknowledged records (Pub/Sub's ordering-key cascade, or an
        acknowledgement lost in transit) checks this before running a record again.
        """
        raise NotImplementedError


class InMemoryBookkeepingStore(BookkeepingStore):
    """Process-local bookkeeping: correct while the process lives, lost on restart."""

    def __init__(self, dedup_ttl: float = DEFAULT_DEDUP_TTL_SECONDS):
        self._dedup_ttl = dedup_ttl
        self._lock = threading.Lock()
        self._attempts: dict[str, int] = {}
        self._dedup: dict[str, tuple[str, float]] = {}  # dedup_id -> (owner, expiry)
        self._acked: dict[str, float] = {}  # key -> expiry

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

    def mark_acked(self, key: str) -> None:
        with self._lock:
            self._acked[key] = time.monotonic() + self._dedup_ttl

    def was_acked(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            for expired in [k for k, expiry in self._acked.items() if expiry <= now]:
                del self._acked[expired]
            return key in self._acked


class RedisLikeBookkeepingStore(BookkeepingStore):
    """Bookkeeping over a shared Redis/Valkey driver: survives pod restarts."""

    # Key prefix used for acked-record memory when no dedicated driver is given.
    _SHARED_ACKED_PREFIX = "acked:"

    def __init__(self, attempts_driver, dedup_driver, acked_driver=None):
        """
        :param attempts_driver: Driver for attempt counters (its TTL bounds a counter's life).
        :param dedup_driver: Driver for dedup claims (its TTL is the dedup window).
        :param acked_driver: Driver for acknowledged-record memory (its TTL is how long an ack is
            remembered). When omitted, the dedup driver holds it under an ``acked:`` key prefix,
            which shares the dedup window.
        """
        self._attempts = attempts_driver
        self._dedup = dedup_driver
        self._acked = acked_driver

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
        if existing is None:
            # The claim expired between the SET and the GET, i.e. we raced the tail of the dedup
            # window. Reading that as "someone else owns it" would drop a legitimate record, so
            # treat the id as free and try to claim it once more.
            return bool(self._dedup.set(full_key, owner, nx=True))
        return existing == owner

    def mark_acked(self, key: str) -> None:
        driver, full_key = self._acked_key(key)
        driver.set(full_key, "1")

    def was_acked(self, key: str) -> bool:
        driver, full_key = self._acked_key(key)
        return driver.get(full_key) is not None

    def _acked_key(self, key: str) -> tuple:
        """The driver holding acked-record memory, and ``key``'s full key on it."""
        if self._acked is not None:
            return self._acked, self._acked.key(key)
        return self._dedup, self._dedup.key(f"{self._SHARED_ACKED_PREFIX}{key}")


class BookkeepingStoreFactory:
    """Builds the :class:`BookkeepingStore` from Redis/Valkey configuration the deployment already has.

    Resolution order:

    1. ``session.type`` ``redis`` or ``valkey`` with its block set (design decision Q5);
    2. ``execution.response_store.type`` ``redis`` or ``valkey`` with its block set (#886): queue
       mode on GCP always has a Redis response store while sessions usually live on Firestore;
    3. process-local bookkeeping with a one-time warning, since the alternative would be forcing
       an unrelated infrastructure dependency on a deployment that has not asked for one.

    Durable stores use the matching block's connection URL with the bookkeeping key prefixes, so
    they never collide with the session or response keys in the same database.
    """

    _fallback_warned = False

    @classmethod
    def create(cls, feature: str = "execution.queues.type: kafka") -> BookkeepingStore:
        """Create the bookkeeping store for the current configuration.

        :param feature: Config path quoted in the missing-extra error, for the operator.
        """
        config = AKConfig.get()
        session_config = config.session
        execution_config = getattr(config, "execution", None)
        response_store_config = getattr(execution_config, "response_store", None) if execution_config is not None else None

        for block in (session_config, response_store_config):
            store = cls._durable_store(block, feature)
            if store is not None:
                return store

        if not cls._fallback_warned:
            cls._fallback_warned = True
            session_type = session_config.type if session_config is not None else None
            response_store_type = response_store_config.type if response_store_config is not None else None
            _log.warning(
                f"Queue retry bookkeeping is process-local: neither session.type '{session_type}' nor "
                f"execution.response_store.type '{response_store_type}' is a shared key store. Delivery counts and "
                "deduplication reset when a worker restarts, so a message that crashes its worker can exceed "
                "max_receive_count without being permanently failed. Configure session.type or "
                "execution.response_store.type redis or valkey for bookkeeping that survives restarts."
            )
        return InMemoryBookkeepingStore()

    @classmethod
    def _durable_store(cls, block, feature: str) -> RedisLikeBookkeepingStore | None:
        """A durable store over ``block``'s Redis/Valkey connection, or None if it has none.

        :param block: A session or response-store config block (``type`` plus per-backend
            sub-blocks), or None.
        :param feature: Config path quoted in the missing-extra error.
        """
        backend = block.type if block is not None else None

        if backend == "redis" and getattr(block, "redis", None) is not None:
            with require_extra("redis", feature):
                from ...core.util.driver.redis import RedisDriver

            return cls._redis_like(RedisDriver, block.redis.url)

        if backend == "valkey" and getattr(block, "valkey", None) is not None:
            with require_extra("valkey", feature):
                from ...core.util.driver.valkey import ValkeyDriver

            return cls._redis_like(ValkeyDriver, block.valkey.url)

        return None

    @staticmethod
    def _redis_like(driver_class, url: str) -> RedisLikeBookkeepingStore:
        """Build one driver per concern off one connection URL: separate prefixes and TTLs."""
        return RedisLikeBookkeepingStore(
            attempts_driver=driver_class(url=url, prefix=ATTEMPTS_KEY_PREFIX, ttl=DEFAULT_ATTEMPTS_TTL_SECONDS, decode_responses=True),
            dedup_driver=driver_class(url=url, prefix=DEDUP_KEY_PREFIX, ttl=DEFAULT_DEDUP_TTL_SECONDS, decode_responses=True),
            # An ack is remembered for the dedup window: a redelivery of an acked record arrives
            # within one lease extension plus the subscription's maximum retry backoff (spec #886 §2.2).
            acked_driver=driver_class(url=url, prefix=ACKED_KEY_PREFIX, ttl=DEFAULT_DEDUP_TTL_SECONDS, decode_responses=True),
        )


def reset_fallback_warning(state: bool | None = False) -> None:
    """Test helper: reset the one-time fallback warning latch."""
    BookkeepingStoreFactory._fallback_warned = bool(state)
