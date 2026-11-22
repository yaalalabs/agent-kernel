import io
import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from agentkernel.core.config import AKConfig
from agentkernel.core.logger import TRACE, AKLogger, TraceLine, TraceStage


@pytest.fixture(autouse=True)
def restore_logging_state():
    """
    Snapshots and restores process-wide logging state around every test in this module.
    AKLogger mutates the root and "ak" loggers in place, so without this the handlers it installs
    outlive the test and later tests print their expected logs to stderr.
    """
    loggers = [logging.getLogger(), logging.getLogger("ak")]
    snapshot = [(logger, logger.level, logger.handlers.copy(), logger.propagate) for logger in loggers]
    initialized = AKLogger._initialized
    try:
        yield
    finally:
        for logger, level, handlers, propagate in snapshot:
            logger.setLevel(level)
            logger.handlers.clear()
            logger.handlers.extend(handlers)
            logger.propagate = propagate
        AKLogger._initialized = initialized


class TestResolveLevel:
    """Test AKLogger.resolve_level() method."""

    def test_resolve_level_int(self):
        """Test resolving log level from integer."""
        assert AKLogger.resolve_level(logging.INFO) == logging.INFO
        assert AKLogger.resolve_level(logging.DEBUG) == logging.DEBUG
        assert AKLogger.resolve_level(logging.ERROR) == logging.ERROR

    def test_resolve_level_string_uppercase(self):
        """Test resolving log level from uppercase string."""
        assert AKLogger.resolve_level("INFO") == logging.INFO
        assert AKLogger.resolve_level("DEBUG") == logging.DEBUG
        assert AKLogger.resolve_level("WARNING") == logging.WARNING
        assert AKLogger.resolve_level("ERROR") == logging.ERROR
        assert AKLogger.resolve_level("CRITICAL") == logging.CRITICAL

    def test_resolve_level_string_lowercase(self):
        """Test resolving log level from lowercase string."""
        assert AKLogger.resolve_level("info") == logging.INFO
        assert AKLogger.resolve_level("debug") == logging.DEBUG
        assert AKLogger.resolve_level("warning") == logging.WARNING
        assert AKLogger.resolve_level("error") == logging.ERROR
        assert AKLogger.resolve_level("critical") == logging.CRITICAL

    def test_resolve_level_string_mixed_case(self):
        """Test resolving log level from mixed case string."""
        assert AKLogger.resolve_level("InFo") == logging.INFO
        assert AKLogger.resolve_level("DeBuG") == logging.DEBUG
        assert AKLogger.resolve_level("WaRnInG") == logging.WARNING

    def test_resolve_level_invalid_string(self):
        """Test resolving invalid log level string returns WARNING."""
        assert AKLogger.resolve_level("INVALID") == logging.WARNING
        assert AKLogger.resolve_level("random") == logging.WARNING


class TestAttachStreamHandler:
    """Test AKLogger.attach_stream_handler() method."""

    def test_attach_stream_handler_removes_existing_handlers(self):
        """Test that attach_stream_handler removes existing handlers."""
        logger = logging.getLogger("test_logger")
        logger.handlers.clear()

        # Add a handler
        existing_handler = logging.StreamHandler()
        logger.addHandler(existing_handler)
        assert len(logger.handlers) == 1

        # Attach new handler should remove existing
        AKLogger.attach_stream_handler(logger, attach_formatter=False)
        assert len(logger.handlers) == 1
        assert logger.handlers[0] is not existing_handler

    def test_attach_stream_handler_closes_existing_handlers(self):
        """Test that attach_stream_handler closes existing handlers."""
        logger = logging.getLogger("test_logger_close")
        logger.handlers.clear()

        # Add a handler with close tracking
        existing_handler = logging.StreamHandler()
        existing_handler.close = MagicMock()
        logger.addHandler(existing_handler)

        AKLogger.attach_stream_handler(logger, attach_formatter=False)
        existing_handler.close.assert_called_once()

    def test_attach_stream_handler_adds_stream_handler(self):
        """Test that attach_stream_handler adds a StreamHandler."""
        logger = logging.getLogger("test_logger_add")
        logger.handlers.clear()

        AKLogger.attach_stream_handler(logger, attach_formatter=False)
        assert len(logger.handlers) == 1
        assert isinstance(logger.handlers[0], logging.StreamHandler)

    def test_attach_stream_handler_with_formatter(self):
        """Test that attach_stream_handler adds formatter when requested."""
        logger = logging.getLogger("test_logger_formatter")
        logger.handlers.clear()

        AKLogger.attach_stream_handler(logger, attach_formatter=True)
        assert len(logger.handlers) == 1
        assert logger.handlers[0].formatter is not None
        assert isinstance(logger.handlers[0].formatter, logging.Formatter)

    def test_attach_stream_handler_without_formatter(self):
        """Test that attach_stream_handler does not add formatter when not requested."""
        logger = logging.getLogger("test_logger_no_formatter")
        logger.handlers.clear()

        AKLogger.attach_stream_handler(logger, attach_formatter=False)
        assert len(logger.handlers) == 1
        assert logger.handlers[0].formatter is None


