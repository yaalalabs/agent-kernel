from ...core.util.driver.redis import RedisDriver
from .redis_like import RedisLikeResponseStore


class RedisResponseStore(RedisLikeResponseStore):
    """Redis-backed response store; everything but the driver lives in RedisLikeResponseStore."""

    def __init__(self, url: str, prefix: str = "ak:responses:", ttl: int = 0):
        self._log.debug("Initializing RedisResponseStore with prefix=%s ttl=%s", prefix, ttl)
        self._driver = RedisDriver(url=url, prefix=prefix, ttl=int(ttl), decode_responses=True)
