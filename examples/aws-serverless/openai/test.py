import pickle
import asyncio

from ak.openai.openai import OpenAISession


async def test_session_add_items():
    # Initialize the session
    ai_session = OpenAISession()

    # Test data
    test_items = [{"content": "a"}, {"content": "b"}, {"content": "c"}]

    # Add items to session
    await ai_session.add_items(test_items)

    dumps = pickle.dumps(ai_session)
    print("=======================================================")
    print(dumps)
    print("=======================================================")

    loads = pickle.loads(dumps)
    print(loads)

    print("=======================================================")


async def main():
    await test_session_add_items()


if __name__ == "__main__":
    asyncio.run(main())
