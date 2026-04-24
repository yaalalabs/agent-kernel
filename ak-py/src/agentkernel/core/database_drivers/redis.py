
import logging
import time
import traceback
import redis
from typing import Optional




class BaseRedisDriver:
    """
    BaseRedisDriver provides common connection management and helpers for
    Redis operations, to be extended by specific drivers like session or
    attachment drivers.
    """

    def __init__(self, url: str, ttl: int, prefix: str):
        self._url = url
        self._ttl = ttl
        self._prefix = prefix
        self._log = logging.getLogger("ak.core.database_drivers.redis.base_driver")
        self._redis_client = None

    @property
    def client(self):
        """
        Returns the Redis client instance, connecting lazily if needed.
        """
        if self._redis_client is None:
            self._connect()
        else:
            try:
                self._redis_client.ping()
            except redis.RedisError:
                self._log.warning("Redis client is not alive, reconnecting")
                self._connect()
            except Exception as e:
                self._log.error(f"Unexpected error while pinging Redis client: {e}")
                self._log.error(traceback.format_exc())
                self._connect()
        return self._redis_client

    @property
    def ttl(self):
        return self._ttl

    def _connect(self) -> None:
        """
        Connects to Redis using the configured URL with self-healing retries.
        """
        retries = 3
        last_err: Optional[Exception] = None
        
        for attempt in range(retries):
            try:
                self._log.debug(f"Connecting to Redis at {self._url}")
                
                client = redis.from_url(self._url, decode_responses=False, socket_connect_timeout=5)
                client.ping()
                self._redis_client = client
                
                
                return
                
            except Exception as e:
                last_err = e
                self._log.warning(f"Redis connection attempt {attempt + 1} failed: {e}")
                
             
                if attempt < retries - 1:
                    time.sleep(2)
                    
        
        if last_err:
            raise last_err
        
    def set():
        pass