class TestSetHandlersLevel:
    """Test AKLogger.set_handlers_level() method."""

    def test_set_handlers_level_single_handler(self):
        """Test setting level on logger with single handler."""
        logger = logging.getLogger("test_single_handler")
        logger.handlers.clear()

        handler = logging.StreamHandler()
        logger.addHandler(handler)

        AKLogger.set_handlers_level(logger, logging.ERROR)
        assert handler.level == logging.ERROR

    def test_set_handlers_level_multiple_handlers(self):
        """Test setting level on logger with multiple handlers."""
        logger = logging.getLogger("test_multiple_handlers")
        logger.handlers.clear()

        handler1 = logging.StreamHandler()
        handler2 = logging.StreamHandler()
        handler3 = logging.StreamHandler()
        logger.addHandler(handler1)
        logger.addHandler(handler2)
        logger.addHandler(handler3)

        AKLogger.set_handlers_level(logger, logging.DEBUG)
        assert handler1.level == logging.DEBUG
        assert handler2.level == logging.DEBUG
        assert handler3.level == logging.DEBUG

    def test_set_handlers_level_no_handlers(self):
        """Test setting level on logger with no handlers (should not error)."""
        logger = logging.getLogger("test_no_handlers")
        logger.handlers.clear()

        # Should not raise an error
        AKLogger.set_handlers_level(logger, logging.INFO)


class TestSetAKLogLevel:
    """Test AKLogger.set_ak_log_level() method."""

    def test_set_ak_log_level_sets_logger_level(self):
        """Test that set_ak_log_level sets the ak logger level."""
        logger = logging.getLogger("ak")

        AKLogger.set_ak_log_level("ERROR")
        assert logger.level == logging.ERROR

    def test_set_ak_log_level_sets_propagate_false(self):
        """Test that set_ak_log_level sets propagate to False."""
        logger = logging.getLogger("ak")

        AKLogger.set_ak_log_level("INFO")
        assert logger.propagate is False

    def test_set_ak_log_level_attaches_handler(self):
        """Test that set_ak_log_level attaches a stream handler."""
        logger = logging.getLogger("ak")

        logger.handlers.clear()
        AKLogger.set_ak_log_level("DEBUG")
        assert len(logger.handlers) == 1
        assert isinstance(logger.handlers[0], logging.StreamHandler)

    def test_set_ak_log_level_sets_handler_level(self):
        """Test that set_ak_log_level sets handler level."""
        logger = logging.getLogger("ak")
        logger.handlers.clear()

        AKLogger.set_ak_log_level("WARNING")
        assert logger.handlers[0].level == logging.WARNING


class TestSetSystemLogLevel:
    """Test AKLogger.set_system_log_level() method."""

    def test_set_system_log_level_sets_logger_level(self):
        """Test that set_system_log_level sets the root logger level."""
        logger = logging.getLogger()

        AKLogger.set_system_log_level("ERROR")
        assert logger.level == logging.ERROR

    def test_set_system_log_level_sets_propagate_false(self):
        """Test that set_system_log_level sets propagate to False."""
        logger = logging.getLogger()

        AKLogger.set_system_log_level("INFO")
        assert logger.propagate is False

    def test_set_system_log_level_attaches_handler(self):
        """Test that set_system_log_level attaches a stream handler."""
        logger = logging.getLogger()

        logger.handlers.clear()
        AKLogger.set_system_log_level("DEBUG")
        assert len(logger.handlers) == 1
        assert isinstance(logger.handlers[0], logging.StreamHandler)

    def test_set_system_log_level_sets_handler_level(self):
        """Test that set_system_log_level sets handler level."""
        logger = logging.getLogger()
        logger.handlers.clear()

        AKLogger.set_system_log_level("WARNING")
        assert logger.handlers[0].level == logging.WARNING


