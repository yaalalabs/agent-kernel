"""The API Gateway Lambda authorizer on the identity provider (#603): the policy's principal and context."""

from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from agentkernel.core.model import Principal
from agentkernel.core.util.factory import AKConfigError
from agentkernel.deployment.aws.serverless.akauthorizer import APIGatewayAuthorizer, APIGatewayRequestAuthorizerEvent
from agentkernel.identity import IdentityProviderFactory, RequestContext

ALICE = Principal(subject="alice", provider="static", namespace="static", groups=["ops"])
METHOD_ARN = "arn:aws:execute-api:us-east-1:123456789012:api/test/prod/POST/api/v1/chat"


def _event(authorization: str | None = "Bearer alice-secret", **overrides) -> dict:
    event = {
        "type": "REQUEST",
        "methodArn": METHOD_ARN,
        "resource": "/api/v1/chat",
        "path": "/api/v1/chat",
        "httpMethod": "POST",
        "headers": {"Content-Type": "application/json"},
    }
    if authorization is not None:
        event["headers"]["Authorization"] = authorization
    event.update(overrides)
    return event


def _statement(policy: dict) -> dict:
    return policy["policyDocument"]["Statement"][0]


class TestAPIGatewayRequestAuthorizerEvent:
    """Tests for APIGatewayRequestAuthorizerEvent model."""

    def test_event_with_all_fields(self):
        event_data = {
            "type": "REQUEST",
            "methodArn": "arn:aws:execute-api:us-east-1:123456789012:api/test/prod/GET/resource",
            "resource": "/resource",
            "path": "/api/v1/chat",
            "httpMethod": "POST",
            "headers": {"Authorization": "Bearer token123", "Content-Type": "application/json"},
            "pathParameters": {"param1": "value1"},
            "stageVariables": {"stage": "prod"},
        }

        event = APIGatewayRequestAuthorizerEvent.model_validate(event_data)

        assert event.type == "REQUEST"
        assert event.methodArn == "arn:aws:execute-api:us-east-1:123456789012:api/test/prod/GET/resource"
        assert event.resource == "/resource"
        assert event.path == "/api/v1/chat"
        assert event.httpMethod == "POST"
        assert event.headers.Authorization == "Bearer token123"
        assert event.pathParameters == {"param1": "value1"}
        assert event.stageVariables == {"stage": "prod"}

    def test_event_with_minimal_fields(self):
        event_data = {
            "type": "REQUEST",
            "methodArn": "arn:aws:execute-api:us-east-1:123456789012:api/test/prod/GET/resource",
            "headers": {"Authorization": "Bearer token123"},
        }

        event = APIGatewayRequestAuthorizerEvent.model_validate(event_data)

        assert event.resource is None
        assert event.path is None
        assert event.httpMethod is None
        assert event.headers.Authorization == "Bearer token123"
        assert event.pathParameters is None
        assert event.stageVariables is None

    @pytest.mark.parametrize("missing", ["type", "methodArn", "headers"])
    def test_event_missing_required_fields(self, missing):
        event_data = {
            "type": "REQUEST",
            "methodArn": "arn:aws:execute-api:us-east-1:123456789012:api/test/prod/GET/resource",
            "headers": {"Authorization": "Bearer token123"},
        }
        del event_data[missing]

        with pytest.raises(ValidationError) as exc_info:
            APIGatewayRequestAuthorizerEvent.model_validate(event_data)

        assert missing in str(exc_info.value)

    def test_event_with_empty_optional_fields(self):
        event = APIGatewayRequestAuthorizerEvent.model_validate(
            {
                "type": "REQUEST",
                "methodArn": "arn:aws:execute-api:us-east-1:123456789012:api/test/prod/GET/resource",
                "headers": {"Authorization": "Bearer token123"},
                "pathParameters": {},
                "stageVariables": {},
            }
        )

        assert event.pathParameters == {}
        assert event.stageVariables == {}

    def test_event_serialization(self):
        event = APIGatewayRequestAuthorizerEvent.model_validate(
            {
                "type": "REQUEST",
                "methodArn": "arn:aws:execute-api:us-east-1:123456789012:api/test/prod/GET/resource",
                "headers": {"Authorization": "Bearer token123"},
            }
        )

        serialized = event.model_dump()

        assert serialized["type"] == "REQUEST"
        assert serialized["headers"]["Authorization"] == "Bearer token123"


