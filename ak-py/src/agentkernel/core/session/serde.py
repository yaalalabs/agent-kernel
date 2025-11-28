import logging
import pickle
from typing import Any


class BinarySerde:
    """
    BinarySerde provides serialization and deserialization of Session objects for Redis
    storage using a JSON representation.
    """

    _log = logging.getLogger("ak.core.session.binaryserde")

    # Binary headers to distinguish formats

    @classmethod
    def dumps(cls, obj: Any) -> bytes:
        """
        Serialize a value to JSON, falling back to repr for non-serializable objects.
        :param obj: The value to serialize.
        :return: The serialized value as a JSON string.
        """
        cls._log.debug(f"dumped: {obj}")
        return pickle.dumps(obj)

    @classmethod
    def loads(cls, payload: bytes) -> Any:
        """
        Deserialize a JSON string/bytes back into a Python object; returns None if missing.
        :param payload: The JSON string or bytes to deserialize.
        :return: The deserialized value.
        """
        cls._log.debug(f"loads: {type(payload)}")
        if payload is None:
            return None
        loaded = pickle.loads(payload)
        cls._log.debug(f"loaded: {loaded}")
        return loaded
