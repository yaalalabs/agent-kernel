import asyncio
import base64
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from agentkernel.test import Test

pytestmark = pytest.mark.asyncio(loop_scope="session")

UNIQUE_RUN_ID = str(uuid.uuid4())[:8]
REDIS_PORT = 6399  # non-default port to avoid conflict with any local Redis
REDIS_CONTAINER_NAME = f"ak-redis-multimodal-test-{UNIQUE_RUN_ID}"

# Local test image
TEST_IMAGE_PATH = Path(__file__).parent / "test_image.webp"


class APITestClient:
    def __init__(self, url):
        self.url = url
        self.session_id = str(uuid.uuid4())

    async def send(self, prompt, images=None, files=None):
        payload = {
            "prompt": prompt,
            "session_id": self.session_id,
            "agent": "support",
        }
        if images:
            payload["images"] = images
        if files:
            payload["files"] = files

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{self.url}/api/v1/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data.get("result", "")


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def redis_client():
    use_docker = shutil.which("docker") is not None
    redis_proc = None

    if use_docker:
        # Start Redis via Docker container
        print(f"\nStarting Redis container '{REDIS_CONTAINER_NAME}' on port {REDIS_PORT}...")
        redis_proc = subprocess.Popen(
            [
                "docker",
                "run",
                "--rm",
                "--name",
                REDIS_CONTAINER_NAME,
                "-p",
                f"{REDIS_PORT}:6379",
                "redis:alpine",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        # Fall back to a locally installed redis-server
        redis_server_bin = shutil.which("redis-server")
        if redis_server_bin is None:
            pytest.skip(
                "Neither 'docker' nor 'redis-server' is available. "
                "Install one of them to run this test. "
                "On Ubuntu: sudo apt-get install -y redis-server"
            )
        print(f"\nDocker not found. Starting local redis-server on port {REDIS_PORT}...")
        redis_proc = subprocess.Popen(
            [redis_server_bin, "--port", str(REDIS_PORT), "--daemonize", "no"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    # Wait for Redis to be ready
    await asyncio.sleep(3)
    print("Redis is ready.")

    redis_url = f"redis://localhost:{REDIS_PORT}"
    env = os.environ.copy()
    env["AK_MULTIMODAL__REDIS__URL"] = redis_url

    proc = subprocess.Popen(
        [sys.executable, "app.py"],
        stdout=sys.stdout,
        stderr=sys.stderr,
        env=env,
        cwd=str(Path(__file__).parent),
    )
    await asyncio.sleep(5)

    try:
        yield APITestClient("http://localhost:8000")
    finally:
        proc.terminate()
        proc.wait()

        if use_docker:
            print(f"\nStopping Redis container '{REDIS_CONTAINER_NAME}'...")
            subprocess.run(
                ["docker", "stop", REDIS_CONTAINER_NAME],
                check=False,
                capture_output=True,
            )
        if redis_proc is not None:
            redis_proc.terminate()
            redis_proc.wait()
        print("Cleanup complete.")


@pytest.mark.order(1)
async def test_image_description(redis_client):
    with open(TEST_IMAGE_PATH, "rb") as f:
        b64_data = base64.b64encode(f.read()).decode("utf-8")

    response = await redis_client.send(
        prompt="What animal is this? Reply with exactly 'Elephant' and nothing else.",
        images=[
            {
                "name": "elephant",
                "mime_type": "image/webp",
                "image_data": b64_data,
            }
        ],
    )
    print(f"Agent response: {response}")

    Test.compare(
        actual=response,
        expected=["Elephant", "elephant", "An elephant", "It's an elephant"],
        threshold=80,
    )


@pytest.mark.order(2)
async def test_followup_retrieval_from_redis(redis_client):
    response = await redis_client.send(
        prompt="Analyze the image again. What is the color of the dust on it? please reply only colour do not include any other words in the answer.",
    )
    print(f"Agent response: {response}")

    Test.compare(
        actual=response,
        expected=["Red", "red", "Reddish", "Red dust"],
        threshold=80,
    )
