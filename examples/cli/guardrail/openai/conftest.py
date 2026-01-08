"""
Pytest configuration for guardrail OpenAI example tests.
Suppresses stdout from openai-guardrails library to prevent test failures.
"""

import contextlib
import io
import sys

import pytest


@pytest.fixture(autouse=True)
def suppress_guardrails_stdout():
    """
    Automatically suppress stdout from openai-guardrails library during tests.
    """
    # Store original stdout
    original_stdout = sys.stdout
    
    # Create a string buffer to capture output
    captured_output = io.StringIO()
    
    # Redirect stdout to the buffer
    sys.stdout = captured_output
    
    try:
        yield
    finally:
        # Restore original stdout
        sys.stdout = original_stdout
