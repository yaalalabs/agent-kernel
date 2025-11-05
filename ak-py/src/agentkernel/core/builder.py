import logging
from enum import StrEnum
import traceback

from .config import AKConfig
from .sessions.in_memory import InMemorySessionStore
from .sessions.redis import RedisSessionStore
from .sessions.redis import RedisDriver
from .sessions import SessionStore


class Builder:
    _log = logging.getLogger("ak.builder")


class SessionStoreType(StrEnum):
    IN_MEMORY = "IN_MEMORY"
    REDIS = "REDIS"

    @classmethod
    def from_str(cls, type_str: str) -> "SessionStoreType":
        try:
            return cls[type_str.upper()]
        except KeyError:
            Builder._log.warning(f"Invalid session store type '{type_str}', falling back to IN_MEMORY")
            # Traceback logging removed as this is an expected control flow case
            return SessionStoreType.IN_MEMORY


class SessionStoreBuilder(Builder):
    @staticmethod
    def build() -> SessionStore:
        session_store_type: SessionStoreType = SessionStoreType.from_str(AKConfig.get().session.type)

        Builder._log.info(f"Building {session_store_type} session store")
        if session_store_type == SessionStoreType.REDIS:
            return RedisSessionStore(RedisDriver())
        else:
            return InMemorySessionStore()
