import asyncio
import json
import logging
import traceback
from typing import Any, Dict

from ..core import AgentService

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

    @classmethod
    def handler(cls, event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        """
        AWS Lambda handler function to process incoming requests.
        """
        cls._log.info("Agent Kernel Agent Lambda Handler started")
        service = AgentService()
        try:
            prompt = json.loads(event.get('body', '{}')).get('prompt', '')
            name = json.loads(event.get('body', '{}')).get('agent', None)
            session_id = json.loads(event.get('body', '{}')).get('session_id', None)

            service.select(session_id, name)
            if not service.agent:
                cls._log.info("No agents available. defaulting to first agent in the list")
                service.select(session_id)
                if not service.agent:
                    cls._log.info("No agents available. Please load an agent module.")
                    return {
                        'statusCode': 400,
                        'body': json.dumps(
                            {'error': 'No agent available', 'session_id': service.get_response_session_id(session_id)})
                    }
            try:
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    asyncio.set_event_loop(asyncio.new_event_loop())
                    result = asyncio.run(service.run(prompt))
                else:
                    result = loop.run_until_complete(service.run(prompt))
            except RuntimeError:
                result = asyncio.run(service.run(prompt))

            cls._log.info(f"Result: {result}")

            if hasattr(result, 'raw'):  # Handle CrewAI result
                return {
                    'statusCode': 200,
                    'body': json.dumps(
                        {'result': str(result.raw), 'session_id': service.get_response_session_id(session_id)})
                }

            return {
                'statusCode': 200,
                'body': json.dumps({'result': result, 'session_id': service.get_response_session_id(session_id)})
            }
        except Exception as e:
            cls._log.error(f"Error processing request: {e}\n{traceback.format_exc()}")
            return {
                'statusCode': 500,
                'body': json.dumps({'error': str(e), 'session_id': service.get_response_session_id(None)})
            }
