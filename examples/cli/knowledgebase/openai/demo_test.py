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
async def test_first_question(test_client):
    await test_client.send("Who won the 1996 cricket world cup?")
    await test_client.expect(["Sri Lanka won the 1996 cricket world cup."])


@pytest.mark.order(2)
async def test_fallback_when_kb_empty(test_client):
    # Question that is unlikely to be pre-seeded in any local KB, but easy for the base model
    await test_client.send("What is the capital of France?")
    await test_client.expect(["capital of France is Paris"])


@pytest.mark.order(3)
async def test_kb_descriptions_exposed(test_client):
    # The router should expose and understand its configured knowledge bases
    await test_client.send("Which knowledge bases or databases do you use to store information?")
    await test_client.expect(["ChromaDB", "Neo4jDB", "SQLDB"])


@pytest.mark.order(4)
async def test_kb_schemas_available(test_client):
    # The router should be able to describe schemas from get_schemas()
    await test_client.send("Summarize the knowledge base schemas you know about.")
    await test_client.expect(
        [
            "ChromaDB",
            "Neo4jDB",
            "SQLDB",
            "semantic",
            "graph",
            "relational",
        ]
    )
