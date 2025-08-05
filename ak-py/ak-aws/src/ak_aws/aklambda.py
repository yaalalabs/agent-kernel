import json
import uuid
import asyncio
from typing import Any, Dict

from ak import Runtime, Session


class Lambda:
    """
    Lambda class provides an AWS Lambda interface for interacting with agents.
    Includes handler method for AWS Lambda function integration.
    """
    _agent: Any = None
    _session: Any = None

    @classmethod
    def _select(cls, name: str | None = None):
        """
        Selects an agent by name, or the first available agent if no name is provided.
        """
        if name:
            selected = Runtime.agents().get(name)
            if selected:
                cls._agent = selected
            else:
                print(f"No agent found with name '{name}'")
        else:
            agents = list(Runtime.agents().values())
            cls._agent = agents[0] if agents else None
            if cls._session is None and cls._agent is not None:
                cls._new()

    @classmethod
    def _new(cls):
        if cls._agent:
            cls._session = Session(str(uuid.uuid4()))
            print(f"Starting new session: {cls._session.id}")
        else:
            print("No agent selected. Please select an agent using !select <agent_name>.")

    @classmethod
    def _load(cls, name: str):
        """
        Loads an agent module by name.
        """
        try:
            Runtime.load(name)
            if not cls._agent:
                cls._select()
        except ImportError as e:
            print(f"No module found with name '{name}': {e}")
            return None

    @classmethod
    async def _run_agent(cls, prompt: str):
        """
        Async method to run the agent.
        """
        return await Runtime.run(cls._agent, cls._session, prompt)

    @classmethod
    def handler(cls, event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        """
        AWS Lambda handler function to process incoming requests.
        """
        print("Agent Kernel Lambda")

        try:
            prompt = json.loads(event.get('body', '{}')).get('prompt', '')
            name = json.loads(event.get('body', '{}')).get('agent', None)

            cls._select(name)
            if not cls._agent:
                print("No agents available. defaulting to first agent in the list")
                cls._select()
                if not cls._agent:
                    print("No agents available. Please load an agent module.")
                    return {
                        'statusCode': 400,
                        'body': json.dumps({'error': 'No agent available'})
                    }

            result = asyncio.run(cls._run_agent(prompt))
            print(f"Result: {result}")
            return {
                'statusCode': 200,
                'body': json.dumps({'result': result})
            }
        except Exception as e:
            return {
                'statusCode': 500,
                'body': json.dumps({'error': str(e)})
            }
