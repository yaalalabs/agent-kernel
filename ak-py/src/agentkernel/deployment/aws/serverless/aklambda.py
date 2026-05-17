from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, Optional

from ....core.config import AKConfig, ExecutionMode
from .core import BaseLambdaRouter, RESTLambdaRouter, WSLambdaRouter


class Lambda:
    """
    Lambda class provides an AWS Lambda interface for interacting with agents.
    Supports both REST API and WebSocket API Gateway events.
    Includes a handler method for AWS Lambda function integration.
    """

    _log = logging.getLogger("ak.aws.lambda")
    _router: Optional[BaseLambdaRouter] = None
    _config: Optional[AKConfig] = None

    @classmethod
    def _get_config(cls) -> AKConfig:
        if cls._config is None:
            cls._config = AKConfig.get()
        return cls._config

    @classmethod
    def _get_router(cls) -> BaseLambdaRouter:
        if cls._router is None:
            cls._router = WSLambdaRouter() if cls._is_websocket_mode() else RESTLambdaRouter()
        return cls._router

    @staticmethod
    def _is_websocket_mode() -> bool:
        return Lambda._get_config().execution.mode == ExecutionMode.ASYNC

    @classmethod
    def register(cls, route: str, method: Optional[str] = None) -> Callable[[Callable], Callable]:
        """
        Class method decorator that delegates route registration to the internal LambdaRouter.

        :param route: URL route for the handler (normalized with leading slash, no trailing slash)
        :param method: HTTP method (defaults to "GET", case-insensitive)
        :return: Decorator function that registers the handler and returns it unchanged
        """
        return cls._get_router().register(route, method)

    @staticmethod
    def _wrap_response(result: Any) -> Dict[str, Any]:
        """
        Normalize various handler return types into API Gateway compatible responses.

        :param result: Handler return value (dict, tuple, str, or list)
        :return: API Gateway compatible response dictionary with statusCode and body
        """
        if isinstance(result, dict) and "statusCode" in result and "body" in result:
            return result  # already well-formed
        if isinstance(result, tuple) and len(result) == 2:
            status, body = result
            if isinstance(body, (dict, list)):
                return {"statusCode": int(status), "body": json.dumps(body)}
            return {"statusCode": int(status), "body": str(body)}
        if isinstance(result, (dict, list)):
            return {"statusCode": 200, "body": json.dumps(result)}
        return {"statusCode": 200, "body": str(result)}

    @classmethod
    def handler(cls, event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        """
        AWS Lambda handler function to process incoming requests.

        :param event: API Gateway event dictionary containing request information
        :param context: AWS Lambda context object
        :return: API Gateway response dictionary with status code and body
        """
        cls._log.info("Agent Kernel Agent Lambda Handler started")
        # Attempting to dispatch to custom routes
        try:
            router = cls._get_router()
            result = router.dispatch(event, context)
            return cls._wrap_response(result)
        except Exception as e:
            # Exception in custom route handler/Lambda function raise 500
            cls._log.exception(f"Custom route handler failed: {e}")
            return {
                "statusCode": 500,
                "body": json.dumps({"error": f"Custom handler error: {e}"}),
            }
