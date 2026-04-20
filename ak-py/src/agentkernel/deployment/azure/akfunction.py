import json
import logging
import traceback

import azure.functions as func

from ..common.chat_service import ChatService


class AzureFunctions:
    """
    AzureFunctions class provides an Azure Functions interface for interacting with agents.
    Includes a handler method for Azure Function integration.
    """

    _log = logging.getLogger("ak.azure.functions")
    _log.setLevel(logging.DEBUG)
    _chat_service = None

    @classmethod
    def _get_chat_service(cls) -> ChatService:
        if cls._chat_service is None:
            cls._chat_service = ChatService()
        return cls._chat_service
    
    @classmethod
    def handler(cls, req: func.HttpRequest) -> func.HttpResponse:
        """
        Azure Functions HTTP handler to process incoming requests.
        """
        cls._log.info("Agent Kernel Agent Azure Function Handler started")
        

        try:
            # Parse request body
            try:
                body = req.get_json()
                cls._log.info(f"Request body: {body}")
            except ValueError as e:
                cls._log.error(f"Failed to parse JSON: {e}")
                raise ValueError("Invalid JSON in request body")

            if isinstance(body, dict) and body.get("body") is not None:
                body = body["body"]

            # Process chat request using common service
            status_code, res_body = cls._get_chat_service().process_chat_request(body)

            return func.HttpResponse(
                body=json.dumps(res_body),
                status_code=status_code,
                mimetype="application/json",
            )

        except ValueError as ve:
            cls._log.error(f"ValueError processing request: {ve}\n{traceback.format_exc()}")
            return func.HttpResponse(
                body=json.dumps(
                    {
                        "error": str(ve),
                        "session_id": None,
                    }
                ),
                status_code=400,
                mimetype="application/json",
            )

        except Exception as e:
            cls._log.error(f"Error processing request: {e}\n{traceback.format_exc()}")
            return func.HttpResponse(
                body=json.dumps(
                    {
                        "error": str(e),
                        "session_id": None,
                    }
                ),
                status_code=500,
                mimetype="application/json",
            )
