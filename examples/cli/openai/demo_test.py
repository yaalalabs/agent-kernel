import pytest
from ak.test import Test


@pytest.mark.asyncio
async def test_demo():
    test = Test("demo.py")
    await test.start()
    await test.send("Who won the 1996 cricket world cup?")
    await test.expect("The 1996 Cricket World Cup was won by Sri Lanka")
    await test.stop()