class TestConstruction:
    def test_requires_an_identity_block(self, monkeypatch):
        """An authorizer nobody can authenticate to would deny every request: a configuration error at cold start."""
        monkeypatch.setattr(IdentityProviderFactory, "get", classmethod(lambda cls: None))

        with pytest.raises(AKConfigError, match="APIGatewayAuthorizer requires an identity block"):
            APIGatewayAuthorizer()


class TestHandle:
    """Every outcome is a policy: Allow carrying the principal for an accepted credential, Deny for anything else."""

    def test_an_accepted_credential_allows_the_method_as_the_subject(self, static_identity):
        policy = APIGatewayAuthorizer().handle(_event())

        assert policy["principalId"] == "alice"
        assert policy["policyDocument"]["Version"] == "2012-10-17"
        assert _statement(policy) == {"Action": "execute-api:Invoke", "Effect": "Allow", "Resource": METHOD_ARN}

    def test_the_context_carries_the_principal_as_a_json_string(self, static_identity):
        """API Gateway context values must be strings; the one value is the whole principal, groups included."""
        policy = APIGatewayAuthorizer().handle(_event())

        assert list(policy["context"]) == ["principal"]
        assert isinstance(policy["context"]["principal"], str)
        assert Principal.model_validate_json(policy["context"]["principal"]) == ALICE

    def test_a_refused_credential_denies_with_no_context(self, static_identity):
        policy = APIGatewayAuthorizer().handle(_event("Bearer mallory"))

        assert (policy["principalId"], _statement(policy)["Effect"], _statement(policy)["Resource"]) == ("unauthorized", "Deny", METHOD_ARN)
        assert "context" not in policy

    def test_a_header_without_the_bearer_scheme_is_denied(self, static_identity):
        """The shared header parsing applies here too: a bare token is not a credential the provider is asked about."""
        policy = APIGatewayAuthorizer().handle(_event("alice-secret"))

        assert _statement(policy)["Effect"] == "Deny"
        assert static_identity.calls == []

    def test_a_missing_authorization_header_is_denied(self, static_identity):
        policy = APIGatewayAuthorizer().handle(_event(None))

        assert (_statement(policy)["Effect"], _statement(policy)["Resource"]) == ("Deny", METHOD_ARN)
        assert static_identity.calls == []

    def test_an_event_without_a_method_arn_is_denied_everywhere(self, static_identity):
        event = _event()
        del event["methodArn"]

        policy = APIGatewayAuthorizer().handle(event)

        assert (policy["principalId"], _statement(policy)["Effect"], _statement(policy)["Resource"]) == ("unauthorized", "Deny", "*")

    def test_a_provider_failure_is_denied_not_raised(self, static_identity, monkeypatch):
        async def _boom(credential, context=None):
            raise RuntimeError("jwks unreachable")

        monkeypatch.setattr(static_identity, "authenticate", _boom)

        policy = APIGatewayAuthorizer().handle(_event())

        assert (policy["principalId"], _statement(policy)["Effect"]) == ("unauthorized", "Deny")

    def test_the_provider_sees_where_the_credential_was_presented(self, static_identity):
        APIGatewayAuthorizer().handle(_event(path="/users/123/posts/456", httpMethod="GET"))

        ((credential, context),) = static_identity.calls
        assert credential == "alice-secret"
        assert context == RequestContext(path="/users/123/posts/456", http_method="GET", headers={"Authorization": "Bearer alice-secret"})

    def test_the_lambda_context_argument_is_ignored(self, static_identity):
        policy = APIGatewayAuthorizer().handle(_event(), Mock())

        assert policy["principalId"] == "alice"

    @pytest.mark.parametrize("method", ["GET", "POST", "PUT", "DELETE", "PATCH"])
    def test_every_method_is_allowed_on_its_own_arn(self, static_identity, method):
        arn = f"arn:aws:execute-api:us-east-1:123456789012:api/test/prod/{method}/resource"

        policy = APIGatewayAuthorizer().handle(_event(methodArn=arn, httpMethod=method, path="/resource"))

        assert (_statement(policy)["Effect"], _statement(policy)["Resource"]) == ("Allow", arn)


class TestBuildPolicy:
    def test_context_values_are_strings(self, static_identity):
        policy = APIGatewayAuthorizer()._build_policy("alice", "Allow", METHOD_ARN, {"n": 1, "flag": True})

        assert policy["context"] == {"n": "1", "flag": "True"}

    def test_no_context_key_without_context(self, static_identity):
        assert "context" not in APIGatewayAuthorizer()._build_policy("alice", "Deny", METHOD_ARN, None)