class TestConfigureFromConfig:
    """Test AKLogger.configure_from_config() method."""

    def setup_method(self):
        """Reset initialization state before each test (restore_logging_state handles teardown)."""
        AKLogger._initialized = False

    @patch.object(AKConfig, "get")
    def test_configure_from_config_idempotent(self, mock_config_get):
        """Test that configure_from_config is idempotent - only runs once."""
        mock_config = MagicMock()
        mock_config.logging.ak.level = "INFO"
        mock_config.logging.system.level = "DEBUG"
        mock_config_get.return_value = mock_config

        # First call should configure
        AKLogger.configure_from_config()
        assert AKLogger._initialized is True

        # Reset mock to track if it's called again
        mock_config_get.reset_mock()

        # Second call should return early without reconfiguring
        AKLogger.configure_from_config()
        mock_config_get.assert_not_called()

    @patch.object(AKConfig, "get")
    def test_configure_from_config_honors_ak_level(self, mock_config_get):
        """Test that configure_from_config honors configured AK log level."""
        mock_config = MagicMock()
        mock_config.logging.ak.level = "ERROR"
        mock_config.logging.system.level = None
        mock_config_get.return_value = mock_config

        logger = logging.getLogger("ak")
        logger.handlers.clear()

        AKLogger.configure_from_config()
        assert logger.level == logging.ERROR

    @patch.object(AKConfig, "get")
    def test_configure_from_config_honors_system_level(self, mock_config_get):
        """Test that configure_from_config honors configured system log level."""
        mock_config = MagicMock()
        mock_config.logging.ak.level = None
        mock_config.logging.system.level = "DEBUG"
        mock_config_get.return_value = mock_config

        logger = logging.getLogger()
        logger.handlers.clear()

        AKLogger.configure_from_config()
        assert logger.level == logging.DEBUG

    @patch.object(AKConfig, "get")
    def test_configure_from_config_both_levels(self, mock_config_get):
        """Test that configure_from_config configures both loggers when both levels set."""
        mock_config = MagicMock()
        mock_config.logging.ak.level = "WARNING"
        mock_config.logging.system.level = "ERROR"
        mock_config_get.return_value = mock_config

        ak_logger = logging.getLogger("ak")
        root_logger = logging.getLogger()

        ak_logger.handlers.clear()
        root_logger.handlers.clear()

        AKLogger.configure_from_config()
        assert ak_logger.level == logging.WARNING
        assert root_logger.level == logging.ERROR

    @patch.object(AKConfig, "get")
    def test_configure_from_config_none_levels(self, mock_config_get):
        """Test that configure_from_config handles None levels gracefully."""
        mock_config = MagicMock()
        mock_config.logging.ak.level = None
        mock_config.logging.system.level = None
        mock_config_get.return_value = mock_config

        # Should not raise an error
        AKLogger.configure_from_config()
        assert AKLogger._initialized is True

    @patch.object(AKConfig, "get")
    def test_configure_from_config_sets_initialized_flag(self, mock_config_get):
        """Test that configure_from_config sets the initialized flag."""
        mock_config = MagicMock()
        mock_config.logging.ak.level = "INFO"
        mock_config.logging.system.level = None
        mock_config_get.return_value = mock_config

        assert AKLogger._initialized is False
        AKLogger.configure_from_config()
        assert AKLogger._initialized is True

    def test_first_akconfig_get_triggers_configuration(self):
        """Test that the first AKConfig.get() call configures logging (lazy load path)."""
        AKConfig._reset()
        try:
            with patch.object(AKLogger, "configure_from_config") as mock_configure:
                AKConfig.get()
                mock_configure.assert_called_once()

                # Subsequent get() calls return the cached instance without reconfiguring
                mock_configure.reset_mock()
                AKConfig.get()
                mock_configure.assert_not_called()
        finally:
            AKConfig._reset()


