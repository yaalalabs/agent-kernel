import logging
from unittest.mock import MagicMock, patch

import pytest

from agentkernel.core.config import AKConfig
from agentkernel.core.logger import AKLogger


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
        original_level = logger.level

        AKLogger.set_ak_log_level("ERROR")
        assert logger.level == logging.ERROR

        # Restore
        logger.setLevel(original_level)

    def test_set_ak_log_level_sets_propagate_false(self):
        """Test that set_ak_log_level sets propagate to False."""
        logger = logging.getLogger("ak")
        original_propagate = logger.propagate

        AKLogger.set_ak_log_level("INFO")
        assert logger.propagate is False

        # Restore
        logger.propagate = original_propagate

    def test_set_ak_log_level_attaches_handler(self):
        """Test that set_ak_log_level attaches a stream handler."""
        logger = logging.getLogger("ak")
        original_handlers = logger.handlers.copy()

        logger.handlers.clear()
        AKLogger.set_ak_log_level("DEBUG")
        assert len(logger.handlers) == 1
        assert isinstance(logger.handlers[0], logging.StreamHandler)

        # Restore
        logger.handlers.clear()
        for handler in original_handlers:
            logger.addHandler(handler)

    def test_set_ak_log_level_sets_handler_level(self):
        """Test that set_ak_log_level sets handler level."""
        logger = logging.getLogger("ak")
        logger.handlers.clear()

        AKLogger.set_ak_log_level("WARNING")
        assert logger.handlers[0].level == logging.WARNING

        logger.handlers.clear()


class TestSetSystemLogLevel:
    """Test AKLogger.set_system_log_level() method."""

    def test_set_system_log_level_sets_logger_level(self):
        """Test that set_system_log_level sets the root logger level."""
        logger = logging.getLogger()
        original_level = logger.level

        AKLogger.set_system_log_level("ERROR")
        assert logger.level == logging.ERROR

        # Restore
        logger.setLevel(original_level)

    def test_set_system_log_level_sets_propagate_false(self):
        """Test that set_system_log_level sets propagate to False."""
        logger = logging.getLogger()
        original_propagate = logger.propagate

        AKLogger.set_system_log_level("INFO")
        assert logger.propagate is False

        # Restore
        logger.propagate = original_propagate

    def test_set_system_log_level_attaches_handler(self):
        """Test that set_system_log_level attaches a stream handler."""
        logger = logging.getLogger()
        original_handlers = logger.handlers.copy()

        logger.handlers.clear()
        AKLogger.set_system_log_level("DEBUG")
        assert len(logger.handlers) == 1
        assert isinstance(logger.handlers[0], logging.StreamHandler)

        # Restore
        logger.handlers.clear()
        for handler in original_handlers:
            logger.addHandler(handler)

    def test_set_system_log_level_sets_handler_level(self):
        """Test that set_system_log_level sets handler level."""
        logger = logging.getLogger()
        logger.handlers.clear()

        AKLogger.set_system_log_level("WARNING")
        assert logger.handlers[0].level == logging.WARNING

        logger.handlers.clear()


class TestConfigureFromConfig:
    """Test AKLogger.configure_from_config() method."""

    def setup_method(self):
        """Reset initialization state before each test."""
        AKLogger._initialized = False

    def teardown_method(self):
        """Reset initialization state after each test."""
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
        original_level = logger.level
        logger.handlers.clear()

        AKLogger.configure_from_config()
        assert logger.level == logging.ERROR

        # Restore
        logger.setLevel(original_level)
        logger.handlers.clear()

    @patch.object(AKConfig, "get")
    def test_configure_from_config_honors_system_level(self, mock_config_get):
        """Test that configure_from_config honors configured system log level."""
        mock_config = MagicMock()
        mock_config.logging.ak.level = None
        mock_config.logging.system.level = "DEBUG"
        mock_config_get.return_value = mock_config

        logger = logging.getLogger()
        original_level = logger.level
        logger.handlers.clear()

        AKLogger.configure_from_config()
        assert logger.level == logging.DEBUG

        # Restore
        logger.setLevel(original_level)
        logger.handlers.clear()

    @patch.object(AKConfig, "get")
    def test_configure_from_config_both_levels(self, mock_config_get):
        """Test that configure_from_config configures both loggers when both levels set."""
        mock_config = MagicMock()
        mock_config.logging.ak.level = "WARNING"
        mock_config.logging.system.level = "ERROR"
        mock_config_get.return_value = mock_config

        ak_logger = logging.getLogger("ak")
        root_logger = logging.getLogger()

        ak_original = ak_logger.level
        root_original = root_logger.level
        ak_logger.handlers.clear()
        root_logger.handlers.clear()

        AKLogger.configure_from_config()
        assert ak_logger.level == logging.WARNING
        assert root_logger.level == logging.ERROR

        # Restore
        ak_logger.setLevel(ak_original)
        root_logger.setLevel(root_original)
        ak_logger.handlers.clear()
        root_logger.handlers.clear()

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


class TestGlobalLoggingSideEffects:
    """Test that logging operations don't have unexpected global side effects."""

    def test_ak_logger_does_not_clobber_root_logger(self):
        """Test that configuring AK logger doesn't affect root logger."""
        root_logger = logging.getLogger()
        ak_logger = logging.getLogger("ak")

        root_original_level = root_logger.level
        root_original_handlers = root_logger.handlers.copy()
        ak_original_level = ak_logger.level
        ak_logger.handlers.clear()

        # Configure AK logger
        AKLogger.set_ak_log_level("DEBUG")

        # Root logger should be unchanged
        assert root_logger.level == root_original_level
        assert len(root_logger.handlers) == len(root_original_handlers)

        # Restore
        ak_logger.setLevel(ak_original_level)
        ak_logger.handlers.clear()

    def test_root_logger_does_not_clobber_ak_logger(self):
        """Test that configuring root logger doesn't affect AK logger."""
        root_logger = logging.getLogger()
        ak_logger = logging.getLogger("ak")

        root_original_level = root_logger.level
        root_logger.handlers.clear()
        ak_original_level = ak_logger.level
        ak_original_handlers = ak_logger.handlers.copy()

        # Configure root logger
        AKLogger.set_system_log_level("DEBUG")

        # AK logger should be unchanged
        assert ak_logger.level == ak_original_level
        assert len(ak_logger.handlers) == len(ak_original_handlers)

        # Restore
        root_logger.setLevel(root_original_level)
        root_logger.handlers.clear()

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

        AKLogger._initialized = False
