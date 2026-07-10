import json

import pytest
import pytest_asyncio
from agentkernel.test import Test

pytestmark = pytest.mark.asyncio(loop_scope="session")  # uses a single session for all tests


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def test_client():
    test = Test("demo.py")
    await test.start()
    try:
        yield test
    finally:
        await test.stop()


@pytest.mark.order(1)
async def test_structured_reply_is_json(test_client):
    response = await test_client.send("John Doe can be reached at john.doe@example.com or on 077-1234567")
    data = json.loads(response)
    assert data["name"] == "John Doe"
    assert data["email"] == "john.doe@example.com"
    assert data["phone"] == "077-1234567"


@pytest.mark.order(2)
async def test_missing_fields_are_null(test_client):
    response = await test_client.send("You can write to Jane Smith at jane@example.com")
    data = json.loads(response)
    assert data["name"] == "Jane Smith"
    assert data["email"] == "jane@example.com"
    assert data["phone"] is None
