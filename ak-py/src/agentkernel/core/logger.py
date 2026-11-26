import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import ClassVar

from .config import AKConfig

# Below DEBUG; 5 is the value other libraries (e.g. uvicorn) use for TRACE, so the name stays consistent
TRACE = 5
logging.addLevelName(TRACE, "TRACE")


class TraceStage(StrEnum):
    """Request-path stages written at ``TRACE``, in request order. The logged value is the name."""

    REQUEST_RECEIVED = "REQUEST_RECEIVED"
    INPUT_ENQUEUED = "INPUT_ENQUEUED"
    AGENT_RECEIVED = "AGENT_RECEIVED"
    AGENT_START = "AGENT_START"
    AGENT_FIRST_CHUNK = "AGENT_FIRST_CHUNK"
    AGENT_DONE = "AGENT_DONE"
    OUTPUT_ENQUEUED = "OUTPUT_ENQUEUED"
    OUTPUT_RECEIVED = "OUTPUT_RECEIVED"
    RESPONSE_DELIVERED = "RESPONSE_DELIVERED"
    RESPONSE_POLL_START = "RESPONSE_POLL_START"
    RESPONSE_FOUND = "RESPONSE_FOUND"


@dataclass(frozen=True)
class TraceLine:
    """One parsed ``TRACE`` log line."""

    timestamp: datetime
    stage: TraceStage
    request_id: str
    message: str | None = None

    # Matches the lines AKLogger's formatter writes at TRACE; the two change together. The optional AK-written
    # message comes first (`[STAGE] message="..." request_id=...`) and the client-supplied request_id runs to end
    # of line, so an id containing spaces or a look-alike `message="..."` still parses whole. A CRLF line ending is dropped.
    _PATTERN: ClassVar[re.Pattern] = re.compile(
        r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z) - \S+ - TRACE - \[([A-Z_]+)\] (?:message="(.*?)" )?request_id=(.+?)\r?$'
    )

    @classmethod
    def parse(cls, line: str) -> "TraceLine | None":
        """Parse a trace line written by AK, ignoring any prefix the log backend adds.

        :param line: A log line.
        :return: The parsed trace line, or None if it is not a trace line or has an unknown stage.
        """
        match = cls._PATTERN.search(line)
        if not match or match.group(2) not in TraceStage.__members__:
            return None
        timestamp, stage, message, request_id = match.groups()
        try:
            parsed_timestamp = datetime.fromisoformat(timestamp)
        except ValueError:
            return None
        return cls(parsed_timestamp, TraceStage[stage], request_id, message)


class AKLogger:
    """Agent Kernel logger configuration utility."""

    _initialized = False

    @staticmethod
    def resolve_level(level: str | int) -> int:
        """Resolve log level from string or int.

        :param level: Log level as string or int.
        :return: Resolved log level as int.
        """
        if isinstance(level, int):
            return level

        level_name = str(level).upper()

        get_mapping = getattr(logging, "getLevelNamesMapping", None)
        if callable(get_mapping):
            return get_mapping().get(level_name, logging.WARNING)

        return logging.WARNING

    @staticmethod
    def attach_stream_handler(logger: logging.Logger, attach_formatter=False) -> None:
        """Attach a stream handler to the logger.

        :param logger: Logger instance to attach handler to.
        :param attach_formatter: Whether to attach a default formatter.
        :return: None.
        """
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
            handler.close()
        handler = logging.StreamHandler()
        if attach_formatter:
            formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
            # UTC ISO 8601 with milliseconds, e.g. 2026-10-21T08:15:12.345Z, so lines from different hosts compare.
            # TraceLine._PATTERN parses this format; change them together.
            formatter.converter = time.gmtime
            formatter.default_time_format = "%Y-%m-%dT%H:%M:%S"
            formatter.default_msec_format = "%s.%03dZ"
            handler.setFormatter(formatter)
        logger.addHandler(handler)

    @staticmethod
    def set_handlers_level(logger: logging.Logger, level: int) -> None:
        """Set the level for all handlers on a logger.

        :param logger: Logger instance to set handler levels for.
        :param level: Log level to set.
        :return: None.
        """
        for handler in logger.handlers:
            handler.setLevel(level)

    @staticmethod
    def set_ak_log_level(level: str):
        """Set the log level for the AK logger.

        :param level: Log level as string.
        :return: None.
        """
        resolved_level = AKLogger.resolve_level(level)
        ak_logger = logging.getLogger("ak")
        ak_logger.setLevel(resolved_level)
        ak_logger.propagate = False  # stopping the propagation here so that it won't propagate to the root, so loggers like "ak.api" with propagate=True (propagate is True by default, which is the case here) won't propagate to the root, propagation will stop at this level ("ak" level)
        AKLogger.attach_stream_handler(logger=ak_logger, attach_formatter=True)
        AKLogger.set_handlers_level(logger=ak_logger, level=resolved_level)

    @staticmethod
    def set_system_log_level(level: str):
        """Set the log level for the system root logger.

        :param level: Log level as string.
        :return: None.
        """
        resolved_level = AKLogger.resolve_level(level)
        root_logger = logging.getLogger()
        root_logger.setLevel(resolved_level)
        root_logger.propagate = False  # the root logger has nowhere to propagate to because it is the root
        AKLogger.attach_stream_handler(logger=root_logger, attach_formatter=True)
        AKLogger.set_handlers_level(logger=root_logger, level=resolved_level)

    @classmethod
    def configure_from_config(cls):
        """Configure loggers from AKConfig settings.

        :return: None.
        """
        if cls._initialized:
            return
        config = AKConfig.get()
        ak_level = config.logging.ak.level
        system_level = config.logging.system.level
        if system_level:
            cls.set_system_log_level(system_level)
        if ak_level:
            cls.set_ak_log_level(ak_level)
        cls._initialized = True
