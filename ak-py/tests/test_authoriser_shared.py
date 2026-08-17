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


def test_all_import_paths_resolve_to_the_same_class():
    from agentkernel.auth.authoriser import Authoriser as from_auth_module
    from agentkernel.integration.thread import Authoriser as from_thread_package
    from agentkernel.integration.thread.authoriser import Authoriser as from_thread_shim
    from agentkernel.thread import Authoriser as from_thread_alias

    assert Authoriser is from_auth_module
    assert Authoriser is from_thread_shim
    assert Authoriser is from_thread_package
    assert Authoriser is from_thread_alias


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
