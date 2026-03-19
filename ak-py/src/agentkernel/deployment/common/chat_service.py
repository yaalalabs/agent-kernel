import asyncio
import logging
from typing import Any, Dict, List

from ...core import AgentService
from ...core.model import AgentReplyImage, AgentReplyText, AgentRequestAny, AgentRequestText


class ChatService:
    """
    Centralized service for processing agent chat requests.
    Used across AWS Lambda, Azure Functions, and SQS consumers.
    """

    def __init__(self):
        self._log = logging.getLogger("ak.deployment.chat_service")
        # self.service = AgentService is done in the process_chat_request() function

    def process_chat_request(self, body: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process agent chat request with common logic.

        :param body: Request body containing prompt, agent, session_id, and optional context
        :return: Response dictionary with result/error and session_id
        """
        try:
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

            # Add additional context from request body
            for key, value in body.items():
                if key in ["prompt", "agent", "session_id"]:
                    continue
                self._log.info(f"Adding additional context: {key}={value}")
                requests.append(AgentRequestAny(name=key, content=value))

            self.service = AgentService()

            self.service.select(session_id, agent)
            if not self.service.agent:
                raise ValueError("No agent available")

            # Run the agent service
            result = self._run_agent_service(requests)
            self._log.debug(f"Result: {result}")

            return {
                "statusCode": 200,
                "result": (
                    str(result)
                    if isinstance(result, (AgentReplyText, AgentReplyImage))
                    else "Non textual result received"
                ),
                "session_id": self.service.get_response_session_id(session_id),
            }

        except ValueError as ve:
            self._log.error(f"ValueError processing request: {ve}")
            return {
                "statusCode": 400,
                "error": str(ve),
                "session_id": self.service.get_response_session_id(None),
            }
        except Exception as e:
            self._log.error(f"Error processing request: {e}")
            return {
                "statusCode": 500,
                "error": str(e),
                "session_id": self.service.get_response_session_id(None),
            }

    def _run_agent_service(self, requests: List[Any]) -> Any:
        """
        Run the agent service with proper event loop handling.

        :param requests: List of agent requests to process
        :return: Agent response result
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                asyncio.set_event_loop(asyncio.new_event_loop())
                return asyncio.run(self.service.run_multi(requests=requests))
            else:
                return loop.run_until_complete(self.service.run_multi(requests=requests))
        except RuntimeError:
            return asyncio.run(self.service.run_multi(requests=requests))
