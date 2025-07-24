"""
Utility functions for the Agent Kernel common library.
"""
from typing import Any, Dict, List, Optional


def validate_config(config: Dict[str, Any]) -> bool:
    """
    Validate a configuration dictionary.

    Args:
        config: The configuration dictionary to validate.

    Returns:
        bool: True if the configuration is valid, False otherwise.
    """
    # This is a placeholder implementation
    return True if config else False


def merge_configs(base_config: Dict[str, Any], override_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Merge two configuration dictionaries.

    Args:
        base_config: The base configuration dictionary.
        override_config: The configuration dictionary to override values in the base.

    Returns:
        Dict[str, Any]: The merged configuration dictionary.
    """
    # This is a placeholder implementation
    result = base_config.copy()
    result.update(override_config)
    return result


class Logger:
    """
    A simple logger class for Agent Kernel components.
    """

    def __init__(self, name: str, level: str = "INFO"):
        """
        Initialize a new Logger instance.

        Args:
            name: The name of the logger.
            level: The logging level.
        """
        self.name = name
        self.level = level

    def info(self, message: str) -> None:
        """
        Log an info message.

        Args:
            message: The message to log.
        """
        # This is a placeholder implementation
        print(f"[INFO] {self.name}: {message}")

    def error(self, message: str) -> None:
        """
        Log an error message.

        Args:
            message: The message to log.
        """
        # This is a placeholder implementation
        print(f"[ERROR] {self.name}: {message}")

    def debug(self, message: str) -> None:
        """
        Log a debug message.

        Args:
            message: The message to log.
        """
        # This is a placeholder implementation
        if self.level == "DEBUG":
            print(f"[DEBUG] {self.name}: {message}")