import logging

from .config import AKConfig


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
            handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
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
