import logging
from typing import Any, Dict, Optional

from pydantic import BaseModel

from ...api.auth.handler import AuthValidator, ValidationContext, ValidationResult


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


class APIGatewayAuthorizer:
    def __init__(self, validator: AuthValidator):
        self._validator = validator
        self._log = logging.getLogger("ak.deployment.aws.akauthorizer")

    def handle(self, event: dict, context: dict = None) -> dict:
        self._log.info(f"Authorizer received event: {event}")
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
        self._log.info(f"Authorizer return policy: {return_policy}")
        return return_policy

    def _build_request(self, event: dict) -> APIGatewayRequestAuthorizerEvent:
        return APIGatewayRequestAuthorizerEvent.model_validate(event)

    def _extract_token(self, request: APIGatewayRequestAuthorizerEvent) -> str:
        auth_token = request.headers.Authorization
        return auth_token.replace("Bearer ", "").strip()

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
