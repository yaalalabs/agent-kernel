import os

import pytest

REPLY_TIMEOUT_SECONDS = 180
POLL_INTERVAL_SECONDS = 5


def require_env(*names: str) -> dict[str, str]:
    """Return the requested environment variables, skipping the test if any is missing."""
    missing = [name for name in names if not os.environ.get(name)]
    if missing:
        pytest.skip(f"Missing environment variables: {', '.join(missing)}")
    return {name: os.environ[name] for name in names}
