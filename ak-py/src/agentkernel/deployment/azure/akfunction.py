import asyncio
import json
import logging
import traceback
from typing import Any
import azure.functions as func
from agentkernel.core.model import AgentReplyImage, AgentReplyText, AgentRequestAny, AgentRequestText
from ...core import AgentService

# logging.basicConfig(
#     level=logging.DEBUG,
#     format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
#     force=True,
# )


class AzureFunctions:
    """
    AzureFunctions class provides an Azure Functions interface for interacting with agents.
    Includes a handler method for Azure Function integration.
    """
    _log = logging.getLogger("ak.azure.functions")
    _log.setLevel(logging.DEBUG)

    @classmethod
    def handler(cls, req: func.HttpRequest) -> func.HttpResponse:
        """
        Azure Functions HTTP handler to process incoming requests.

        """
        cls._log.info("Agent Kernel Agent Azure Function Handler started")
        
        service = None
        session_id = None
        
        try:
            # Initialize service
            cls._log.info("Initializing AgentService")
            service = AgentService()
            cls._log.info(f"AgentService initialized: {service}")
            
            # Parse request body
            try:
                body = req.get_json()
                cls._log.info(f"Request body: {body}")
                
            except ValueError as e:
                cls._log.error(f"Failed to parse JSON: {e}")
                raise ValueError("Invalid JSON in request body")
            
            prompt = body.get("prompt", None)
            agent = body.get("agent", None)
            session_id = body.get("session_id", None)
            
            cls._log.info(f"Parsed - prompt: {prompt}, agent: {agent}, session_id: {session_id}")
            
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
                cls._log.info(f"Adding additional context: {key}={value}")
                requests.append(AgentRequestAny(name=key, content=value))
            
            cls._log.info(f"Selecting agent with session_id: {session_id}, agent: {agent}")
            service.select(session_id, agent)
            
            cls._log.info(f"Service agent after select: {service.agent}")
            if not service.agent:
                raise ValueError("No agent available")
            
            # Run the agent service
            cls._log.info("Running agent service")
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
            
            # Get response session_id
            try:
                response_session_id = service.get_response_session_id(session_id) if service else session_id
            except Exception as e:
                cls._log.error(f"Error getting response session_id: {e}")
                response_session_id = session_id
            
            return func.HttpResponse(
                body=json.dumps(
                    {
                        "result": (
                            str(result)
                            if isinstance(result, (AgentReplyText, AgentReplyImage))
                            else "Non textual result received"
                        ),
                        "session_id": response_session_id,
                    }
                ),
                status_code=200,
                mimetype="application/json"
            )
            
        except ValueError as ve:
            cls._log.error(f"ValueError processing request: {ve}\n{traceback.format_exc()}")
            
            response_session_id = session_id
            if service:
                try:
                    response_session_id = service.get_response_session_id(session_id)
                except Exception as e:
                    cls._log.error(f"Error in get_response_session_id during ValueError handling: {e}")
            
            return func.HttpResponse(
                body=json.dumps(
                    {
                        "error": str(ve),
                        "session_id": response_session_id,
                    }
                ),
                status_code=400,
                mimetype="application/json"
            )
            
        except Exception as e:
            cls._log.error(f"Error processing request: {e}\n{traceback.format_exc()}")
            
            response_session_id = session_id
            if service:
                try:
                    response_session_id = service.get_response_session_id(session_id)
                except Exception as inner_e:
                    cls._log.error(f"Error in get_response_session_id during exception handling: {inner_e}")
            
            return func.HttpResponse(
                body=json.dumps(
                    {
                        "error": str(e),
                        "session_id": response_session_id,
                    }
                ),
                status_code=500,
                mimetype="application/json"
            )