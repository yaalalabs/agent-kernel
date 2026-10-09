"""Where the built-in webhook platforms deliver (#760).

Deliberately free of FastAPI and platform SDKs: the Lambda authorizer imports it through
WebhookRouteMatcher, and must not pay for the adapter modules.
"""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Optional


@dataclass(frozen=True)
class WebhookRoute:
    """One integration's delivery routes: POST on webhook_path, and GET on challenge_path when set."""

    name: str
    webhook_path: str
    challenge_path: Optional[str] = None


# The only definition of the built-in paths: the six adapters read their path attributes from it,
# and WebhookRouteMatcher.for_integrations lets the same routes past the authorizer.
BUILTIN_WEBHOOK_ROUTES: Mapping[str, WebhookRoute] = MappingProxyType(
    {
        route.name: route
        for route in (
            WebhookRoute("slack", "/slack/events"),
            WebhookRoute("teams", "/teams/messages"),
            WebhookRoute("telegram", "/telegram/webhook"),
            WebhookRoute("whatsapp", "/whatsapp/webhook", challenge_path="/whatsapp/webhook"),
            WebhookRoute("messenger", "/messenger/webhook", challenge_path="/messenger/webhook"),
            WebhookRoute("instagram", "/instagram/webhook", challenge_path="/instagram/webhook"),
        )
    }
)
