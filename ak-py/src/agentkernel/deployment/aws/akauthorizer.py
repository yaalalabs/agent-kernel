from typing import Dict, Any, Optional
from pydantic import BaseModel
from ...api.auth.handler import AuthValidator, ValidationContext

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
        self.validator = validator

    def handle(self, event: dict) -> dict:
        request: APIGatewayRequestAuthorizerEvent = self._build_request(event)
        token = self._extract_token(request)

        result = self.validator.validate(
            token=token,
            context=ValidationContext(
                path=request.path,
                http_method=request.httpMethod,
                headers=request.headers.model_dump(),
            )
        )

        if not result.is_valid:
            raise Exception("Unauthorized")

        return self._build_policy(
            principal_id=result.subject or "user",
            effect="Allow",
            method_arn=request.method_arn,
            context=result.claims,
        )

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