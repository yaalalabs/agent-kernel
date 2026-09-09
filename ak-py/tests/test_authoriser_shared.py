"""Tests for the shared Authoriser base (relocated to agentkernel.auth, #629 Phase 1):
import-path preservation, the AuthValidatorAuthoriser adapter, and the extracted
AuthorisedRESTRequestHandler hierarchy."""

from typing import Optional

from agentkernel.auth import Authoriser, AuthValidatorAuthoriser
from agentkernel.auth.handler import AuthValidator, ValidationContext, ValidationResult


class _StubValidator(AuthValidator):
    """AuthValidator double returning a canned ValidationResult."""

    def __init__(self, result: Optional[ValidationResult]):
        self._result = result

    def validate(self, token: str, context: Optional[ValidationContext] = None) -> ValidationResult:
        return self._result


def test_the_package_export_matches_the_defining_module():
    from agentkernel.auth.authoriser import Authoriser as from_auth_module

    assert Authoriser is from_auth_module


def test_authoriser_is_no_longer_exported_from_the_thread_package():
    """agentkernel.auth is the single import path (#629); the thread package owns
    threads, not shared auth primitives."""
    import agentkernel.integration.thread as thread_package
    import agentkernel.thread as thread_alias

    assert not hasattr(thread_package, "Authoriser")
    assert not hasattr(thread_alias, "Authoriser")


def test_thread_handler_inherits_the_shared_authorised_base():
    from agentkernel.api.handler import AuthorisedRESTRequestHandler
    from agentkernel.integration.thread.thread_chat import ThreadRESTRequestHandler

    assert issubclass(ThreadRESTRequestHandler, AuthorisedRESTRequestHandler)


def test_adapter_is_an_authoriser():
    adapter = AuthValidatorAuthoriser(_StubValidator(ValidationResult(is_valid=True)))
    assert isinstance(adapter, Authoriser)


def test_adapter_resolves_subject_for_a_valid_token():
    adapter = AuthValidatorAuthoriser(_StubValidator(ValidationResult(is_valid=True, subject="user-1")))
    assert adapter.authorise("token") == "user-1"


def test_adapter_uses_the_default_subject_when_unset():
    # ValidationResult.subject defaults to "user"
    adapter = AuthValidatorAuthoriser(_StubValidator(ValidationResult(is_valid=True)))
    assert adapter.authorise("token") == "user"


def test_adapter_rejects_an_invalid_token():
    adapter = AuthValidatorAuthoriser(_StubValidator(ValidationResult(is_valid=False, error_msg="bad")))
    assert adapter.authorise("token") is None


def test_adapter_rejects_a_none_result():
    adapter = AuthValidatorAuthoriser(_StubValidator(None))
    assert adapter.authorise("token") is None
