from agentkernel.core.util.error_util import user_facing_error_message


class ErrorWithStatusCode(Exception):
    def __init__(self, status_code: int, message: str = ""):
        super().__init__(message)
        self.status_code = status_code


class ErrorWithStringCode(Exception):
    def __init__(self, code: str, message: str = ""):
        super().__init__(message)
        self.code = code


class AuthenticationError(Exception):
    pass


class BadRequestError(Exception):
    pass


class TimeoutError(Exception):
    pass


class SilentError(Exception):
    def __str__(self):
        return ""


def test_user_facing_error_message_for_503_status():
    error = ErrorWithStatusCode(503, "Unavailable")
    assert user_facing_error_message(error) == "Error: The service is temporarily unavailable. Please try again."


def test_user_facing_error_message_for_429_string():
    error = ErrorWithStringCode("429", "Too Many Requests")
    assert user_facing_error_message(error) == "Error: Too many requests. Please try again later."


def test_user_facing_error_message_for_auth_class():
    error = AuthenticationError("Secret Key Invalid")
    assert user_facing_error_message(error) == "Error: Invalid API configuration or credentials."


def test_user_facing_error_message_for_timeout():
    error = TimeoutError("Request timed out")
    assert user_facing_error_message(error) == "Error: Could not connect to the model provider. Please check your internet."


def test_user_facing_error_message_for_bad_request_cli_case():
    error = BadRequestError("model gpt-4o-mdasda not found")
    assert user_facing_error_message(error) == "Error: Invalid model or resource not found. Please check your configuration."


def test_user_facing_error_message_fallback_cleanup():
    error = Exception("   Unexpected    system \n failure  ")
    assert user_facing_error_message(error) == "Error: Unexpected system failure"


def test_user_facing_error_message_ultimate_fallback():
    error = SilentError()
    assert user_facing_error_message(error) == "An unexpected error occurred: SilentError"
