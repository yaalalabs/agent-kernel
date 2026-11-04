import logging
from typing import Any, Callable, Dict, Optional

from pydantic import BaseModel, ValidationError

from ....auth.handler import AuthValidator, ValidationContext, ValidationResult


class Headers(BaseModel):
    Authorization: str


class APIGatewayRequestAuthorizerEvent(BaseModel):
    type: str
    methodArn: str
    resource: Optional[str] = None
    path: Optional[str] = None
    httpMethod: Optional[str] = None
    headers: Headers
    pathParameters: Optional[Dict[str, str]] = None
    stageVariables: Optional[Dict[str, str]] = None


# Given the raw authorizer event, the name of the integration whose route it targets, or None.
WebhookBypass = Callable[[Dict[str, Any]], Optional[str]]


class APIGatewayAuthorizer:
    def __init__(self, validator: AuthValidator, bypass: Optional[WebhookBypass] = None):
        """
        :param validator: Validates the bearer token of every request the bypass does not claim.
        :param bypass: Lets messaging-integration routes through without a token, e.g.
            ``WebhookRouteMatcher.for_integrations("slack")``. Platforms send no bearer token; the
            adapter's own signature check in the request-handler Lambda authenticates them. It only
            gets a say with authorizer caching off (``result_ttl_in_seconds = 0``): with a TTL, API
            Gateway answers a header-less request with 401 before calling this Lambda.
        """
        self._validator = validator
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
            token = self._extract_token(request)
            result: ValidationResult = self._validator.validate(
                token=token,
                context=ValidationContext(
                    path=request.path,
                    http_method=request.httpMethod,
                    headers=request.headers.model_dump(),
                ),
            )
            return_policy = self._build_policy(
                principal_id=result.subject,
                effect="Allow" if result.is_valid else "Deny",
                method_arn=request.methodArn,
                context=result.claims,
            )
        except ValidationError as e:
            # Missing or malformed headers/Authorization
            self._log.info(f"Event validation failed: {e}")
            return_policy = self._build_deny_policy(event.get("methodArn", "*"))
        except ValueError as e:
            # Token extraction failed
            self._log.info(f"Token extraction failed: {e}")
            return_policy = self._build_deny_policy(event.get("methodArn", "*"))
        except Exception as e:
            # Catch-all for unexpected errors during validation
            self._log.info(f"Unexpected error in authorizer: {e}", exc_info=True)
            return_policy = self._build_deny_policy(event.get("methodArn", "*"))

        self._log.info(f"Authorizer return policy: {return_policy}")
        return return_policy

    def _bypass_policy(self, event: dict) -> Optional[dict]:
        """An Allow for a request the bypass recognises, or None to take the normal path.

        The Allow names the exact ``methodArn`` (never a wildcard) and carries no claims. A bypass
        that raises is logged and falls through to the validator, which fails closed for a request
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

    def _extract_token(self, request: APIGatewayRequestAuthorizerEvent) -> str:
        auth_token = request.headers.Authorization
        token = auth_token.replace("Bearer ", "").strip()
        if not token:
            raise ValueError("Bearer token is empty")
        return token

    def _build_policy(self, principal_id: str, effect: str, method_arn: str, context: Dict[str, Any] | None = None):
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
