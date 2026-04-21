class ErrorCategory:
    RATE_LIMIT = "rate_limit"
    SERVER = "server"
    CONNECTION = "connection"
    AUTH = "auth"
    NOT_FOUND = "not_found"
    UNKNOWN = "unknown"


class ErrorUtil:
    @staticmethod
    def _get_status_code(error: Exception) -> int | None:
        """Extracts HTTP status code from error attributes if they exist."""
        for attr in ["status_code", "code", "status"]:
            val = getattr(error, attr, None)
            if isinstance(val, int):
                return val
            if isinstance(val, str) and val.isdigit():
                return int(val)
        return None

    @staticmethod
    def _classify(error: Exception, status_code: int | None) -> str:
        """Categorizes the error based on code, name, or message content."""
        error_name = error.__class__.__name__.lower()
        message = str(error).lower()

        if status_code == 429:
            return ErrorCategory.RATE_LIMIT

        if status_code in [500, 502, 503, 504]:
            return ErrorCategory.SERVER

        if "timeout" in error_name or "connection" in error_name:
            return ErrorCategory.CONNECTION

        if "auth" in error_name or "unauthorized" in error_name:
            return ErrorCategory.AUTH

        if any(k in error_name for k in ["notfound", "invalid", "badrequest"]):
            return ErrorCategory.NOT_FOUND

        if any(t in message for t in ["overloaded", "temporarily unavailable", "high demand"]):
            return ErrorCategory.SERVER

        return ErrorCategory.UNKNOWN

    @staticmethod
    def _format_error_message(error: Exception) -> str:
        """Returns a clean string for the UI based on the error category."""
        status_code = ErrorUtil._get_status_code(error)
        category = ErrorUtil._classify(error, status_code)

        if category == ErrorCategory.RATE_LIMIT:
            return "Error: Too many requests. Please try again later."

        if category == ErrorCategory.SERVER:
            return "Error: The service is temporarily unavailable. Please try again."

        if category == ErrorCategory.CONNECTION:
            return "Error: Could not connect to the model provider. Please check your internet."

        if category == ErrorCategory.AUTH:
            return "Error: Invalid API configuration or credentials."

        if category == ErrorCategory.NOT_FOUND:
            return "Error: Invalid model or resource not found. Please check your configuration."

        message = " ".join(str(error).split()).strip()
        if message:
            return f"Error: {message}"

        return f"An unexpected error occurred: {error.__class__.__name__}"


def user_facing_error_message(error: Exception) -> str:
    return ErrorUtil._format_error_message(error)
