import logging
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ValidationError

from ....core.util.async_bridge import run_async_sync
from ....core.util.factory import AKConfigError
from ....identity.errors import AuthenticationError
from ....identity.provider.base import RequestContext
from ....identity.provider.request import RequestAuthenticator


class Headers(BaseModel):
    Authorization: str


class APIGatewayRequestAuthorizerEvent(BaseModel):
    type: str
    methodArn: str
    resource: str | None = None
    path: str | None = None
    httpMethod: str | None = None
    headers: Headers
    pathParameters: dict[str, str] | None = None
    stageVariables: dict[str, str] | None = None


# Given the raw authorizer event, the name of the integration whose route it targets, or None.
WebhookBypass = Callable[[dict[str, Any]], str | None]


class APIGatewayAuthorizer:
    """The API Gateway Lambda authorizer: authenticates the bearer header through the configured identity provider.

    An accepted credential yields an Allow policy whose ``principalId`` is the principal's subject and
    whose context carries the whole principal as JSON (API Gateway context values must be strings), for
    the request-handler Lambda to rebuild onto the request. Anything else is a Deny.
    """

    def __init__(self, bypass: WebhookBypass | None = None):
        """
        :param bypass: Lets messaging-integration routes through without a token, e.g.
            ``WebhookRouteMatcher.for_integrations("slack")``. Platforms send no bearer token; the
            adapter's own signature check in the request-handler Lambda authenticates them. It only
            gets a say with authorizer caching off (``result_ttl_in_seconds = 0``): with a TTL, API
            Gateway answers a header-less request with 401 before calling this Lambda.
        :raises AKConfigError: If no identity provider is configured: an authorizer nobody can
            authenticate to would deny every request.
        """
        self._authenticator = RequestAuthenticator.from_config()
        if self._authenticator.provider is None:
            raise AKConfigError("APIGatewayAuthorizer requires an identity block: it authenticates every request the bypass does not claim")
        self._bypass = bypass
        self._log = logging.getLogger("ak.deployment.aws.akauthorizer")

    def handle(self, event: dict, context: dict = None) -> dict:
        self._log.info(f"Authorizer received event: {event}")
        # Before _build_request: its required Authorization header would Deny a webhook outright.
        policy = self._bypass_policy(event)
        if policy is not None:
            self._log.info(f"Authorizer return policy: {policy}")
            return policy

        try:
            request: APIGatewayRequestAuthorizerEvent = self._build_request(event)
            principal = run_async_sync(
                self._authenticator.authenticate_bearer(
                    request.headers.Authorization,
                    RequestContext(path=request.path, http_method=request.httpMethod, headers=request.headers.model_dump()),
                )
            )
            if principal.is_anonymous:
                # Unreachable with the provider the constructor demanded; denied rather than allowed as "anonymous".
                return_policy = self._build_deny_policy(request.methodArn)
            else:
                return_policy = self._build_policy(
                    principal_id=principal.subject,
                    effect="Allow",
                    method_arn=request.methodArn,
                    context={"principal": principal.model_dump_json()},
                )
        except ValidationError as e:
            # Missing or malformed headers/Authorization
            self._log.info(f"Event validation failed: {e}")
            return_policy = self._build_deny_policy(event.get("methodArn", "*"))
        except AuthenticationError as e:
            # A refused credential, or a header that is not "Bearer <token>": the reason stays in the log.
            self._log.info(f"Refused credential: {e}")
            return_policy = self._build_deny_policy(event.get("methodArn", "*"))
        except Exception as e:
            # Catch-all for unexpected errors during authentication
            self._log.info(f"Unexpected error in authorizer: {e}", exc_info=True)
            return_policy = self._build_deny_policy(event.get("methodArn", "*"))

        self._log.info(f"Authorizer return policy: {return_policy}")
        return return_policy

    def _bypass_policy(self, event: dict) -> dict | None:
        """An Allow for a request the bypass recognises, or None to take the normal path.

        The Allow names the exact ``methodArn`` (never a wildcard) and carries no principal. A bypass
        that raises is logged and falls through to the provider, which fails closed for a request
        with no token.
        """
        if self._bypass is None or not event.get("methodArn"):
            return None
        try:
            matched = self._bypass(event)
        except Exception:
            self._log.warning("Authorizer bypass raised; taking the normal authorization path", exc_info=True)
            return None
        if not matched:
            return None
        principal_id = f"integration:{matched}" if isinstance(matched, str) else "integration"
        return self._build_policy(principal_id=principal_id, effect="Allow", method_arn=event["methodArn"], context=None)

    def _build_request(self, event: dict) -> APIGatewayRequestAuthorizerEvent:
        return APIGatewayRequestAuthorizerEvent.model_validate(event)

    def _build_policy(self, principal_id: str, effect: str, method_arn: str, context: dict[str, Any] | None = None):
        policy = {
            "principalId": principal_id,
            "policyDocument": {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Action": "execute-api:Invoke",
                        "Effect": effect,
                        "Resource": method_arn,
                    }
                ],
            },
        }
        if context:
            # API Gateway requires context values to be strings
            policy["context"] = {k: str(v) for k, v in context.items()}
        return policy

    def _build_deny_policy(self, method_arn: str, principal_id: str = "unauthorized") -> dict:
        """Build a deny policy for failed authorization attempts"""
        return self._build_policy(
            principal_id=principal_id,
            effect="Deny",
            method_arn=method_arn,
            context=None,
        )
