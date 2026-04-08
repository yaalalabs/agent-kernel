import re


def _extract_status_code(error: Exception, message: str) -> int | None:
    status_code = getattr(error, "status_code", None)
    if isinstance(status_code, int):
        return status_code

    match = re.search(r"\b([45]\d{2})\b", message)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None
    return None


def user_facing_error_message(error: Exception) -> str:
    """
    Normalize framework/model exceptions into concise, single-line user messages.
    """
    message = " ".join(str(error).split()).strip()
    status_code = _extract_status_code(error, message)

    if status_code in {500, 502, 503, 504}:
        return f"Error: The model is temporarily unavailable ({status_code}). Please try again."

    if status_code == 429:
        return "Error: Rate limited by the model provider (429). Please try again."

    lowered = message.lower()
    if any(token in lowered for token in ["temporarily unavailable", "high demand", "overloaded", "service unavailable"]):
        return "Error: The model is temporarily unavailable. Please try again."

    if message:
        return f"Error: {message}"

    return "Error: Agent execution failed due to an unexpected runtime error."
