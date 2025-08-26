import asyncio
import json
import logging
import traceback
import uuid
from typing import Any, Dict

from ..core import Runtime, Agent, Session
from ..core.runtime import MemoryType

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    force=True
)


class Lambda:
    """
    Lambda class provides an AWS Lambda interface for interacting with agents.
    Includes a handler method for AWS Lambda function integration.
    """
    _log = logging.getLogger("ak.aws.lambda")
    _agent: Agent | None = None
    _session: Session | None = None
    _runtime: Runtime = Runtime.instance(MemoryType.REDIS)

    @classmethod
    def _select(cls, session_id: str | None, name: str | None = None):
        """
        Selects an agent by name, or the first available agent if no name is provided.
        """
        if name:
            selected = cls._runtime.agents().get(name)
            if selected:
                cls._agent = selected
            else:
                cls._log.warning(f"No agent found with name '{name}'")
        else:
            cls._log.info("No agent was requested. Defaulting to first agent in the list")
            agents = list(cls._runtime.agents().values())
            cls._agent = agents[0] if agents else None
            if cls._agent:
                cls._log.info(f"Selected agent: {cls._agent.name}")
            else:
                cls._log.error("No agents available")

        # Create a session only if an agent is selected
        if cls._agent:
            if session_id is not None:
                cls._old(session_id)
            else:
                cls._new()
        else:
            cls._log.warning("No agent selected. Session was not created.")

    @classmethod
    def _old(cls, session_id: str):
        cls._log.debug(f"Attempting to reuse existing session: {session_id}")
        cls._session = cls._runtime.sessions().load(session_id)

    @classmethod
    def _new(cls):
        session_id = str(uuid.uuid4())
        cls._log.info(f"Starting new session: {session_id}")
        cls._session = cls._runtime.sessions().new(session_id)

    @classmethod
    def _load(cls, session_id: str, name: str):
        """
        Loads an agent module by name.
        """
        try:
            cls._runtime.load(name)
            if not cls._agent:
                cls._select(session_id)
        except ImportError as e:
            cls._log.info(f"No module found with name '{name}': {e}")
            return None

    @classmethod
    async def _run_agent(cls, prompt: str):
        """
        Async method to run the agent.
        """
        result = await cls._runtime.run(cls._agent, cls._session, prompt)
        cls._runtime.sessions().store(cls._session)
        return result

    @classmethod
    def _get_response_session_id(cls, session_id: str | None = None):
        """
        Method will return the session's ID if exists. If not, it will
        return the ID sent by the user. If neither exists, it will return None.
        """
        if cls._session:
            return cls._session.id
        else:
            return session_id

    @classmethod
    def handler(cls, event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        """
        AWS Lambda handler function to process incoming requests.
        """
        cls._log.info("Agent Kernel Agent Lambda Handler started")
        try:
            prompt = json.loads(event.get('body', '{}')).get('prompt', '')
            name = json.loads(event.get('body', '{}')).get('agent', None)
            session_id = json.loads(event.get('body', '{}')).get('session_id', None)

            cls._select(session_id, name)
            if not cls._agent:
                cls._log.info("No agents available. defaulting to first agent in the list")
                cls._select(session_id)
                if not cls._agent:
                    cls._log.info("No agents available. Please load an agent module.")
                    return {
                        'statusCode': 400,
                        'body': json.dumps(
                            {'error': 'No agent available', 'session_id': cls._get_response_session_id(session_id)})
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
                    'body': json.dumps(
                        {'result': str(result.raw), 'session_id': cls._get_response_session_id(session_id)})
                }

            return {
                'statusCode': 200,
                'body': json.dumps({'result': result, 'session_id': cls._get_response_session_id(session_id)})
            }
        except Exception as e:
            cls._log.error(f"Error processing request: {e}\n{traceback.format_exc()}")
            return {
                'statusCode': 500,
                'body': json.dumps({'error': str(e), 'session_id': cls._get_response_session_id(None)})
            }
