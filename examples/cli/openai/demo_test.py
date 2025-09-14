import asyncio

from ak.test import Test


async def test_demo():
    test = Test('demo.py')
    await test.start()
    await test.send("History of Sri Lanka")
    await test.stop()


if __name__ == "__main__":
    asyncio.run(test_demo())
