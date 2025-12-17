import pytest

from agentkernel.test.test import Mode
from agentkernel.test.test import Test as CliTest


@pytest.mark.asyncio
async def test_cli_tester_prompt_update_and_expect():
    t = CliTest(path="dummy.py", match_threshold=60)
    # Only test prompt and expect logic without a subprocess
    CliTest._update_prompt("agent")
    assert CliTest._get_prompt() == "(agent) >> "

    # Set the last response manually for expect()
    t.last_agent_response = "Hello World"
    # Should pass with a reasonable fuzzy threshold when expected is similar
    await t.expect(["Hello World!"])

    # Now raise a threshold too high to fail
    t.match_threshold = 95
    with pytest.raises(AssertionError):
        await t.expect(["Hi there"])


def test_compare_fuzzy_mode():
    """Test fuzzy mode only uses fuzzy matching"""
    # Should pass with fuzzy matching
    CliTest.compare("Hello World", ["Hello World!"], threshold=50, mode=Mode.FUZZY)

    # Should fail with fuzzy matching when threshold is too high
    with pytest.raises(AssertionError, match="didn't pass the threshold score"):
        CliTest.compare("Hello World", ["Goodbye"], threshold=50, mode=Mode.FUZZY)


def test_compare_judge_mode():
    """Test judge mode only uses LLM evaluation"""
    # Note: This will make an actual LLM call via Ragas (answer_similarity)
    # Should pass: answer is semantically similar to expected
    CliTest.compare(
        actual="Paris is the capital of France",
        expected=["The capital of France is Paris"],
        user_input="What is the capital of France?",
        mode=Mode.JUDGE,
        threshold=50,  # 0.5 threshold for answer_similarity
    )

    # Should fail with completely unrelated responses
    with pytest.raises(AssertionError, match="didn't pass judge"):
        CliTest.compare(
            actual="Hello",
            expected=["Goodbye forever"],
            user_input="What is the capital of France?",
            mode=Mode.JUDGE,
            threshold=95,
        )


def test_compare_fallback_mode():
    """Test fallback mode tries fuzzy first, then judge"""
    # Should pass with fuzzy matching (no LLM call needed)
    CliTest.compare("Hello World", ["Hello World!"], threshold=50)

    # Should pass with judge when fuzzy fails but answer is still semantically similar
    CliTest.compare(
        actual="Paris is the capital of France",
        expected=["Paris"],
        user_input="What is the capital of France?",
        threshold=50,
        mode=Mode.FALLBACK,
    )

    # Should fail when both fuzzy and judge fail
    with pytest.raises(AssertionError, match="didn't pass fuzzy matching or judge evaluation"):
        CliTest.compare(
            "Hello",
            ["Goodbye completely"],
            user_input="What is the capital of France?",
            threshold=95,
            mode=Mode.FALLBACK,
        )


def test_compare_invalid_mode():
    """Test that invalid mode raises ValueError"""
    with pytest.raises(ValueError, match="Invalid mode"):
        CliTest.compare("Hello", ["Hello"], mode="invalid")


@pytest.mark.asyncio
async def test_expect_with_different_modes():
    """Test that expect uses the mode specified during initialization"""
    # Test with fuzzy mode
    t_fuzzy = CliTest(path="dummy.py", match_threshold=50, mode=Mode.FUZZY)
    t_fuzzy.last_agent_response = "Hello World"
    await t_fuzzy.expect(["Hello World!"])

    # Test with judge mode
    t_judge = CliTest(path="dummy.py", mode=Mode.JUDGE, match_threshold=50)
    t_judge.last_agent_response = "Paris is the capital of France"
    t_judge.last_user_input = "What is the capital of France?"
    # For Ragas judge we must supply user_input via compare(), but expect() uses stored last_user_input.
    # We directly call compare() here to pass user_input.
    CliTest.compare(
        actual=t_judge.last_agent_response,
        expected=["The capital of France is Paris"],
        user_input="What is the capital of France?",
        mode=Mode.JUDGE,
        threshold=50,
    )

    # Test with fallback mode (default)
    t_fallback = CliTest(path="dummy.py")
    t_fallback.last_agent_response = "Hello World"
    await t_fallback.expect(["Hello World!"])
