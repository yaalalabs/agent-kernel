import ast
import importlib.util
import pathlib
import re
import shutil

import pytest
import pytest_asyncio
from agentkernel.test import Test

pytestmark = pytest.mark.asyncio(loop_scope="session")  # uses a single session for all tests

HERE = pathlib.Path(__file__).parent
GENERATED = HERE / "bundle" / "generated"


def generated_text() -> str:
    """Everything the producer and curator have written to the bundle so far."""
    return "\n".join(path.read_text() for path in sorted(GENERATED.rglob("*.md")))


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def test_client():
    # An agentkernel without the okf package ignores the config block, so every agent runs with no
    # knowledge-base tools and answers from general knowledge -- which reads as a flaky test rather
    # than a missing install. Fail on the cause instead.
    if importlib.util.find_spec("agentkernel.knowledgebase.okf") is None:
        pytest.fail("The installed agentkernel has no OKF support. Run ./build.sh local first.")

    # Writes from a previous run would otherwise be visible to this one: a stale corrected
    # customers concept changes what the consumer reports about trust.
    shutil.rmtree(GENERATED, ignore_errors=True)

    test = Test("demo.py")
    await test.start()
    try:
        yield test
    finally:
        await test.stop()


async def ask(test_client, agent_name: str, message: str) -> str:
    """Point the CLI at one of the three agents defined in demo.py and send it one message."""
    await test_client.send(f"!select {agent_name}")
    return (await test_client.send(message)).lower()


async def test_demo_imports_nothing_from_the_knowledgebase_package():
    # The point of the example: the whole knowledge-base tier arrives from config.yaml. If this
    # fails, someone has re-wired by hand what the okf block is supposed to provide. Only the
    # import statements are inspected -- demo.py's docstring names these pieces to say they are
    # deliberately absent.
    tree = ast.parse((HERE / "demo.py").read_text())
    modules = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    modules |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    names = {alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) for alias in node.names}

    assert not any(module.startswith("agentkernel.knowledgebase") for module in modules)
    assert not {"KnowledgeBuilder", "OKFManager"} & names


@pytest.mark.order(1)
async def test_consumer_fetches_a_concept_and_answers_from_its_body(test_client):
    # amount_usd appears nowhere but the body of tables/orders.md, and only fetch_kb reads a full
    # body, so naming it proves the agent navigated to the concept rather than guessing.
    response = await ask(
        test_client,
        "kb_consumer_agent",
        "Using the knowledge base, which column of the orders table holds revenue? "
        "Give the exact column name as written in the concept, and the concept path you read it from.",
    )
    assert "amount_usd" in response
    assert "orders.md" in response


@pytest.mark.order(2)
async def test_consumer_reports_the_trust_signal(test_client):
    # customers.md is machine-confirmed, not human-reviewed, so the answer is no. Trust is
    # advisory, never a filter: the concept is returned either way, and the agent is expected to
    # pass the signal on rather than present an unreviewed concept as settled.
    response = await ask(
        test_client,
        "kb_consumer_agent",
        "Using the knowledge base, has a human reviewed the customers table concept? "
        "Begin your answer with exactly Yes or No.",
    )
    assert re.match(r"\W*no\b", response), response


@pytest.mark.order(3)
async def test_consumer_is_refused_a_write(test_client):
    # The consumer never receives write_kb at all, so it cannot attempt the write and should say
    # it has no way to do it. This is the per-(agent, database) permission rule, from the agent's
    # side: same bundle, same tools otherwise, different answer.
    response = await ask(
        test_client,
        "kb_consumer_agent",
        "Add a new concept recording that refunds are processed weekly. If you cannot, say you cannot and why.",
    )
    assert any(
        phrase in response
        for phrase in ("cannot", "can't", "unable", "not able", "read-only", "read only", "don't have", "do not have")
    ), response
    assert "weekly" not in generated_text()


@pytest.mark.order(4)
async def test_producer_writes_a_new_concept_and_reads_it_back(test_client):
    await ask(
        test_client,
        "kb_producer_agent",
        "Record this new fact in the knowledge base now, without asking for confirmation: "
        "the orders table is rebuilt nightly at 02:00 UTC.",
    )
    # The write lands as a real file, which is the deterministic half of the check.
    assert "02:00" in generated_text()

    response = await test_client.send(
        "Search the knowledge base for what you just recorded about the nightly rebuild, and state the time it happens."
    )
    assert "02:00" in response


@pytest.mark.order(5)
async def test_curator_reads_before_it_amends(test_client):
    await ask(
        test_client,
        "kb_curator_agent",
        "Fetch the concept at tables/customers.md, then write a corrected version of it now, without asking for "
        "confirmation, adding that the table also holds a signup_channel column.",
    )
    assert "signup_channel" in generated_text()
