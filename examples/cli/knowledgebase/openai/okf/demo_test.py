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
async def test_kb_descriptions_exposed(test_client):
    await test_client.send("Which knowledge base do you read from? Reply with its name only.")
    await test_client.expect(["OKF"])


@pytest.mark.order(2)
async def test_browse_lists_the_tables_namespace(test_client):
    # browse_kb on a namespace holding an index.md returns that curated listing verbatim, so the
    # reply is a multi-line listing rather than a short answer. expect() scores the whole response
    # against each expected string as an alternative, which a listing never matches, and it could
    # not require both names anyway -- assert on the response directly.
    await test_client.send("Browse the tables namespace and list the concepts it holds.")
    response = (test_client.last_agent_response or "").lower()
    assert "orders" in response
    assert "customers" in response


@pytest.mark.order(3)
async def test_fetch_reads_a_concept_body(test_client):
    # Only fetch_kb reads a full body, so a column that appears nowhere but the body of
    # tables/orders.md is what proves the fetch happened.
    await test_client.send("Fetch the concept at tables/orders.md and name the column that holds the revenue.")
    await test_client.expect(["amount_usd"])


@pytest.mark.order(4)
async def test_search_finds_the_upstream_source(test_client):
    # No curated listing points at datasets/, so this one has to be found by ranking.
    await test_client.send("Where is the orders data loaded from? Name the upstream system.")
    await test_client.expect(["Postgres"])


@pytest.mark.order(5)
async def test_trust_signal_is_reported(test_client):
    # Trust is advisory, never a filter: the concept is returned either way, and the agent is
    # expected to pass the signal on rather than present unverified knowledge as settled.
    await test_client.send("Has the customers table concept been reviewed by a human? Answer yes or no.")
    response = (test_client.last_agent_response or "").lower()
    assert "no" in response
