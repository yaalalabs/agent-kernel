---
sidebar_position: 8
---

# A2UI

[A2UI](https://a2ui.org/) is an open format for an agent that answers with *an interface* rather than
a paragraph. The agent emits JSON describing components — a Card, a Text, a Button — and your client
draws them with its own pre-approved widgets. The agent never sends HTML or JavaScript.

Agent Kernel's part is small and deliberate: **it labels the payload and carries it intact.** It
ships no component catalog, parses nothing, and validates nothing.

## Turning it on

```yaml
a2ui:
  enabled: true
  agents:
    - expenses
```

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `false` | Enable the capability. With it off, nothing runs and no reply is labelled. |
| `agents` | all agents | Agent names whose JSON replies are labelled. |

Naming an agent under `agents` is a **declaration** that it emits A2UI. From there, a reply from that
agent whose body parses as JSON is labelled `application/a2ui+json`; prose, which does not parse, is
left exactly as it is.

## What you write

One thing: the catalog, in your agent's instructions.

```python
agent = Agent(
    name="expenses",
    instructions=f"{MY_INSTRUCTIONS}\n\n{MY_CATALOG}",
)
```

**Why Agent Kernel does not ship one.** A catalog has to match the components your frontend actually
implements. One listing components your client cannot draw is worse than no catalog — the model will
emit them confidently and nothing will render. Agent Kernel cannot know what your frontend can draw,
so the catalog is yours, and so is the prompt built from it.

See [`examples/api/a2ui-openai`](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/api/a2ui-openai)
for a runnable one.

## What a client receives

A UI turn, over REST:

```json
{
  "result": {"version": "v1.0", "createSurface": {"surfaceId": "expense_form", "components": [...]}},
  "media_type": "application/a2ui+json",
  "session_id": "s-91"
}
```

A prose turn — which is most turns:

```json
{"result": "Hi — what would you like to claim for?", "session_id": "s-91"}
```

**The label is the switch.** `result` carries the object when `media_type` is present and the string
it has always carried when it is not, so nothing changes for a client that has not opted in.

## Which surfaces carry it

| Surface | Carries a labelled payload |
|---|---|
| REST | yes |
| WebSocket | yes |
| Async mode | yes |
| Conversation threads | the live reply; stored history is not labelled |
| Streaming / AG-UI | yes, with your own `on_stream_event` hook — see below |
| MCP | yes, as `structuredContent` with the label in `_meta` |
| A2A | not yet; it arrives with the `a2a-sdk` 1.x port |

## Limits worth knowing before you build on it

**It does not reach a streamed run.** The hook runs on `Runtime.run`, and `Runtime.stream` never
calls one — so with `execution.mode: stream` the config block does nothing. Agent Kernel logs a
warning at startup rather than leaving you to discover it. Labelling a streamed payload means
writing an `on_stream_event` hook, which also means holding deltas back until the message ends.

**It does not reach an `output_type` agent.** A reply that is already structured means you handed
the framework a schema, whose shape — your union members, your discriminator — Agent Kernel has
never seen. Such a reply is passed through untouched, so the config block and the `output_type`
route cannot collide: one or the other owns the labelling, never both. On that route, write the
post-hook yourself.

**It does not validate.** A reply that parses is labelled and forwarded, whether or not it is good
A2UI. Your renderer rejects a bad one, which is the right place — it is the only party that knows
which components exist.

**It trusts the declaration.** An agent you named that answers with non-UI JSON gets labelled too.

## Another format

Nothing above is special to A2UI except the one constant. To carry your own format — in-house UI
JSON, Adaptive Cards, a chart schema — write a post-hook that sets `media_type`, and every surface
treats it identically:

```python
class MyFormatPostHook(PostHook):
    async def on_run(self, session, requests, agent, agent_reply):
        if not isinstance(agent_reply, AgentReplyAny):
            return agent_reply
        return agent_reply.model_copy(update={"media_type": "application/vnd.acme.ui+json"})

    def name(self) -> str:
        return "my_format"


OpenAIModule([agent]).post_hook(agent, [MyFormatPostHook()])
```

Label with `model_copy` as above and the payload is untouched. If you need to *replace* `content`,
construct a new `AgentReplyAny` instead — `model_copy` skips field validation, so a replaced payload
would miss the JSON-safety guarantee every surface relies on.
