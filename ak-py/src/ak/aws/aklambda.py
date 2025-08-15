import asyncio
import json
import logging
import traceback
import uuid

from typing import Any, Dict

from ..core import Runtime, Session, Agent

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    force=True
)


class Lambda:
    """
    Lambda class provides an AWS Lambda interface for interacting with agents.
    Includes handler method for AWS Lambda function integration.
    """
    _log = logging.getLogger("ak.aws.lambda")
    _agent: Agent | None = None
    _session: Session | None = None

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
                cls._log.warning(f"No agent found with name '{name}'")
        else:
            cls._log.info("No agent was requested. Defaulting to first agent in the list")
            agents = list(Runtime.agents().values())
            cls._agent = agents[0] if agents else None
            if cls._agent:
                cls._log.info(f"Selected agent: {cls._agent.name}")
            else:
                cls._log.error("No agents available")

        if cls._session is not None:
            cls._log.debug(f"Reusing existing session: {cls._session.id}")
        else:
            cls._new()

    @classmethod
    def _new(cls):
        if cls._agent:
            cls._session = Session(str(uuid.uuid4()))
            cls._log.info(f"Starting new session: {cls._session.id}")
        else:
            cls._log.warning("No agent selected")

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
            cls._log.info(f"No module found with name '{name}': {e}")
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
        cls._log.info("Agent Kernel Agent Lambda Handler started")
        try:
            prompt = json.loads(event.get('body', '{}')).get('prompt', '')
            name = json.loads(event.get('body', '{}')).get('agent', None)

            cls._select(name)
            if not cls._agent:
                cls._log.info("No agents available. defaulting to first agent in the list")
                cls._select()
                if not cls._agent:
                    cls._log.info("No agents available. Please load an agent module.")
                    return {
                        'statusCode': 400,
                        'body': json.dumps({'error': 'No agent available'})
                    }
            try:
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    asyncio.set_event_loop(asyncio.new_event_loop())
                    result = asyncio.run(cls._run_agent(prompt))
                else:
                    result = loop.run_until_complete(cls._run_agent(prompt))
            except RuntimeError:
                result = asyncio.run(cls._run_agent(prompt))

            cls._log.info(f"Result: {result}")

            if hasattr(result, 'raw'):  # Handle CrewAI result
                return {
                    'statusCode': 200,
                    'body': json.dumps({'result': str(result.raw)})
                }

            return {
                'statusCode': 200,
                'body': json.dumps({'result': result})
            }
        except Exception as e:
            cls._log.error(f"Error processing request: {e}\n{traceback.format_exc()}")
            return {
                'statusCode': 500,
                'body': json.dumps({'error': str(e)})
            }
