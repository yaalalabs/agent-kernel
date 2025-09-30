import pytest

from ak.test.test import Test as CliTest


@pytest.mark.asyncio
async def test_cli_tester_prompt_update_and_expect():
    t = CliTest(path="dummy.py", match_threshold=60)
    # Only test prompt and expect logic without a subprocess
    CliTest._update_prompt("agent")
    assert CliTest._get_prompt() == "(agent) >> "

    # Set the last response manually for expect()
    t.latest = "Hello World"
    # Should pass with a reasonable fuzzy threshold when expected is similar
    await t.expect("Hello World!")

    # Now raise a threshold too high to fail
    t.match_threshold = 95
    with pytest.raises(AssertionError):
        await t.expect("Hi there")
