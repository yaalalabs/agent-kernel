# What a DataPart is, and how A2UI rides one

Supporting note for [`../design.md`](../design.md) piece 4. It answers one question: when the design
says *"A2A has a data part for structured content and Agent Kernel always sends a text part"*, what
is actually different on the wire, and what does a client do with it.

Everything below was **executed**, not read from documentation. The JSON blocks are real output from
`a2a-sdk 0.3.6` — the version the capped pin resolves to — unless marked otherwise. Protocol claims
about A2UI come from [a2ui.org](https://a2ui.org/) as of September 2026.

---

## 1. A2A messages are made of parts

An A2A message is not a string. It is an envelope with a list of **parts**, and each part declares
its own `kind`:

| `kind` | Type | Carries |
|---|---|---|
| `text` | `TextPart` | a string |
| `file` | `FilePart` | bytes or a URI, with a `mimeType` |
| `data` | `DataPart` | **a JSON object** |

A message can mix them — prose in one part, a structured payload in the next. That is the whole
point of the design: the protocol already has a slot for "here is an object", and Agent Kernel has
never used it.

`DataPart` has exactly three fields (verified against 0.3.6):

```
DataPart.data      dict[str, Any]              the payload
DataPart.kind      Literal["data"]             the discriminator
DataPart.metadata  dict[str, Any] | None       free-form, per-part
```

**Note what is missing: there is no `mimeType` field.** `FilePart` has one; `DataPart` does not. That
matters in §3.

## 2. Today: everything is a text part

`api/a2a/a2a.py:49` calls `new_agent_text_message(str(response), ...)` for every reply. So a
structured reply — already a dict inside Agent Kernel — is stringified and posted as prose:

```json
{
  "contextId": "ctx-42",
  "kind": "message",
  "messageId": "a7c655a9-a118-4a90-a4ac-58517095c073",
  "parts": [
    {
      "kind": "text",
      "text": "{\"version\": \"v1.0\", \"createSurface\": {\"surfaceId\": \"s1\"}}"
    }
  ],
  "role": "agent",
  "taskId": "task-7"
}
```

Look at the escaping. The JSON is *inside* a string, in a part typed `text`.

**Why this is a protocol-level loss, not an encoding nuisance.** An A2A client library hands you a
`TextPart` here. Its `text` is a string, and nothing on the wire says that string is JSON, let alone
what kind. A client that renders UI is looking for a `DataPart`; it finds a text part, renders a
paragraph of escaped JSON, and is correct to do so. This is the difference between "works" and
"doesn't" — not polish.

## 3. After: a labelled reply becomes a data part

```json
{
  "contextId": "ctx-42",
  "kind": "message",
  "messageId": "2211cd13-e7ce-4455-8baa-ab8062fb0e89",
  "parts": [
    {
      "data": {
        "version": "v1.0",
        "createSurface": {
          "surfaceId": "expense_form",
          "components": ["..."]
        }
      },
      "kind": "data",
      "metadata": {
        "mimeType": "application/a2ui+json"
      }
    }
  ],
  "role": "agent",
  "taskId": "task-7"
}
```

Three things changed and each one earns its place:

1. **`kind` is `data`.** A client's part-type switch now routes this to its structured branch.
2. **`data` is an object.** No escaping, no second parse.
3. **`metadata.mimeType` says what the object is.** Without it the client has a JSON blob of unknown
   shape.

The code that produces it is three lines, verified working on 0.3.6:

```python
from a2a.types import DataPart, Part
from a2a.utils import new_agent_parts_message

new_agent_parts_message(
    [Part(root=DataPart(data=reply.content, metadata={"mimeType": reply.media_type}))],
    context_id, task_id)
```

**Why the label lives in `metadata`, and why the key is `mimeType`.** `DataPart` has no `mimeType`
field (§1), so metadata is the only place it can go — and A2A documents `metadata` as exactly this:
free-form per-part metadata that extensions may give meaning to. A2UI's own **A2A extension spec**
then names the key. Its example:

```json
{
  "data":     { "beginRendering": { "surfaceId": "outlier_stores_map_surface" } },
  "kind":     "data",
  "metadata": { "mimeType": "application/json+a2ui" }
}
```

So `mimeType` is not a name Agent Kernel chose. Inventing one — `media_type`, say — would leave the
payload unlabelled as far as a conformant client is concerned, because it would be looking for
`mimeType` and finding nothing.

> **Two caveats on that example, both live.** It is the **v0.8** binding, the only one published —
> `v0.9.1-a2a-extension` and `v1.0-a2a-extension` both 404. Its message key `beginRendering` was
> replaced by `createSurface` in v0.9, and its mime string `application/json+a2ui` is the form
> a2ui.org's v1.0 changelog says the protocol is moving *away* from, toward
> `application/a2ui+json`. The design takes the newer string (Decision 11) and accepts that a client
> written against the v0.8 binding will look for the other one.

## 4. The agent card has to advertise it

A part is only half the story. An A2A client reads the **agent card** first, and the card is where a
server declares which extensions it speaks. Without a declaration a conformant client has no reason
to expect a data part at all.

`AgentCapabilities.extensions` is A2A's slot for this, and `AgentExtension` carries
`uri` / `description` / `params` / `required`. Real output, with the declaration in place:

```json
{
  "capabilities": {
    "extensions": [
      {
        "description": "Replies may carry A2UI documents in a DataPart",
        "required": false,
        "uri": "https://a2ui.org/a2a-extension/a2ui/v0.8"
      }
    ],
    "streaming": false
  },
  "defaultInputModes": ["text"],
  "defaultOutputModes": ["json"],
  "description": "Files expense claims",
  "name": "expenses",
  "preferredTransport": "HTTP+JSON",
  "protocolVersion": "0.3.0",
  "skills": [
    { "description": "File a claim", "id": "file_expense", "name": "file_expense", "tags": [] }
  ],
  "url": "http://localhost:8000/a2a/expenses",
  "version": "0.9.2"
}
```

`required: false` is deliberate: a client that ignores the extension still gets valid A2A, because
`DataPart` is a core protocol type rather than something the extension introduces. The extension
only says what the bytes *mean*.

Note `"defaultOutputModes": ["json"]` — the card already claims this today (`core/builder.py:44`)
while the executor only ever sends text. **The card is currently inaccurate**; this work makes an
existing claim true rather than adding a new one.

**Unverified:** A2A also has an extension *activation* flow, where a client opts in per request. The
design sends a data part whenever a reply is labelled, regardless of activation. That is believed
fine — `DataPart` is core A2A, not extension-gated — but it has not been checked against the spec.

## 5. What the round trip looks like

```
agent returns a dict
   → the a2ui hook labels it            (application/a2ui+json)
   → A2A's executor sees media_type set
   → new_agent_parts_message([DataPart(data=…, metadata={"mimeType": …})])
   → client reads the card, sees the A2UI extension
   → client switches on part.kind == "data"
   → client reads metadata.mimeType, recognises A2UI
   → client renders part.data with its own components
```

Every step before the fourth already exists. The design adds the fourth and the extension
declaration; the rest is the client's.

## 6. This changes shape again at the 1.x port

Recorded here because it is the same subject, and because the port is a separate issue that will
need it.

**a2a-sdk 1.x replaced the pydantic types with protobuf.** Verified on 1.1.2:

```
>>> from a2a.helpers import new_data_message
>>> type(new_data_message({"version": "v1.0"}, media_type="application/a2ui+json", ...))
a2a_pb2.Message                 # no model_dump()
```

```
message_id: "f7d70260-…"
context_id: "c1"
task_id: "t1"
role: ROLE_AGENT
parts {
  data { struct_value { fields { key: "version" value { string_value: "v1.0" } } } }
  media_type: "application/a2ui+json"        ← a first-class field, not metadata
}
```

Two consequences:

- **The label moves.** `DataPart.metadata["mimeType"]` on 0.3.x becomes a `media_type` field on the
  part in 1.x. A client reading the label has to change — a breaking change, though there are none
  today because A2A has never sent a data part.
- **The card's shape moves too.** `AgentCard.url` and `AgentCard.preferred_transport` do not exist
  in 1.x; they are replaced by `supported_interfaces` (an `AgentInterface` of
  `url` / `protocol_binding` / `tenant` / `protocol_version`). Building today's card verbatim against
  1.x raises `ValueError: Protocol message AgentCard has no "url" field`.

So the port is an object-model migration across `core/builder.py`, `api/a2a/handler.py` and
`api/a2a/a2a.py` — roughly 60–90 lines on a 185-line surface — rather than the three renamed imports
the design first assumed. The five framework adapters are unaffected: `AgentSkill(id, name,
description, tags)` constructs unchanged on 1.x, verified.
