import json
import logging
import traceback
from urllib.parse import urlsplit

import azure.functions as func

from ...core.chat_service import ChatService
from ...core.model import ChatRunRequest
from ...core.util.async_bridge import run_async_sync
from ...identity.errors import AuthenticationError
from ...identity.provider.base import RequestContext
from ...identity.provider.request import RequestAuthenticator


class AzureFunctions:
    """
    AzureFunctions class provides an Azure Functions interface for interacting with agents.
    Includes a handler method for Azure Function integration. The request's bearer token is
    authenticated through the configured identity provider before the body is read.
    """

    _log = logging.getLogger("ak.azure.functions")
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

        The ``Authorization`` header is authenticated first: a refused or malformed credential is a
        401 before the body is parsed, and the resulting principal (anonymous without a header or an
        ``identity`` block) is assigned to the request, replacing anything the client put there.
        """
        cls._log.info("Agent Kernel Agent Azure Function Handler started")

        # The path only: the URL's query string can carry the function key (``?code=``) under authLevel: function.
        path = urlsplit(req.url).path
        try:
            principal = run_async_sync(
                RequestAuthenticator.from_config().authenticate_bearer(
                    req.headers.get("Authorization"),
                    RequestContext(path=path, http_method=req.method, headers=dict(req.headers)),
                )
            )
        except AuthenticationError as exc:
            cls._log.info(f"Refused credential on {req.method} {path}: {exc}")
            return cls._json_response({"error": exc.public_detail, "session_id": None}, 401)

        try:
            # Parse request body
            try:
                body = req.get_json()
                cls._log.info(f"Request body: {body}")
            except ValueError as e:
                cls._log.error(f"Failed to parse JSON: {e}")
                raise ValueError("Invalid JSON in request body")

            if isinstance(body, dict) and body.get("body") is not None:
                body = ChatRunRequest.model_validate(body["body"])
            elif isinstance(body, dict) and body:
                body = ChatRunRequest.model_validate(body)
            else:
                raise ValueError("Invalid request, request body cannot be empty or null")
            body.principal = principal

            # Process chat request using common service
            status_code, res_body = cls._get_chat_service().process_chat_request(body)
            return cls._json_response(res_body, status_code)

        except ValueError as ve:
            cls._log.error(f"ValueError processing request: {ve}\n{traceback.format_exc()}")
            return cls._json_response({"error": str(ve), "session_id": None}, 400)

        except Exception as e:
            cls._log.error(f"Error processing request: {e}\n{traceback.format_exc()}")
            return cls._json_response({"error": str(e), "session_id": None}, 500)

    @staticmethod
    def _json_response(body: dict, status_code: int) -> func.HttpResponse:
        """Build the JSON response every outcome of ``handler`` is answered with."""
        return func.HttpResponse(body=json.dumps(body), status_code=status_code, mimetype="application/json")
