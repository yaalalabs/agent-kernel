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
    await test_client.send("!select physics")
    # Named after exactly one person; the earlier phrasing ("who discovered energy emission
    # from black holes?") was ambiguous with the Penrose process and drew "Roger Penrose".
    await test_client.send("What is the name of the radiation emitted by black holes?")
    await test_client.expect(["Hawking radiation"])

    await test_client.send("!select geography")
    await test_client.send("What is the prehistoric single continent of which all current continents broke off from?")
    await test_client.expect(["Pangea"])

    # Selecting a non-existent agent is a no-op — the failure is logged (stderr), not printed,
    # so the previously selected 'geography' agent stays active and still answers.
    await test_client.send("!select triage")
    await test_client.send("Which ocean is the largest on Earth?")
    await test_client.expect(["Pacific"])
