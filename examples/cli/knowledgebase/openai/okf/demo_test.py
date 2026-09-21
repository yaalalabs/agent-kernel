import ast
import pathlib

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


async def select(test_client, agent_name: str) -> None:
    """Point the CLI at one of the three agents defined in demo.py."""
    await test_client.send(f"!select {agent_name}")


async def test_demo_imports_nothing_from_the_knowledgebase_package():
    # The point of the example: the whole knowledge-base tier arrives from config.yaml. If this
    # fails, someone has re-wired by hand what the okf block is supposed to provide. Only the
    # import statements are inspected -- demo.py's docstring names these pieces to say they are
    # deliberately absent.
    tree = ast.parse(pathlib.Path(__file__).with_name("demo.py").read_text())
    modules = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    modules |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    names = {alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) for alias in node.names}

    assert not any(module.startswith("agentkernel.knowledgebase") for module in modules)
    assert not {"KnowledgeBuilder", "OKFManager"} & names


@pytest.mark.order(1)
async def test_consumer_browses_and_answers_citing_a_concept_path(test_client):
    # Only fetch_kb reads a full body, so a column that appears nowhere but the body of
    # tables/orders.md is what proves the agent navigated to it.
    await select(test_client, "kb_consumer_agent")
    await test_client.send(
        "Could you please provide the concept definition of the 'orders' table within the data warehouse schema? Additionally, could you specify the name of the column that holds the revenue?"
    )
    await test_client.expect(["amount_usd"])


@pytest.mark.order(2)
async def test_consumer_reports_the_trust_signal(test_client):
    # customers.md is machine-confirmed, not human-reviewed, so the answer is no. Trust is
    # advisory, never a filter: the concept is returned either way, and the agent is expected to
    # pass the signal on rather than present an unreviewed concept as settled.
    await select(test_client, "kb_consumer_agent")
    await test_client.send("Has the customers table concept been reviewed by a human? Answer yes or no.")
    response = (test_client.last_agent_response or "").lower()
    assert "no" in response


@pytest.mark.order(3)
async def test_consumer_is_refused_a_write(test_client):
    # The consumer never receives write_kb at all, so it cannot attempt the write and should say
    # it has no way to do it. This is the per-(agent, database) permission rule, from the agent's
    # side: same bundle, same tools otherwise, different answer.
    await select(test_client, "kb_consumer_agent")
    await test_client.send(
        "Add a new concept recording that refunds are processed weekly. If you cannot, say you cannot and why."
    )
    response = (test_client.last_agent_response or "").lower()
    assert any(phrase in response for phrase in ("cannot", "can't", "unable", "read-only", "read only", "no ability"))


@pytest.mark.order(4)
async def test_producer_writes_a_new_concept_and_reads_it_back(test_client):
    await select(test_client, "kb_producer_agent")
    await test_client.send(
        "Update knowledge: the orders table is rebuilt nightly at 02:00 UTC. Update the knowledge base accordingly."
    )
    await test_client.send(
        "Search the knowledge base for what you just recorded about the nightly rebuild, and state the time it happens."
    )
    await test_client.expect(["02:00"])


@pytest.mark.order(5)
async def test_curator_reads_before_it_amends(test_client):
    await select(test_client, "kb_curator_agent")
    await test_client.send(
        "Review the concept at tables/customers.md, then record a corrected version noting it also holds the signup channel."
    )
    response = (test_client.last_agent_response or "").lower()
    assert "customers" in response