class TestGlobalLoggingSideEffects:
    """Test that logging operations don't have unexpected global side effects."""

    def test_ak_logger_does_not_clobber_root_logger(self):
        """Test that configuring AK logger doesn't affect root logger."""
        root_logger = logging.getLogger()
        ak_logger = logging.getLogger("ak")

        root_original_level = root_logger.level
        root_original_handlers = root_logger.handlers.copy()
        ak_logger.handlers.clear()

        # Configure AK logger
        AKLogger.set_ak_log_level("DEBUG")

        # Root logger should be unchanged
        assert root_logger.level == root_original_level
        assert len(root_logger.handlers) == len(root_original_handlers)

    def test_root_logger_does_not_clobber_ak_logger(self):
        """Test that configuring root logger doesn't affect AK logger."""
        root_logger = logging.getLogger()
        ak_logger = logging.getLogger("ak")

        root_logger.handlers.clear()
        ak_original_level = ak_logger.level
        ak_original_handlers = ak_logger.handlers.copy()

        # Configure root logger
        AKLogger.set_system_log_level("DEBUG")

        # AK logger should be unchanged
        assert ak_logger.level == ak_original_level
        assert len(ak_logger.handlers) == len(ak_original_handlers)

    def test_multiple_configure_calls_safe(self):
        """Test that multiple configure calls are safe after reset."""
        AKLogger._initialized = False

        with patch.object(AKConfig, "get") as mock_config_get:
            mock_config = MagicMock()
            mock_config.logging.ak.level = "INFO"
            mock_config.logging.system.level = None
            mock_config_get.return_value = mock_config

            # First call
            AKLogger.configure_from_config()
            assert AKLogger._initialized is True

            # Reset and call again
            AKLogger._initialized = False
            AKLogger.configure_from_config()
            assert AKLogger._initialized is True

            # Should have called config.get() twice
            assert mock_config_get.call_count == 2


def _ak_output(level: str, log: Callable[[logging.Logger], None]) -> str:
    """Configure the ak logger at ``level``, run ``log`` on a child logger, return what the handler wrote."""
    AKLogger.set_ak_log_level(level)
    stream = io.StringIO()
    logging.getLogger("ak").handlers[0].setStream(stream)
    log(logging.getLogger("ak.test.trace"))
    return stream.getvalue()


class TestTrace:
    """TRACE level, line format and TraceLine.parse."""

    def test_trace_level_registered_and_resolvable(self):
        assert TRACE == 5
        assert logging.getLevelName(TRACE) == "TRACE"
        assert AKLogger.resolve_level("trace") == TRACE

    def test_stdlib_logging_not_patched(self):
        assert not hasattr(logging, "TRACE")

    def test_trace_written_at_trace_level(self):
        out = _ak_output("TRACE", lambda log: log.log(TRACE, "[%s] request_id=%s", TraceStage.AGENT_START, "r1"))
        assert " - ak.test.trace - TRACE - [AGENT_START] request_id=r1" in out

    def test_trace_filtered_at_debug(self):
        out = _ak_output("DEBUG", lambda log: log.log(TRACE, "[%s] request_id=%s", TraceStage.AGENT_START, "r1"))
        assert out == ""

    def test_timestamp_is_utc_iso_with_millis(self):
        out = _ak_output("INFO", lambda log: log.info("hello"))
        match = re.match(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z) - ", out)
        assert match
        assert abs((datetime.now(UTC) - datetime.fromisoformat(match.group(1))).total_seconds()) < 60

    def test_parse_round_trip(self):
        message = 'said "hi" and left'
        out = _ak_output(
            "TRACE",
            lambda log: log.log(TRACE, '[%s] request_id=%s message="%s"', TraceStage.AGENT_DONE, "r-2", message),
        )
        line = TraceLine.parse(out)
        assert line is not None
        assert line.stage is TraceStage.AGENT_DONE
        assert line.request_id == "r-2"
        assert line.message == message
        assert line.timestamp.tzinfo is not None
        assert line.timestamp.isoformat(timespec="milliseconds").replace("+00:00", "Z") == out[:24]

    def test_parse_without_message(self):
        line = TraceLine.parse("2026-10-21T08:15:12.345Z - ak.pipeline - TRACE - [INPUT_ENQUEUED] request_id=abc")
        assert line == TraceLine(datetime(2026, 10, 21, 8, 15, 12, 345000, tzinfo=UTC), TraceStage.INPUT_ENQUEUED, "abc", None)

    def test_parse_tolerates_prefix(self):
        line = TraceLine.parse("2026-10-21T08:15:13.000Z\tabc-123\t2026-10-21T08:15:12.345Z - ak.x - TRACE - [AGENT_START] request_id=r")
        assert line is not None
        assert line.stage is TraceStage.AGENT_START
        assert line.timestamp == datetime(2026, 10, 21, 8, 15, 12, 345000, tzinfo=UTC)

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "garbage",
            "2026-10-21T08:15:12.345Z - ak.x - INFO - Agent done: request_id=r",
            "2026-10-21T08:15:12.345Z - ak.x - TRACE - [NOT_A_STAGE] request_id=r",
            "2026-10-21T08:15:12.345Z - ak.x - TRACE - no stage here",
            "2026-13-45T08:15:12.345Z - ak.x - TRACE - [AGENT_START] request_id=r",
        ],
    )
    def test_parse_returns_none_for_non_trace_lines(self, text):
        assert TraceLine.parse(text) is None
