"""Authorizer Lambda: bearer-token auth for the chat route, and a bypass for Slack's webhook.

Slack sends no bearer token: it signs the body, and the authorizer event carries no body. So the
bypass lets `POST /<api_base_path>/<api_version>/slack/events` through by method and path alone,
never by header, and the Slack adapter's signature check in the request-handler Lambda is the real
authentication.

The bypass only gets a say with authorizer caching off (`result_ttl_in_seconds = 0` in
deploy/main.tf): with a TTL, API Gateway answers a request that has no Authorization header with
401 before calling this Lambda.
"""

import hmac
import os
from typing import Optional

from agentkernel.auth import AuthValidator, ValidationContext, ValidationResult
from agentkernel.aws import APIGatewayAuthorizer
from agentkernel.integration.adapter import WebhookRouteMatcher


class DemoValidator(AuthValidator):
    """Accepts one shared demo token. Replace it with your identity provider's token check."""

    def __init__(self) -> None:
        self._token = os.environ["DEMO_AUTH_TOKEN"]

    def validate(self, token: str, context: Optional[ValidationContext] = None) -> ValidationResult:
        return ValidationResult(is_valid=hmac.compare_digest(token, self._token), subject="demo-user")


handler = APIGatewayAuthorizer(validator=DemoValidator(), bypass=WebhookRouteMatcher.for_integrations("slack")).handle
