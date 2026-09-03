import pytest
import pytest_asyncio
from agentkernel.test import Test

pytestmark = pytest.mark.asyncio(loop_scope="session")  # uses a single session for all tests


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def test_client():
    test = Test("demo.py", match_threshold=0.1)
    await test.start()
    try:
        yield test
    finally:
        await test.stop()


@pytest.mark.order(1)
async def test_first_question(test_client):
    await test_client.send("Who won the 1996 cricket world cup?, answer with only the country name")
    await test_client.expect(["Sri Lanka"])


@pytest.mark.order(2)
async def test_score_mode_gives_partial_credit(test_client):
    await test_client.send("What is the capital of France? Answer in one word.")
    result = await test_client.expect(["Paris is the capital of France"], return_metrics=True)
    assert result.evaluator == "custom_evaluator.TokenOverlapEvaluator"
    assert result.metric == "jaccard_token_overlap"
    assert 0.0 < result.score < 1.0  # graded, not binary
    assert result.passed


@pytest.mark.order(3)
async def test_llm_mode_uses_the_custom_judge(test_client):
    await test_client.send(
        "Which countries hosted the tournament? Answer with only the country names, listing all of them."
    )
    result = Test.compare(
        actual=test_client.last_agent_response,
        expected=["Sri Lanka, India and Pakistan"],
        user_input=test_client.last_user_input,
        threshold=0.6,
        return_metrics=True,
    )
    assert result.metric == "litellm_raw_judge"
    assert result.passed
