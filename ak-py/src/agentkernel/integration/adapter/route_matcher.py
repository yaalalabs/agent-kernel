import logging
import os
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from ...core.util.factory import AKConfigError
from .routes import BUILTIN_WEBHOOK_ROUTES, WebhookRoute


class WebhookRouteMatcher:
    """The APIGatewayAuthorizer bypass for messaging-integration routes (#760 Q1).

    Matches an authorizer event's method and path, and nothing else. The event has no body, so no
    signature can be checked here, and a header test could be spoofed onto a chat request. The
    adapter's verify, in the request-handler Lambda, stays the real check.

    Imports only the route table, never an adapter module, so the authorizer Lambda loads neither
    FastAPI nor any platform SDK. It keeps no state across calls and is safe to share.
    """

    _log = logging.getLogger("ak.integration.route_matcher")

    def __init__(self, routes: Iterable[WebhookRoute], base_path: Optional[str] = None):
        """
        :param routes: The routes to let through: POST on each webhook_path, GET on each challenge_path.
        :param base_path: The prefix API Gateway serves them under, e.g. "/api/v1". None derives it from
            API_BASE_PATH and API_VERSION, which the ak-serverless module sets on the authorizer Lambda.
        """
        self._base_path = base_path if base_path is not None else self._base_path_from_env()
        self._routes: Dict[Tuple[str, str], str] = {}
        for route in routes:
            self._routes[("POST", self._normalize(route.webhook_path))] = route.name
            if route.challenge_path:
                self._routes[("GET", self._normalize(route.challenge_path))] = route.name

    @classmethod
    def for_integrations(cls, *names: str, base_path: Optional[str] = None) -> "WebhookRouteMatcher":
        """A matcher for built-in integrations, by name: for_integrations("slack", "whatsapp").

        :param names: Built-in integration names.
        :param base_path: See the constructor.
        :return: A matcher for those integrations' routes.
        :raises ValueError: If no name is given.
        :raises AKConfigError: If a name is not a built-in.
        """
        if not names:
            raise ValueError("WebhookRouteMatcher.for_integrations needs at least one integration name")
        unknown = [name for name in names if name not in BUILTIN_WEBHOOK_ROUTES]
        if unknown:
            raise AKConfigError(
                f"no built-in webhook integration named {', '.join(unknown)}; the built-ins are {sorted(BUILTIN_WEBHOOK_ROUTES)}. "
                "For a bring-your-own adapter, pass its routes: WebhookRouteMatcher([WebhookRoute(name, webhook_path)])"
            )
        return cls([BUILTIN_WEBHOOK_ROUTES[name] for name in names], base_path=base_path)

    def __call__(self, event: Mapping[str, Any]) -> Optional[str]:
        """The name of the integration whose route this authorizer event targets, else None.

        Mirrors RESTLambdaRouter.dispatch: the method upper-cased, the base path removed with
        ``str.removeprefix``, and the rest looked up exactly. No header or query parameter is read.
        """
        method = str(event.get("httpMethod") or "").upper()
        path = str(event.get("path") or "").removeprefix(self._base_path)
        return self._routes.get((method, path))

    @staticmethod
    def _base_path_from_env() -> str:
        """``/<API_BASE_PATH>/<API_VERSION>``, the prefix BaseLambdaRouter._get_base_paths_from_env strips.

        Derived here rather than imported, because ``integration/`` must not import ``deployment/``.
        With either variable unset it is "", so the gateway path keeps its prefix, matches nothing,
        and the request goes to the validator: the matcher fails closed.
        """
        api_base_path = os.getenv("API_BASE_PATH")
        api_version = os.getenv("API_VERSION")
        return f"/{api_base_path}/{api_version}" if api_base_path and api_version else ""

    @staticmethod
    def _normalize(path: str) -> str:
        """A leading ``/`` and no trailing ``/``, the rule BaseLambdaRouter applies to registered routes."""
        if not path.startswith("/"):
            path = "/" + path
        if len(path) > 1 and path.endswith("/"):
            path = path[:-1]
        return path
