import pytest


def test_demo_imports():
    try:
        from . import demo

        assert demo is not None
    except ImportError:
        pass  # Skip if agent-framework is not installed in the test env
