"""Binary-safe (de)serialization of the broker wire models (spec #503).

Only the ``queue`` flavor and its worker use this codec; the in-process flavors and the
nv_cache registry use python-mode dumps and keep raw ``bytes``. Two wire spots carry binary:
``SandboxResult.output_files[*].content`` (handled by ``SandboxFile``'s JSON-mode base64
serializers on the model itself) and the free-form ``upload_file`` payload ``content``, the
one binary field a JSON-mode model dump cannot see, handled here. ``provider_data`` is not
transformed: a provider whose escape-hatch data should cross the queue must keep it
JSON-serializable.
"""

import base64
import json
from typing import Any, Union

from .base import ExecutionCompletion, ExecutionRequest


class BrokerWireCodec:
    """Stateless codec between the broker wire models and their queue/store JSON forms."""

    _UPLOAD_OPERATION = "upload_file"

    @classmethod
    def encode_request(cls, request: ExecutionRequest) -> str:
        """Serialize a request for the queue: JSON-mode dump with the upload payload base64-encoded."""
        payload = dict(request.payload)
        content = payload.get("content")
        if request.operation == cls._UPLOAD_OPERATION and isinstance(content, (bytes, bytearray)):
            payload["content"] = base64.b64encode(bytes(content)).decode("ascii")
        return json.dumps(request.model_copy(update={"payload": payload}).model_dump(mode="json"))

    @classmethod
    def decode_request(cls, body: str) -> ExecutionRequest:
        """Parse a request from the queue, restoring the upload payload's bytes."""
        request = ExecutionRequest.model_validate(json.loads(body))
        content = request.payload.get("content")
        if request.operation == cls._UPLOAD_OPERATION and isinstance(content, str):
            request.payload["content"] = base64.b64decode(content, validate=True)
        return request

    @staticmethod
    def encode_completion(completion: ExecutionCompletion) -> dict[str, Any]:
        """Dump a completion to the JSON-safe dict stored in the response store and sent on the output queue."""
        return completion.model_dump(mode="json")

    @staticmethod
    def decode_completion(data: Union[str, dict[str, Any]]) -> ExecutionCompletion:
        """Rebuild a completion from its stored form (``SandboxFile`` restores its bytes)."""
        if isinstance(data, str):
            data = json.loads(data)
        return ExecutionCompletion.model_validate(data)
