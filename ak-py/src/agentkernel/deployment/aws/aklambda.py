import asyncio
import json
import logging
import traceback
from typing import Any, Dict

from agentkernel.core.model import AgentReplyImage, AgentReplyText, AgentRequestAny, AgentRequestText

from ...core import AgentService

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    force=True,
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
            body = json.loads(event.get("body", "{}"))
            prompt = body.get("prompt", None)
            agent = body.get("agent", None)
            session_id = body.get("session_id", None)

            if session_id is None:
                raise ValueError("No session_id is provided in the request")

            requests = []
            if prompt:
                requests.append(AgentRequestText(text=prompt))
            else:
                raise ValueError("No prompt provided in the request")

            for key, value in body.items():
                if key in ["prompt", "agent", "session_id"]:
                    continue
                cls._log.info(f"Adding additional context: {key}={value}")
                requests.append(AgentRequestAny(name=key, content=value))

            service.select(session_id, agent)
            if not service.agent:
                raise ValueError("No agent available")
            try:
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    asyncio.set_event_loop(asyncio.new_event_loop())
                    result = asyncio.run(service.run_multi(requests=requests))
                else:
                    result = loop.run_until_complete(service.run_multi(requests=requests))
            except RuntimeError:
                result = asyncio.run(service.run_multi(requests=requests))
            cls._log.debug(f"Result: {result}")

            return {
                "statusCode": 200,
                "body": json.dumps(
                    {
                        "result": (
                            str(result) if isinstance(result, (AgentReplyText, AgentReplyImage)) else "Non textual result received"
                        ),  # sending image is not supported at the moment
                        "session_id": service.get_response_session_id(session_id),
                    }
                ),
            }

        except ValueError as ve:
            cls._log.error(f"ValueError processing request: {ve}\n{traceback.format_exc()}")
            return {
                "statusCode": 400,
                "body": json.dumps(
                    {
                        "error": str(ve),
                        "session_id": service.get_response_session_id(None),
                    }
                ),
            }
        except Exception as e:
            cls._log.error(f"Error processing request: {e}\n{traceback.format_exc()}")
            return {
                "statusCode": 500,
                "body": json.dumps(
                    {
                        "error": str(e),
                        "session_id": service.get_response_session_id(None),
                    }
                ),
            }
