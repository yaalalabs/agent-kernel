import logging
from datetime import datetime


class LogLevel:
    INFO = 'info'
    DEBUG = 'debug'
    WARN = 'warn'
    ERROR = 'error'
    TRACE = 'trace'


class Logger:
    def __init__(self, name: str, level: LogLevel = LogLevel.INFO):
        self.logger = logging.getLogger(name)
        self.name = name
        self.level = level

        if self.level == LogLevel.INFO:
            self.logger.setLevel(logging.INFO)
        else:
            self.logger.setLevel(logging.DEBUG)

        self.logger.propagate = False  # Prevent duplicate logs
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(message)s')
        handler.setFormatter(formatter)
        self.logger.handlers = [handler]

    @staticmethod
    def get_timestamp():
        return datetime.now().isoformat()

    def info(self, message: str):
        self.logger.info(
            f"{self.get_timestamp()} [{self.name}] INFO {message}")

    def debug(self, message: str):
        if self.level != 'debug':
            return
        self.logger.debug(
            f"{self.get_timestamp()} [{self.name}] DEBUG {message}")

    def warn(self, message: str):
        self.logger.warning(
            f"{self.get_timestamp()} [{self.name}] WARN {message}")

    def error(self, message: str):
        self.logger.error(
            f"{self.get_timestamp()} [{self.name}] ERROR {message}")

    def trace(self, message: str):
        self.logger.debug(
            f"{self.get_timestamp()} [{self.name}] TRACE {message}")


def get_logger(name) -> Logger:
    # Add log level read via ENV variable
    return Logger(name)
