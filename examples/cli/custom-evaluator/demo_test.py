import pytest
import pytest_asyncio
from agentkernel.test import Mode, Test

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
    # Uses test-config.yaml's `mode: fallback`, routed through the custom evaluator below.
    await test_client.send("Who won the 1996 cricket world cup?")
    await test_client.expect(["Sri Lanka won the 1996 cricket world cup."])


@pytest.mark.order(2)
async def test_score_mode_gives_partial_credit(test_client):
    # TokenOverlapEvaluator.score_based_evaluation is graded (Jaccard overlap), unlike the
    # built-in deepeval evaluator's binary whole-string match.
    await test_client.send("What is the capital of France?")
    result = Test.compare(
        actual=test_client.last_agent_response,
        expected=["Paris is the capital of France."],
        threshold=0.3,
        mode=Mode.SCORE,
        return_metrics=True,
    )
    assert result.evaluator == "custom_evaluator.TokenOverlapEvaluator"
    assert result.metric == "jaccard_token_overlap"
    assert result.passed


@pytest.mark.order(3)
async def test_llm_mode_uses_the_custom_judge(test_client):
    # TokenOverlapEvaluator.llm_based_evaluation makes a raw litellm.completion() call with its
    # own rubric prompt - no GEval, no DeepEval dependency at all.
    await test_client.send("Which country hosted the 1996 cricket world cup?")
    result = await test_client.expect(
        ["The tournament was co-hosted by India, Pakistan and Sri Lanka."],
        return_metrics=True,
    )
    assert result.metric in ("jaccard_token_overlap", "litellm_raw_judge")
    assert result.passed
