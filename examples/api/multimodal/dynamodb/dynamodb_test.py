import asyncio
import base64
import os
import subprocess
import sys
import uuid
from pathlib import Path

import boto3
import httpx
import pytest
import pytest_asyncio
from agentkernel.test import Test

pytestmark = pytest.mark.asyncio(loop_scope="session")

UNIQUE_RUN_ID = str(uuid.uuid4())[:8]
TABLE_NAME = f"AgentKernelVisualTestTable-{UNIQUE_RUN_ID}"


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
async def dynamodb_client():
    region = os.environ.get("AWS_REGION", "us-east-2")
    profile = os.environ.get("AWS_PROFILE")

    boto3.setup_default_session(profile_name=profile, region_name=region)

    dynamodb = boto3.client("dynamodb")

    print(f"\nCreating temporary DynamoDB table '{TABLE_NAME}'...")
    dynamodb.create_table(
        TableName=TABLE_NAME,
        KeySchema=[
            {"AttributeName": "session_id", "KeyType": "HASH"},
            {"AttributeName": "attachment_id", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "session_id", "AttributeType": "S"},
            {"AttributeName": "attachment_id", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    print("Waiting for table to become active...")
    dynamodb.get_waiter("table_exists").wait(TableName=TABLE_NAME)
    print(f"Table '{TABLE_NAME}' is ready.")

    env = os.environ.copy()
    env["AK_MULTIMODAL__DYNAMODB__TABLE_NAME"] = TABLE_NAME

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

        print(f"\nDeleting temporary DynamoDB table '{TABLE_NAME}'...")
        try:
            dynamodb.delete_table(TableName=TABLE_NAME)
            print("Cleanup complete.")
        except Exception as e:
            print(f"Warning: Could not delete table '{TABLE_NAME}': {e}")


@pytest.mark.order(1)
async def test_image_description(dynamodb_client):
    image_path = Path(__file__).parent / "test_image.webp"
    with open(image_path, "rb") as f:
        b64_data = base64.b64encode(f.read()).decode("utf-8")

    response = await dynamodb_client.send(
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
async def test_followup_retrieval_from_dynamodb(dynamodb_client):
    response = await dynamodb_client.send(
        prompt="Analyze the image again. What is the color of the dust on it? please reply only colour do not include any other words in the answer.",
    )
    print(f"Agent response: {response}")

    Test.compare(
        actual=response,
        expected=["Red", "red", "Reddish", "Red dust"],
        threshold=80,
    )
