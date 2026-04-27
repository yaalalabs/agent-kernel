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


@pytest.mark.order(2)
async def test_fallback_when_kb_empty(test_client):
    await test_client.send("What is the capital of France?")
    response = (test_client.last_agent_response or "").lower()
    assert "paris" in response


@pytest.mark.order(3)
async def test_kb_descriptions_exposed(test_client):
    await test_client.send("Which knowledge base do you use to store information?")
    await test_client.expect(["ChromaDB"])


@pytest.mark.order(4)
async def test_kb_schemas_available(test_client):
    await test_client.send("Summarize the knowledge base schemas you know about.")
    await test_client.expect(["ChromaDB", "semantic"])


@pytest.mark.order(5)
async def test_store_data(test_client):
    """Test storing facts/documents into ChromaDB"""
    await test_client.send(
        "Store this fact: The capital of France is Paris, located on the Seine River. "
        "The city is known for the Eiffel Tower."
    )
    response = (test_client.last_agent_response or "").lower()
    assert any(
        keyword in response for keyword in ["stored", "added", "saved", "recorded"]
    )


@pytest.mark.order(6)
async def test_retrieve_stored_data(test_client):
    """Test retrieving previously stored facts from ChromaDB"""
    await test_client.send("What information do you have about Paris and France?")
    response = (test_client.last_agent_response or "").lower()
    assert "paris" in response or "france" in response
    assert "capital" in response or "seine" in response or "eiffel" in response

