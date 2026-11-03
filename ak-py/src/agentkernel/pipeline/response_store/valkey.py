from ...core.util.driver.valkey import ValkeyDriver
from .redis_like import RedisLikeResponseStore


class ValkeyResponseStore(RedisLikeResponseStore):
    """Valkey-backed response store; everything but the driver lives in RedisLikeResponseStore."""

    def __init__(self, url: str, prefix: str = "ak:responses:", ttl: int = 0):
        self._log.debug("Initializing ValkeyResponseStore with prefix=%s ttl=%s", prefix, ttl)
        self._driver = ValkeyDriver(url=url, prefix=prefix, ttl=int(ttl), decode_responses=True)
