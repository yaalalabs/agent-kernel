from agentkernel.core.util.error_util import user_facing_error_message


class ErrorWithStatusCode(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


def test_user_facing_error_message_for_503_with_status_attr():
    error = ErrorWithStatusCode(503, "UNAVAILABLE")
    assert user_facing_error_message(error) == "Error: The model is temporarily unavailable (503). Please try again."


def test_user_facing_error_message_for_503_in_message():
    error = Exception("google.genai.errors.ServerError: 503 UNAVAILABLE")
    assert user_facing_error_message(error) == "Error: The model is temporarily unavailable (503). Please try again."


def test_user_facing_error_message_for_high_demand_phrase():
    error = Exception("This model is currently experiencing high demand. Please try again later.")
    assert user_facing_error_message(error) == "Error: The model is temporarily unavailable. Please try again."


def test_user_facing_error_message_falls_back_to_cleaned_message():
    error = Exception("  Something   bad\n happened  ")
    assert user_facing_error_message(error) == "Error: Something bad happened"
