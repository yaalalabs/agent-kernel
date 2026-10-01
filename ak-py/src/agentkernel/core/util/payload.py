"""
JSON-safe payload handling shared by the reply and stream-event models.

`AgentReplyAny.content` and `DataMessage.content` hold a payload an agent produced and a surface must
serialise. Four encoders reach those values — `__str__`'s `json.dumps(default=str)`, pydantic's JSON
mode, FastAPI's `jsonable_encoder`, and bare `json.dumps` in the queue pipeline — and they disagree
about anything that is not a plain JSON type: a `datetime` renders three ways and crashes the fourth.
Normalising once, where the value is born, makes every surface emit the same bytes.

`PayloadCodec` owns both halves of that guarantee. `normalise` is the validator behind
`JSONPayload`, so it runs on every payload construction; `encode` is what the serialisation gates
call instead of `json.dumps`, so a value that arrived through one of the two bypasses below still
produces those same bytes rather than killing the message.

Two bypasses no validator can close, documented rather than defended against:
`reply.model_copy(update={"content": ...})` and in-place mutation of an already-validated value.
Labelling a reply with `model_copy` is safe because it leaves `content` alone; replacing `content`
means constructing a new reply, or the guarantee is lost for that payload.

`NaN` and the infinities are the one exception to "coerce if you can". Pydantic renders them as
`null`, which is indistinguishable from a field the agent chose to omit, so a client could not tell a
divide-by-zero from a deliberate gap. They raise instead.
"""

import json
import math
from typing import Annotated, Any

from pydantic import BeforeValidator, TypeAdapter


class PayloadCodec:
    """Normalises a payload to plain JSON types, and encodes any response body to JSON.

    One class rather than two helpers because both halves answer the same question — what bytes
    does this value become — and answering it in several places is how the encoders diverged.
    Stateless, so every method is a classmethod.
    """

    _adapter: TypeAdapter = TypeAdapter(Any)

    @classmethod
    def normalise(cls, value: Any) -> Any:
        """
        Replace every non-JSON type in a payload with its canonical JSON form.

        :param value: The payload to normalise; must be a JSON object or array.
        :return: The payload with only `str`, `int`, `float`, `bool`, `None`, `list` and `dict`.
        :raises ValueError: If the payload is not an object or array, holds a `NaN` or an infinity,
            or holds a value with no JSON form at all.
        """
        if not isinstance(value, (dict, list)):
            raise ValueError(f"payload must be a JSON object or array, got {type(value).__name__}")
        cls._require_finite(value)
        try:
            return json.loads(cls._adapter.dump_json(value))
        except Exception as e:
            raise ValueError(f"payload is not JSON-serialisable: {e}") from e

    @classmethod
    def encode(cls, body: Any) -> str:
        """
        Serialise a response body to JSON, coping with values that never passed `normalise`.

        Deliberately two passes rather than one. Pydantic converts whatever bare ``json.dumps``
        would have refused, and ``json.dumps`` then writes it out — so a body that was already
        JSON-safe produces the bytes it produced before this gate existed, down to the spacing. The
        gates run on every queue message and every serverless response, not only on labelled ones,
        and changing their bytes for everybody would be exactly the kind of untargeted change this
        work promises not to make.

        Unlike `normalise` this is lenient: a non-finite float becomes ``null`` here rather than
        raising, because a gate's job is to get the message out, not to re-litigate a payload that
        already passed validation or bypassed it.

        :param body: The response body, usually a dict built by `ResponseBuilder`.
        :return: The JSON text.
        """
        return json.dumps(json.loads(cls._adapter.dump_json(body)))

    @classmethod
    def _require_finite(cls, value: Any, path: str = "content") -> None:
        """
        Raise if a `NaN` or an infinity appears anywhere in `value`, naming where it was found.

        Pydantic renders all three as `null` without complaint, so this check cannot be left to it.

        :param value: The value to walk.
        :param path: The key path reported in the error, built up through the recursion.
        :raises ValueError: On the first non-finite float found.
        """
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(f"{path} is {value!r}; NaN and infinities have no JSON form")
        if isinstance(value, dict):
            for key, item in value.items():
                cls._require_finite(item, f"{path}[{key!r}]")
        elif isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                cls._require_finite(item, f"{path}[{index}]")


JSONPayload = Annotated[dict | list, BeforeValidator(PayloadCodec.normalise)]
"""A payload object or array, normalised to plain JSON types on validation."""
