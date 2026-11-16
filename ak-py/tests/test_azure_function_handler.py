"""The Azure Functions handler is a public chat entry point, so it parses ChatRunRequest (#884):
a client cannot set the fields only internal producers use.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

func = pytest.importorskip("azure.functions")

from agentkernel.deployment.azure.akfunction import AzureFunctions  # noqa: E402


def _request(payload: dict) -> "func.HttpRequest":
    return func.HttpRequest(method="POST", url="/api/chat", body=json.dumps(payload).encode())


@pytest.fixture
def chat_service():
    service = MagicMock()
    service.process_chat_request.return_value = (200, {"result": "ok", "session_id": "s1"})
    with patch.object(AzureFunctions, "_get_chat_service", return_value=service):
        yield service


def _wrap(body: dict, nested: bool) -> dict:
    return {"body": body} if nested else body


@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize("field, value", [("requests", [{"type": "text", "prompt": "x"}]), ("scheduled_task_id", "t1")])
def test_an_internal_field_is_rejected_with_400(chat_service, nested, field, value):
    response = AzureFunctions.handler(_request(_wrap({"prompt": "hi", "session_id": "s1", field: value}, nested)))

    assert response.status_code == 400
    assert field in json.loads(response.get_body())["error"]
    chat_service.process_chat_request.assert_not_called()


@pytest.mark.parametrize("nested", [False, True])
def test_an_ordinary_body_reaches_the_chat_service(chat_service, nested):
    response = AzureFunctions.handler(_request(_wrap({"prompt": "hi", "session_id": "s1", "requests": None}, nested)))

    assert response.status_code == 200
    [body] = chat_service.process_chat_request.call_args.args
    assert (body.prompt, body.session_id, body.requests) == ("hi", "s1", None)
