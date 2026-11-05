"""Credentialed REST smoke test for the Claude example."""

import asyncio
import os
import subprocess
import sys
from uuid import uuid4

import httpx
import pytest


@pytest.mark.asyncio
async def test_weather_agent_over_rest():
    if not (
        os.getenv("ANTHROPIC_API_KEY")
        or os.getenv("CLAUDE_CODE_USE_BEDROCK")
        or os.getenv("CLAUDE_CODE_USE_VERTEX")
        or os.getenv("CLAUDE_CODE_USE_FOUNDRY")
    ):
        pytest.skip("Claude API or cloud provider credentials are required")

    process = subprocess.Popen([sys.executable, "app.py"])
    try:
        async with httpx.AsyncClient(base_url="http://127.0.0.1:8000", timeout=120.0) as client:
            for _ in range(50):
                if process.poll() is not None:
                    pytest.fail("REST API exited before becoming ready")
                try:
                    response = await client.get("/openapi.json")
                    response.raise_for_status()
                    break
                except httpx.RequestError:
                    await asyncio.sleep(0.2)
            else:
                pytest.fail("REST API did not become ready")

            response = await client.post(
                "/api/v1/chat",
                json={"agent": "triage", "session_id": str(uuid4()), "prompt": "What is the weather in Tokyo?"},
            )
            response.raise_for_status()
            assert "sunny" in response.json()["result"].lower()
    finally:
        process.terminate()
        process.wait(timeout=10)
