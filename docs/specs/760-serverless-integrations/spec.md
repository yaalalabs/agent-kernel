# #760: Messaging integrations on AWS Lambda: deliver replies and receive webhooks — Implementation Spec

This spec explains **how** to build what [`design.md`](design.md) asks for. Part 1 moves the
pipeline's integration-delivery code into one shared class, `IntegrationDelivery`, which the two
serverless queue consumers now call too. Part 2 adds `LambdaWebhookHost`. It serves the existing
`WebhookRESTRequestHandler` through a thin event ⇄ Starlette translator, from routes the
application registers with `Lambda.register`, and the authorizer lets integration routes through
by path and method. Terraform, packaging, one
example, and the docs close the remaining gaps.

> Base: `develop` @ `71c2943b`. Every `path:line` below was checked against it. Paths are relative
> to `ak-py/src/agentkernel/` unless they start with `ak-py/`, `ak-deployment/`, `docs/`,
> `examples/` or `.agents/`. Unqualified Terraform paths are under `ak-deployment/ak-aws/serverless/`.
> Third-party citations are to the locked versions: fastapi 0.141.1, starlette 1.6.0,
> slack-bolt 1.22.0, slack-sdk 3.44.0.

**`design.md` was corrected while this spec was written.** Each item below is now in `design.md`
and needs its re-review:

1. **Q4 is dropped** (the requester's call). `SlackInboundAdapter.parse` already drops a timeout
   retry before it is acknowledged (`integration/slack/adapter.py:73-79`), so there is no
   `InboundAdapter.is_retry` and no change to `WebhookRESTRequestHandler.handle`.
2. **Q5 is larger** (the requester's call). The `slack` extra also gains `aiohttp`, and
   `agentkernel.api` exports lazily so that the webhook host does not import `uvicorn`.
3. **`bypass` returns the matched integration's name, or `None`,** not a `bool`: the Allow's
   principal `integration:<name>` needs the name.
4. **Only four adapters override `missing_verification_settings`.** Slack and Teams already refuse
   to construct without their secrets.
5. **The parity tests' Slack and Teams deliveries are HTTP-level.** Their contract hooks bypass the
   SDK dispatch.
6. **`IntegrationDelivery`'s unit tests get their own file**, because the class lives in `pipeline/`.
7. **The authorizer's base-path variables are merged at this stack's module call,** not in
   `ak-aws/common`, which is consumed from a registry pin.
8. **The design left route naming to this spec.** It is settled below as one route table.
9. **Stale citations were fixed** (`pipeline/response_handler.py`, `test_aws_lazy_exports.py`,
   `telegram/adapter.py`).
10. **A fourth Terraform gap: the request handler needs the output queue URL too.**
    `WebhookRESTRequestHandler` builds the pipeline `SQSTransport` at construction, which requires
    both URLs, and the request handler gets only the input one (§14, item 3).

**What changes, at a glance**

| File | Kind of change |
|---|---|
| `pipeline/integration_delivery.py` | **New.** `IntegrationDelivery` |
| `pipeline/response_handler.py`, `pipeline/agent_runner.py` | Refactor onto `IntegrationDelivery`, no behaviour change |
| `deployment/aws/serverless/akagentrunner.py` | Fix: pass `requests`, forward the return address, route integration messages off the stream path |
| `deployment/aws/serverless/akresponsehandler.py` | Fix: integration branch first; fix the permanent-failure `KeyError` |
| `integration/adapter/routes.py` | **New.** `WebhookRoute` and the built-in route table |
| `integration/adapter/route_matcher.py` | **New.** `WebhookRouteMatcher` |
| `integration/adapter/base.py`, `webhook.py`, `__init__.py`, `testing.py` | `missing_verification_settings`, `WebhookRESTRequestHandler.adapter`, two lazy exports, one contract test |
| `integration/{slack,teams,telegram,whatsapp,messenger,instagram}/adapter.py` | Paths read from the route table; four `missing_verification_settings` overrides |
| `deployment/aws/serverless/core/event_translator.py` | **New.** `LambdaEventTranslator` |
| `deployment/aws/serverless/core/webhook_host.py` | **New.** `LambdaWebhookHost`, `LambdaWebhookGuard` |
| `deployment/aws/__init__.py` | `LambdaWebhookHost` lazy export (so `agentkernel.aws` has it) |
| `deployment/aws/serverless/akauthorizer.py` | `bypass` |
| `api/__init__.py` | PEP 562 lazy exports |
| `ak-py/pyproject.toml`, `ak-py/uv.lock` | `fastapi` in six extras, `aiohttp` in `slack` |
| `state.tf`, `modules/request-handler/{main,variables}.tf` (serverless) | Multimodal table and output queue URL at the edge; base path on the authorizer |
| `examples/aws-serverless/slack-openai/` | **New** example |
| `ak-py/tests/…` | Seven new files, two edited (see [Testing](#testing)) |

Unchanged: `AKConfig`, ECS, `Lambda` (`aklambda.py`), the Terraform variables, and every public
export apart from `LambdaWebhookHost` in `agentkernel.aws` and the two additions in
`agentkernel.integration.adapter`.

---

## Design

### Part 1: reply delivery

#### 1. `IntegrationDelivery` (new: `pipeline/integration_delivery.py`)

**Its job:** it knows an integration message's return address, and how to deliver a reply or an
error to that address. Nothing else.

**Why `pipeline/`:** the pipeline's `ResponseHandler` needs it. `pipeline/` may not import
`deployment/`, nor `integration/` at module scope (architecture coupling rule 2), while
`deployment/` may import `pipeline/`. So it sits where both can reach it.

**Imports at module scope:** only `logging`, `typing`, `core.model.AgentReplyText`,
`core.util.async_bridge.run_async_sync`, and the `pipeline.envelope` constants. `OutboundAdapter`
is imported under `TYPE_CHECKING` for the return annotation, as `IOHandler` does for
`PollerRunner` (`pipeline/io_handler.py:17-18`). `IntegrationAdapterFactory` is imported inside
`_outbound_adapter`, as today (`pipeline/response_handler.py:161`).

**Not exported** from `agentkernel.pipeline`. It is an internal building block shared by two
consumers. Exporting it later is additive.

```python
class IntegrationDelivery:
    """Integration traffic's return address, and delivery of a reply back to its platform (#524 §6, #760)."""

    def __init__(self, logger: logging.Logger) -> None:
        self._log = logger  # the caller's logger: log lines keep their logger name

    # -- return address ------------------------------------------------------------------
    @staticmethod
    def integration_of(attributes: Mapping[str, Any]) -> Optional[str]:
        """The adapter name when this is integration traffic, else None. Only a non-empty str counts."""

    @staticmethod
    def is_routing_attribute(name: str) -> bool:
        """True for `integration` and every `reply_`-prefixed name."""

    @classmethod
    def routing_attributes(cls, attributes: Mapping[str, Any]) -> Dict[str, str]:
        """The return-address subset of an input message's attributes, values as str; {} for other traffic."""

    @staticmethod
    def reply_context(attributes: Mapping[str, Any]) -> Dict[str, str]:
        """`reply_*` with the prefix removed: what OutboundAdapter.deliver() reads."""

    # -- delivery -----------------------------------------------------------------------
    def deliver(self, integration: str, attributes: Mapping[str, Any], body: Any,
                status_code: int, session_id: Optional[str] = None) -> None: ...

    def deliver_permanent_failure(self, integration: str, attributes: Mapping[str, Any],
                                  session_id: Optional[str] = None) -> None: ...

    @staticmethod
    def _outbound_adapter(integration: str) -> "OutboundAdapter":
        from ..integration.adapter.factory import IntegrationAdapterFactory  # lazy: keeps SDKs out
        return IntegrationAdapterFactory.create_outbound(integration)
```

**`integration_of` accepts only a non-empty `str`.** `test_akagentrunner_stream.py` replaces the
whole `SQSHandler` with a `MagicMock`, whose `.get()` returns a truthy mock. Accepting any truthy
value would send every stream message down the non-streaming path.

**How `deliver` works.** This is the body of `ResponseHandler._deliver_integration`
(`pipeline/response_handler.py:170-193`), moved as it is. Two differences, both without an
observable effect:
- the caller now parses the body and the status (see §2);
- a `None` body is treated as `{}`. Only a Lambda record with no body can hit that; the pipeline
  caller already turns an empty body into `{}`.

1. Resolve `adapter = self._outbound_adapter(integration)`. `AKConfigError` and `ImportError`
   propagate to the caller.
2. Build `reply_context = self.reply_context(attributes)`, and read
   `request_id = attributes.get(ATTR_REQUEST_ID)`.
3. Normalise the body: `None` becomes `{}`, and a non-dict body becomes `{"result": body}`.
4. If `status_code >= 400`:
   - log at ERROR, with the same text as today:
     `[OUTPUT ERROR] integration=…, session_id=…, request_id=…, status_code=…, error={body.get('error')}`
   - then `run_async_sync(adapter.deliver_error(adapter.ERROR_MESSAGE, reply_context))`, and return.
5. Otherwise, `run_async_sync(adapter.deliver(AgentReplyText(response=str(body.get("result", ""))), reply_context))`,
   then log at INFO: `[OUTPUT DONE] Delivered to {integration}: session_id=…, request_id=…`.

It catches nothing. A raised exception is how both hosts get their retries.

**How `deliver_permanent_failure` works:**
- `run_async_sync(adapter.deliver_error(adapter.ERROR_MESSAGE, self.reply_context(attributes)))`
- then the INFO line `Delivered permanent-failure message to {integration}: session_id=…`, the same
  text as `pipeline/response_handler.py:84`.
- It raises on failure. Both callers already wrap permanent-failure handling in a catch-all `try`.

**Rules:**
1. **No per-message state on the instance.** It holds only the logger. Adapters are factory-cached
   and shared (`integration/adapter/factory.py:23-40`).
2. **The caller parses the status.** The pipeline parses strictly (`int(...)`, as at `:183`). The
   serverless handler keeps its tolerant `_resolve_status_code`, where an absent or unparseable
   status means 200 (`deployment/aws/serverless/akresponsehandler.py:71-85`).
3. **No attribute-name collisions.** The routing names are `integration` and `reply_*`. The
   serverless output also carries `request_id`, `user_id`, `status_code` and `endpoint_url`, none of
   which match, so `build_message_attributes`' duplicate check (`pipeline/transport/sqs.py:88-107`)
   cannot trip.

#### 2. Pipeline refactor: no behaviour change

**`pipeline/response_handler.py`**
- **`__init__`:** add `self._integration_delivery = IntegrationDelivery(self._log)`. It is built
  eagerly, because one instance serves every `ConsumerLoop` thread (`:132-143`), so there is no
  lazy-init race.
- **`process` (`:52-57`):**
  ```python
  integration = IntegrationDelivery.integration_of(message.attributes)
  if integration:
      body = json.loads(message.body) if message.body else {}
      status_code = int(message.attributes.get(ATTR_STATUS_CODE, "200"))  # strict, as today
      self._integration_delivery.deliver(integration, message.attributes, body, status_code, session_id=message.group_id)
      return
  ```
  - **The order of work changes, the outcome does not.** Today the adapter is resolved before the
    body and status are parsed (`:177-183`); now it is resolved after.
  - So a message that is both unresolvable and malformed raises `JSONDecodeError`/`ValueError`
    instead of `AKConfigError`. Either way it is retried and ends in `on_permanent_failure`. No
    existing test combines the two faults.
- **`on_permanent_failure` (`:80-85`):** the integration branch becomes
  `self._integration_delivery.deliver_permanent_failure(integration, message.attributes, session_id=message.group_id)`,
  then `return`, inside the existing `try`.
- **Deleted:** `_outbound_adapter` (`:147-163`), `_reply_context` (`:165-168`) and
  `_deliver_integration` (`:170-193`). No test patches them.
- **Imports removed** because they become unused: `AgentReplyText`, `run_async_sync`,
  `REPLY_CONTEXT_PREFIX`, `ATTR_INTEGRATION`. `ATTR_STATUS_CODE` stays.

**`pipeline/agent_runner.py`**
- `_FORWARDED_ATTRIBUTES` (`:27`) becomes `(ATTR_REQUEST_ID, ATTR_USER_ID, ATTR_ENDPOINT_URL)`.
  `_is_forwarded` (`:30-32`) returns
  `key in _FORWARDED_ATTRIBUTES or IntegrationDelivery.is_routing_attribute(key)`, so the forwarded
  set is exactly today's. The comment above it gains one line saying the integration half is the
  shared rule.
- `StreamAgentRunner.process`/`on_permanent_failure` (`:213`, `:242`): `message.attributes.get(ATTR_INTEGRATION)`
  becomes `IntegrationDelivery.integration_of(message.attributes)`.
- The `_record_thread_reply` docstring (`:127-128`) now cites `IntegrationDelivery._outbound_adapter`
  as the lazy-import precedent.
- Imports: `REPLY_CONTEXT_PREFIX` and `ATTR_INTEGRATION` are dropped; `IntegrationDelivery` is added.

#### 3. `ServerlessAgentRunner` (`deployment/aws/serverless/akagentrunner.py`)

Module-scope import: `from ....pipeline.integration_delivery import IntegrationDelivery`. The four
overridable method signatures stay the same.

| Method | Change |
|---|---|
| `process_message` (`:172`) | `process_chat_request(req=body, requests=body.requests)`. With `requests=None`, plain REST traffic behaves as today |
| `_get_record_attributes` (`:89-97`) | After the existing `endpoint_url` block, add `record_attributes["routing_attributes"] = IntegrationDelivery.routing_attributes(message_attributes)`. The existing keys keep their order |
| `_send_to_output_queue` (`:127-135`) | After `endpoint_url` and `status_code`, append one string `SQSHandler.CustomAttribute` per entry of `record_attributes.get("routing_attributes", {})`. The `.get` keeps dicts built by subclasses working |
| `on_permanent_failure` (`:178-200`) | No code change. It already goes through `_get_record_attributes` (`:188`) and `_send_to_output_queue`, so its 500 reply now carries the return address |

- The `Extracted record attributes: …` INFO line now shows the routing attributes too. That
  exposes nothing new: `process_message` already logs the whole record at INFO (`:167`).
- The docstring of `_get_record_attributes` gains a line describing `routing_attributes`.

#### 4. `ServerlessStreamAgentRunner` (same file)

- **`process_message` (`:323-347`):** the first statement becomes
  ```python
  if IntegrationDelivery.integration_of(SQSHandler.get_message_custom_attributes(record)):
      # A platform has no streaming consumer: one reply (pipeline parity, pipeline/agent_runner.py:213).
      return ServerlessAgentRunner.process_message(record)
  ```
  The call names the class explicitly, because this class is a sibling of
  `ServerlessAgentRunner`, not a subclass (`:13`, `:203`).
- **`on_permanent_failure` (`:349-376`):** gets the same guard, delegating to
  `ServerlessAgentRunner.on_permanent_failure(record)`. The guard sits **before** this method's
  own `_get_record_attributes`, which would raise over the missing `endpoint_url` (`:269-270`).
- **The WebSocket path passes the prebuilt list:** `process_stream_chat_sync(req=body, requests=body.requests)`
  (`:339`). Everything else on that path is unchanged: `_get_record_attributes` with its
  `endpoint_url` requirement, `_send_chunk_to_output_queue`, and the dedup suffixes.
- **Why the guard is in this class,** and not only behind `ServerlessAgentRunner.handle`'s mode
  dispatch (`:30-31`): the docs tell STREAM deployments to wire `ServerlessStreamAgentRunner.handle`
  directly (`docs/docs/deployment/aws-serverless.md:547`).

#### 5. Serverless `ResponseHandler` (`deployment/aws/serverless/akresponsehandler.py`)

Module-scope import: `from ....pipeline.integration_delivery import IntegrationDelivery`.
`AKConfig` stays a module-scope import, because `ak-py/tests/test_akresponsehandler.py:84` patches
`…akresponsehandler.AKConfig`.

**New private helpers**
```python
_integration_delivery: Optional[IntegrationDelivery] = None

@classmethod
def _get_integration_delivery(cls) -> IntegrationDelivery:   # same lazy shape as _get_response_store (:30-34)
    if cls._integration_delivery is None:
        cls._integration_delivery = IntegrationDelivery(cls._log)
    return cls._integration_delivery

@staticmethod
def _decode_body(value: Any) -> Any:
    """JSON-decode a record body when it is a string; anything else passes through unchanged."""
    return json.loads(value) if isinstance(value, str) else value
```
`_construct_message_for_store` (`:54-56`) becomes
`message_body = cls._decode_body(body if body is not None else record.get("body"))`. The semantics
are identical: the decode still applies to whichever source was chosen, and a malformed body still
raises `JSONDecodeError`.

**`process_message` (`:116-136`):** the integration branch comes first; the ASYNC, STREAM and
store branches are unchanged, byte for byte.
```python
message_attributes = SQSHandler.get_message_custom_attributes(record)
integration = IntegrationDelivery.integration_of(message_attributes)
if integration:
    cls._get_integration_delivery().deliver(
        integration, message_attributes, cls._decode_body(record.get("body")),
        status_code=cls._resolve_status_code(message_attributes),                  # tolerant parse
        session_id=SQSHandler.get_message_system_attributes(record).get("MessageGroupId"),
    )
    return
```

**`on_permanent_failure` (`:138-207`):** only the start of the `try` changes.
```python
try:
    message_attributes = SQSHandler.get_message_custom_attributes(record)
    session_id = SQSHandler.get_message_system_attributes(record).get("MessageGroupId")   # was :153 (KeyError)

    integration = IntegrationDelivery.integration_of(message_attributes)
    if integration:
        cls._get_integration_delivery().deliver_permanent_failure(integration, message_attributes, session_id=session_id)
        return

    error_message = {...}              # unchanged (:154-157)
    if session_id:
        error_message["session_id"] = session_id   # once, before the branches
    ...                                # ASYNC / STREAM / store branches unchanged, except that the
                                       # ASYNC branch drops its own assignment (:167)
except Exception as e:                 # unchanged (:205-207): never re-raised
```
- `session_id` may be `None` for a record with no group id, and every branch already copes with
  that. On FIFO queues it is always present.
- The REST record gets its session id through the payload: `_construct_message_for_store` reads
  `body["session_id"]` (`:57`). Without the assignment above, the REST branch would store
  `session_id: None`. This matches the pipeline (`pipeline/response_handler.py:93-94`, `:107-108`,
  `:116-117`) and ECS (`deployment/aws/containerized/akoutputconsumer.py:100-106`).

### Part 2: receiving webhooks

#### 6. Built-in webhook routes (new: `integration/adapter/routes.py`)

The design asks for built-in route names that cannot drift between the adapters and the authorizer.
**One table is the only definition,** and both sides read it.

```python
"""Where the built-in webhook platforms deliver (#760).

Deliberately free of FastAPI and platform SDKs: the Lambda authorizer imports it through
WebhookRouteMatcher, and must not pay for the adapter modules.
"""

@dataclass(frozen=True)
class WebhookRoute:
    """One integration's delivery routes: POST on webhook_path, and GET on challenge_path when set."""
    name: str
    webhook_path: str
    challenge_path: Optional[str] = None


BUILTIN_WEBHOOK_ROUTES: Mapping[str, WebhookRoute] = MappingProxyType({route.name: route for route in (
    WebhookRoute("slack", "/slack/events"),
    WebhookRoute("teams", "/teams/messages"),
    WebhookRoute("telegram", "/telegram/webhook"),
    WebhookRoute("whatsapp", "/whatsapp/webhook", challenge_path="/whatsapp/webhook"),
    WebhookRoute("messenger", "/messenger/webhook", challenge_path="/messenger/webhook"),
    WebhookRoute("instagram", "/instagram/webhook", challenge_path="/instagram/webhook"),
)})
```

- Each value is copied from today's adapter attribute, so no path changes: `slack/adapter.py:42`,
  `teams/adapter.py:126`, `telegram/adapter.py:104`, `whatsapp/adapter.py:17`,
  `messenger/adapter.py:15`, `instagram/adapter.py:19`.
- The adapters read the table instead of spelling the path:
  - Slack, Teams and Telegram: `webhook_path = BUILTIN_WEBHOOK_ROUTES[NAME].webhook_path`
  - WhatsApp, Messenger and Instagram: `WEBHOOK_PATH = BUILTIN_WEBHOOK_ROUTES[NAME].webhook_path`
    (the module constant stays, since `NAME` is defined just above it), and
    `challenge_path = BUILTIN_WEBHOOK_ROUTES[NAME].challenge_path`
- `WebhookRoute` is a frozen dataclass, the `InboundParseResult` precedent (`integration/adapter/base.py:64`).
  `BUILTIN_WEBHOOK_ROUTES` is read-only data, not an export: bring-your-own routes are built with
  `WebhookRoute` directly.
- **A contract test guards the table**, for adapters that hard-code a path again or subclass one:
  `IntegrationAdapterContract.test_a_builtin_is_served_where_the_authorizer_expects`. For a webhook
  adapter whose `name` is in `BUILTIN_WEBHOOK_ROUTES`, it asserts that `webhook_path` and
  `challenge_path` equal the table's. It skips every other adapter, so bring-your-own contract
  subclasses are unaffected.

#### 7. `InboundAdapter` and `WebhookRESTRequestHandler` additions

**`InboundAdapter.missing_verification_settings(self) -> List[str]`** (`integration/adapter/base.py`),
concrete, returns `[]`:
```python
def missing_verification_settings(self) -> List[str]:
    """Settings without which this adapter accepts deliveries it cannot authenticate.

    LambdaWebhookHost refuses to serve an adapter that returns any, because behind the API Gateway
    authorizer's integration bypass the adapter's own check is the only one. Empty by default,
    so bring-your-own adapters stay servable.

    :return: The unset settings, named as the user sets them (e.g. "whatsapp.app_secret").
    """
    return []
```

| Adapter | Override returns | Reads | Why |
|---|---|---|---|
| `WhatsAppInboundAdapter` | `["whatsapp.app_secret"]` when empty | `self._client.app_secret` | No secret, no check (`integration/adapter/meta.py:30-31`) |
| `MessengerInboundAdapter` | `["messenger.app_secret"]` | `self._app_secret` (`messenger/adapter.py:46`) | Same |
| `InstagramInboundAdapter` | `["instagram.app_secret"]` | `self._app_secret` (`instagram/adapter.py:49`) | Same |
| `TelegramInboundAdapter` | `["telegram.webhook_secret"]` | `self._client.webhook_secret` | No check when empty (`telegram/adapter.py:120-121`) |
| `SlackInboundAdapter` | no override | — | Construction already fails: an empty `SLACK_SIGNING_SECRET` makes `AsyncApp(...)` raise `ValueError("signing_secret must not be empty.")` (`slack_sdk/signature/__init__.py:41`, via `slack_bolt/app/async_app.py:414`) |
| `TeamsInboundAdapter` | no override | — | Construction already fails: `_TeamsCredentials` raises `ValueError` (`teams/adapter.py:62-64`) |

"Empty" means falsy, exactly the test `verify_signature` (`meta.py:30`) and `TelegramInboundAdapter.verify`
(`telegram/adapter.py:120`) apply. A whitespace-only secret is therefore "set" for the guard, just as
it is a real (if weak) HMAC key for the check.

**`WebhookRESTRequestHandler.adapter`** (`integration/adapter/webhook.py`): a read-only property
returning `self._adapter`, the `PollerRunner.adapter` precedent (`integration/adapter/poller.py:38-41`).
`handle`, `challenge` and `get_router` are unchanged.

**Lazy exports** (`integration/adapter/__init__.py:14-25`): add `"WebhookRoute": ".routes"` and
`"WebhookRouteMatcher": ".route_matcher"`, plus their `TYPE_CHECKING` mirrors.

#### 8. `LambdaEventTranslator` (new: `deployment/aws/serverless/core/event_translator.py`)

**Its job:** API Gateway REST (v1) proxy event ⇄ Starlette. It builds the `Request` an adapter reads,
and turns what the handler produced into the proxy response FastAPI would have sent. It holds no
state.

**Imports** (module scope, all FastAPI/Starlette; hence never imported by `core/__init__.py`):
`starlette.requests.Request`, `starlette.responses.Response`/`PlainTextResponse`,
`starlette.exceptions.HTTPException`, `fastapi.encoders.jsonable_encoder`,
`fastapi.responses.JSONResponse`, `fastapi.exception_handlers.http_exception_handler`.

```python
class LambdaEventTranslator:
    """API Gateway REST (v1) proxy events <-> Starlette, for the Lambda webhook host (#760)."""

    _log = logging.getLogger("ak.aws.lambda.webhook")

    def to_request(self, event: Mapping[str, Any]) -> Request: ...
    async def to_proxy_response(self, request: Request, result: Any) -> Dict[str, Any]: ...
    async def error_to_proxy_response(self, exc: Exception, request: Optional[Request] = None) -> Dict[str, Any]: ...

    @staticmethod
    def _body(event: Mapping[str, Any]) -> bytes: ...
    @staticmethod
    def _headers(event: Mapping[str, Any]) -> List[Tuple[bytes, bytes]]: ...
    @staticmethod
    def _query_string(event: Mapping[str, Any]) -> bytes: ...
    @staticmethod
    def _proxy_response(response: Response) -> Dict[str, Any]: ...
```

**Event → `Request`.** `to_request` builds an ASGI `http` scope and a `receive` callable, and returns
`starlette.requests.Request(scope, receive)`.

| Scope key | Source |
|---|---|
| `method` | `event["httpMethod"]`, upper-cased |
| `path`, `raw_path` | `event["path"]`, the field the router dispatches on (`rest_lambda.py:391`), e.g. `/api/v1/slack/events`; `"/"` when absent |
| `query_string` | `_query_string`: `multiValueQueryStringParameters` (`{name: [values]}`), falling back to `queryStringParameters` (`{name: value}`); `urlencode(pairs, doseq=True)`, in event order |
| `headers` | `_headers`: `multiValueHeaders`, falling back to `headers`; names lower-cased (the ASGI rule, which is what makes Starlette's lookup case-insensitive); values encoded latin-1, or UTF-8 for a value latin-1 cannot hold |
| `scheme` | the `x-forwarded-proto` header, else `"https"` |
| `server` | the `host` header, else `requestContext.domainName`; the port from `x-forwarded-port`, else 443 |
| `client` | `(requestContext.identity.sourceIp, 0)` when present, else `None` |
| `type`, `asgi`, `http_version`, `root_path` | `"http"`, `{"version": "3.0"}`, `"1.1"`, `""` |

- **The body is the exact bytes.** `_body` returns `b""` for a missing body, `base64.b64decode(body)`
  when `isBase64Encoded` is true, and `body.encode("utf-8")` otherwise. The first `receive()` returns
  `{"type": "http.request", "body": ..., "more_body": False}`, and later calls return
  `{"type": "http.disconnect"}`.
- **Starlette caches the body** after the first read. That is what lets Meta's `verify` hash the body
  and `parse` then call `raw.json()` on the same request.
- **Why the single-value maps are a fallback:** a valid proxy event can carry only them. Existing
  serverless code reads that shape (`examples/aws-serverless/schedule-openai/lambda_request_handler.py:37`),
  and Meta's handshake reads `hub.mode`, `hub.verify_token` and `hub.challenge` from the query
  (`integration/adapter/meta.py:51-53`).
- **Bolt's Starlette handler needs exactly these:** `req.method`, `await req.body()`, `req.query_params`
  and `req.headers` (`slack_bolt/adapter/starlette/async_handler.py:52-69`).

**Result → proxy response** (`to_proxy_response`):
- A Starlette `Response` passes through as it is: Bolt's own (`async_handler.py:27-45`) and Teams'
  `JSONResponse` (`teams/adapter.py:174`).
- Any other value becomes `JSONResponse(jsonable_encoder(result))`, status 200. FastAPI does the same
  for a route with no response model: it encodes (`fastapi/routing.py:341`) and then instantiates the
  default `JSONResponse` (`:747`). This covers `success_response()`'s dicts (`webhook.py:82`,
  `telegram/adapter.py:114-116`) and Meta's `int` challenge (`meta.py:57`).

**Exception → proxy response** (`error_to_proxy_response`):
- A `starlette.exceptions.HTTPException`, which `fastapi.HTTPException` subclasses, goes through
  FastAPI's own `http_exception_handler` (`fastapi/exception_handlers.py:11-17`): its status, its
  `headers`, and `{"detail": ...}`, or no body for a status that allows none. That handler ignores
  its `request` argument, so a `None` request is safe.
- Anything else is logged with `_log.exception` and becomes `PlainTextResponse("Internal Server Error", status_code=500)`.
  That is the body Starlette's `ServerErrorMiddleware` sends (`starlette/middleware/errors.py:259`).
  Unlike `Lambda.handler`'s catch-all (`aklambda.py:87-90`), it never puts the exception text in the
  response.

**`_proxy_response(response)`:**
```python
{"statusCode": response.status_code,
 "multiValueHeaders": {name: [value, ...]},   # from response.raw_headers, decoded latin-1, order kept
 "body": <text>, "isBase64Encoded": False}     # body.decode("utf-8"); base64 + True when that fails
```
- `multiValueHeaders` only: API Gateway REST accepts it in a proxy response, and it keeps repeated
  headers such as `set-cookie` (Bolt sets cookies on OAuth responses, `async_handler.py:33-44`).
- A response with no `body` attribute (a `StreamingResponse`) raises
  `TypeError("streaming responses are not supported on Lambda")`, which the host turns into a 500. No
  built-in adapter returns one.
- `Response.background` tasks are not run. No built-in adapter sets one.
- `Lambda._wrap_response` passes the dict through unchanged, because it has `statusCode` and `body`
  (`aklambda.py:58-59`).

#### 9. `LambdaWebhookHost` and `LambdaWebhookGuard` (new: `deployment/aws/serverless/core/webhook_host.py`)

`webhook_host.py` imports `WebhookRESTRequestHandler` and `LambdaEventTranslator` at module scope.
So it is FastAPI-dependent, and `agentkernel.aws` exports `LambdaWebhookHost` lazily (§13): only
touching that name imports the module.

```python
class LambdaWebhookHost:
    """Serves one WebhookRESTRequestHandler from routes the application registers (#760).

    Build it at module scope and register its endpoints with ``Lambda.register``.
    Wraps the handler and copies none of it: verify, parse, acknowledge and enqueue stay in
    WebhookRESTRequestHandler.handle, shared with the pipeline IOHandler.
    """

    _log = logging.getLogger("ak.aws.lambda.webhook")
    _loop: ClassVar[Optional[asyncio.AbstractEventLoop]] = None   # one per execution environment

    def __init__(self, handler: WebhookRESTRequestHandler, translator: Optional[LambdaEventTranslator] = None):
        """Check the deployment can serve the handler, so a broken one fails its Lambda init loudly.

        :raises TypeError: The handler is not a WebhookRESTRequestHandler.
        :raises AKConfigError: See LambdaWebhookGuard.
        """
        self._handler = LambdaWebhookGuard().check(handler)
        self._translator = translator or LambdaEventTranslator()

    def handle(self, event: Dict[str, Any], context: Any) -> Dict[str, Any]:     # the router's (event, context) contract
        return self._run(self._respond(self._handler.handle, event))

    def challenge(self, event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        return self._run(self._respond(self._handler.challenge, event))

    async def _respond(self, endpoint: Callable[[Request], Awaitable[Any]], event: Mapping[str, Any]) -> Dict[str, Any]:
        request = None
        try:
            request = self._translator.to_request(event)
            return await self._translator.to_proxy_response(request, await endpoint(request))
        except Exception as exc:                  # HTTPException included: its status is the answer
            return await self._translator.error_to_proxy_response(exc, request)

    @classmethod
    def _run(cls, coro: Coroutine) -> Any:
        if cls._loop is None or cls._loop.is_closed():
            cls._loop = asyncio.new_event_loop()
        return cls._loop.run_until_complete(coro)
```

The host registers nothing itself: `handle` and `challenge` are what the application registers (§10).

**Routing** goes through the existing `RESTLambdaRouter.register` (`rest_lambda.py:353-378`), which
`Lambda.register` delegates to (`aklambda.py:40-48`). The router's exact-match table and base-path
stripping (`:394-401`) choose the route, and no built-in webhook path has path parameters. For
example, `POST /api/v1/slack/events` is stripped to `/slack/events`, which matches the registered
route. A path registered twice keeps the first handler, with the router's existing warning
(`:372-374`).

**Event loop rules**
1. **One loop per execution environment,** class-level and shared by every host. It is reused
   across warm invocations, like uvicorn's single loop on the other surfaces (`pipeline/io_handler.py:111`).
   `run_async_sync` could not promise that: with no current loop it falls back to a fresh
   `asyncio.run` per call (`core/util/async_bridge.py:34-40`).
2. **The loop is never made the thread's current loop** (`asyncio.set_event_loop` is not called). So
   `run_async_sync` and `iterate_async_sync` elsewhere in the process see exactly what they see
   today. `run_until_complete` needs no current loop.
3. **A closed loop is replaced,** which is only reachable in tests.
4. **`asyncio.to_thread`,** which `WebhookRESTRequestHandler.handle` uses to enqueue (`webhook.py:75`),
   runs on this loop's default executor. That executor is created once and reused.

`LambdaWebhookGuard` holds the checks the host's constructor runs (the design's fail-fast guards).
The host is built at module scope, so they run on cold start, before the application registers any
of the host's endpoints:

```python
class LambdaWebhookGuard:
    """The cold-start checks LambdaWebhookHost runs (#760): fail at import, not on the first delivery."""

    REST_MODES = (ExecutionMode.REST_SYNC, ExecutionMode.REST_ASYNC)
    BASE_PATH_ENV = ("API_BASE_PATH", "API_VERSION", "AGENT_ENDPOINT")

    def check(self, handler: Any) -> WebhookRESTRequestHandler:
        """Run every check, in this order; return the handler, typed.

        :raises TypeError: The handler is not a WebhookRESTRequestHandler.
        :raises AKConfigError: Mode, transport, base-path environment or verification settings.
        """
```

| # | Check | Raises | Message names |
|---|---|---|---|
| 1 | The handler is a `WebhookRESTRequestHandler` | `TypeError` | the offending type, and that `LambdaWebhookHost` serves `WebhookRESTRequestHandler` only |
| 2 | `AKConfig.get().execution.mode` is `rest_sync` or `rest_async` | `AKConfigError` | the mode, and that `Lambda` routes the other modes' events to `WSLambdaRouter` (`aklambda.py:31`). An unset mode (the default, `core/config.py:655-658`) is rejected too |
| 3 | If the handler has `requires_pipeline`, `QueueTransportFactory.resolve_type() == "sqs"` | `AKConfigError` | the resolved type, and both halves of the fix: `queue_mode = true` in Terraform and `execution.queues.type: sqs` in `config.yaml` |
| 4 | `API_BASE_PATH`, `API_VERSION` and `AGENT_ENDPOINT` are all set | `AKConfigError` | the missing names, and that the ak-serverless module sets them (`modules/request-handler/main.tf:348-351`) |
| 5 | The handler's `adapter.missing_verification_settings()` is empty | `AKConfigError` | the adapter class and its missing settings |

Every message starts with `LambdaWebhookHost`, the class the application called.

- **Why this order.** Check 1 is a programming error. Checks 2-4 describe the deployment. Check 5 is
  about the adapter.
  - The mode is checked before the application's `Lambda.register` builds the router, because in
    `async`/`stream` `Lambda._get_router()` would build a `WSLambdaRouter` (`aklambda.py:29-32`).
  - The transport check keys off `requires_pipeline` rather than off the class, so future
    pipeline-only handlers are covered.
- **A failed check raises from the constructor.** The exception escapes module import, so the Lambda
  fails its init loudly, and nothing is registered for that host: the application's
  `Lambda.register` calls come after it.

#### 10. Registering the host's endpoints (application code, through `Lambda.register`)

`Lambda` is unchanged (`aklambda.py`). The application builds one host per handler at module scope
and registers its endpoints with `Lambda.register`, as it would any custom route:

```python
from agentkernel.aws import Lambda, LambdaWebhookHost
from agentkernel.integration.adapter import WebhookRESTRequestHandler
from agentkernel.slack import SlackInboundAdapter

slack = LambdaWebhookHost(WebhookRESTRequestHandler(SlackInboundAdapter()))


@Lambda.register("/slack/events", method="POST")
def slack_events(event, context):
    return slack.handle(event, context)


handler = Lambda.handler
```

- **The routes to register:**
  - `POST` on the adapter's `webhook_path` → `host.handle`, for every webhook adapter;
  - `GET` on its `challenge_path` → `host.challenge`, only for an adapter that declares one
    (WhatsApp, Messenger, Instagram), e.g.
    `Lambda.register("/whatsapp/webhook", method="GET")(whatsapp.challenge)`.
  - Both methods have the router's `(event, context)` contract, so a bound method can be passed to
    the decorator directly, as above.
- **The paths are hand-written.** The host does not read them, so the registered path must equal
  the adapter's `webhook_path`/`challenge_path` (for a built-in, its `BUILTIN_WEBHOOK_ROUTES` entry,
  §6). The same path must also be in `gateway_endpoints` and, behind an authorizer, in the bypass:
  the three places an integration is declared. A path that is in the gateway and the bypass but not
  registered is the router's no-route 500 ([Error handling](#error-handling)).
- **Build first, then register.** The guards run in the constructor (§9), so a broken deployment
  fails before any of that host's routes exist.
- **The response-store requirement is unchanged.** In queue mode `_get_router()` raises it
  (`rest_lambda.py:54-57`) on whichever call first builds the router: the application's first
  `Lambda.register`, or else `Lambda.handler`.

#### 11. `WebhookRouteMatcher` (new: `integration/adapter/route_matcher.py`)

Its only imports are `os`, `logging`, `typing`, `core.util.factory.AKConfigError` and `.routes`, so
the authorizer Lambda loads neither `fastapi` nor any platform SDK.

```python
class WebhookRouteMatcher:
    """The APIGatewayAuthorizer bypass for messaging-integration routes (#760 Q1).

    Matches an authorizer event's method and path, and nothing else. The event has no body, so no
    signature can be checked here, and a header test could be spoofed onto a chat request. The
    adapter's verify, in the request-handler Lambda, stays the real check.
    """

    def __init__(self, routes: Iterable[WebhookRoute], base_path: Optional[str] = None):
        """
        :param routes: The routes to let through: POST on each webhook_path, GET on each challenge_path.
        :param base_path: The prefix API Gateway serves them under, e.g. "/api/v1". None derives it from
            API_BASE_PATH and API_VERSION, which the ak-serverless module sets on the authorizer Lambda.
        """

    @classmethod
    def for_integrations(cls, *names: str, base_path: Optional[str] = None) -> "WebhookRouteMatcher":
        """A matcher for built-in integrations, by name: for_integrations("slack", "whatsapp").

        :raises ValueError: If no name is given.
        :raises AKConfigError: If a name is not a built-in; the message lists the built-ins and
            points bring-your-own adapters at WebhookRouteMatcher([WebhookRoute(...)]).
        """

    def __call__(self, event: Mapping[str, Any]) -> Optional[str]:
        """The name of the integration whose route this authorizer event targets, else None."""
```

1. **The route table is built once** at construction, as `{(METHOD, normalized_path): name}`.
   `normalized_path` follows the rule `BaseLambdaRouter._normalize_path` applies to registered
   routes (`core/router/common.py:21-35`): a leading `/`, and no trailing `/`.
2. **`__call__` mirrors the router's dispatch** (`rest_lambda.py:390-401`):
   - method: `str(event.get("httpMethod") or "").upper()`
   - path: `event.get("path") or ""`, with `base_path` removed by `str.removeprefix`, and then looked
     up **exactly**; the event path is not normalized, as in the router
   - It reads no header and no query parameter.
3. **The derived `base_path`** is `f"/{API_BASE_PATH}/{API_VERSION}"` when both are set, and `""`
   otherwise. That is the same string as `BaseLambdaRouter._get_base_paths_from_env` (`common.py:54-59`).
   - It is derived here, not imported, because `integration/` must not import `deployment/`. The test
     "the base path is stripped as the router strips it" pins the two together.
   - **With no base path the matcher fails closed.** The gateway path `/api/v1/slack/events` then does
     not equal `/slack/events`, so the event goes to the validator.
4. **It keeps no state across calls.** It is safe to share and has no per-call cost beyond one dict
   lookup.

#### 12. `APIGatewayAuthorizer` bypass (`deployment/aws/serverless/akauthorizer.py`)

```python
WebhookBypass = Callable[[Dict[str, Any]], Optional[str]]

class APIGatewayAuthorizer:
    def __init__(self, validator: AuthValidator, bypass: Optional[WebhookBypass] = None): ...

    def handle(self, event: dict, context: dict = None) -> dict:
        self._log.info(f"Authorizer received event: {event}")          # unchanged (:30)
        policy = self._bypass_policy(event)
        if policy is not None:
            self._log.info(f"Authorizer return policy: {policy}")
            return policy
        ...                                                             # :32-63 unchanged

    def _bypass_policy(self, event: dict) -> Optional[dict]:
        """An Allow for a request the bypass recognises, or None to take the normal path."""
```

- **It is checked first,** before `_build_request`. Otherwise the required `Headers.Authorization`
  (`akauthorizer.py:10-11`) turns a header-less webhook into a Deny.
- **`_bypass_policy` returns `None`** when there is no `bypass`, when the event has no `methodArn`,
  when `bypass(event)` returns a falsy value, or when it raises. A raise is logged at WARNING with
  `exc_info` and falls through to the validator, which fails closed for a request with no token.
- **Otherwise it returns `_build_policy(principal_id=..., effect="Allow", method_arn=event["methodArn"], context=None)`:**
  - the exact `methodArn`, never a wildcard, and no claims
  - principal `integration:<name>` for a `str` result
  - principal `integration` for any other truthy result, so that a hand-written `bool` predicate
    also works
- **Without `bypass`,** `handle` behaves byte for byte as today: `_bypass_policy` returns `None` at
  once.
- The validator is never called on a bypassed request, so Teams' Bot Framework JWT never reaches the
  app's `AuthValidator`.

**Authorizer caching has to be off wherever a bypass is used** (`authorizer.result_ttl_in_seconds = 0`).
Terraform cannot enforce this: it does not know a bypass is configured. The example and the docs set
it, and the docs explain the 401 that API Gateway returns before the authorizer runs
(`modules/api-gateway/main.tf:234-236`).

### Shared

#### 13. Packaging and lazy imports

**`ak-py/pyproject.toml`**
- `fastapi>=0.118.0` (the `api` extra's floor, `:121`) is added to `slack` (`:126-129`), `whatsapp`
  (`:130-132`), `messenger` (`:133-135`), `instagram` (`:136-138`), `telegram` (`:139-141`) and
  `teams` (`:142-148`). `gmail` is left alone: it imports no FastAPI.
- `aiohttp>=3.9.0` (the `teams` extra's floor, `:145`) is added to `slack`. Bolt's async app imports
  it at module scope (`slack_bolt/app/async_app.py:8`).
- `ak-py/uv.lock` is regenerated with `uv lock`.

**`api/__init__.py`** becomes a PEP 562 lazy-export module, following `integration/adapter/__init__.py:14-46`:
```python
import importlib
import importlib.metadata
from typing import TYPE_CHECKING, Any

try:
    __version__ = importlib.metadata.version("agentkernel")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.1.0"

_LAZY_EXPORTS = {"AgentRESTRequestHandler": ".handler", "RESTRequestHandler": ".handler", "RESTAPI": ".http"}
__all__ = sorted(_LAZY_EXPORTS)

if TYPE_CHECKING:  # pragma: no cover: static resolution only
    from .handler import AgentRESTRequestHandler, RESTRequestHandler
    from .http import RESTAPI

def __getattr__(name: str) -> Any: ...   # import _LAZY_EXPORTS[name] relative to __name__, return the attribute
def __dir__() -> list[str]: ...
```
- `from agentkernel.api import RESTAPI` keeps working. It is the public form, used across the
  bundled skills, for example `skills/ak-init/SKILL.md:161`.
- Every `patch("agentkernel.api.http.uvicorn.run")` target keeps working (`ak-py/tests/test_api_http.py:319`
  and six more): `patch` imports `agentkernel.api.http` itself.
- **Effect.** `integration/adapter/webhook.py:7` imports `api.handler`, which no longer drags in
  `api.http` and so no longer drags in `uvicorn` (`api/http.py:3`). A clean
  `agentkernel[aws,slack]` venv plus `fastapi` and `aiohttp` served Bolt's `url_verification`
  through a hand-built Starlette `Request` with `uvicorn` absent. That was checked against a scratch
  copy of this change.

**`deployment/aws/__init__.py`** gains one lazy export in `_LAZY_EXPORTS`,
`"LambdaWebhookHost": ".serverless.core.webhook_host"`, plus its `TYPE_CHECKING` mirror. `agentkernel.aws` delegates to that module's
`__getattr__` (`aws.py`), so `from agentkernel.aws import Lambda, LambdaWebhookHost` works, and only
touching `LambdaWebhookHost` imports `webhook_host`, and with it FastAPI and Starlette.

**Lazy boundaries that stay as they are:**
- `from agentkernel.aws import Lambda` loads neither `fastapi` nor `starlette` today, and still
  won't: `Lambda` never imports `webhook_host`, `LambdaWebhookHost` resolves only when touched, and
  `deployment/aws/serverless/core/__init__.py` does not import the two new modules.
- Importing `APIGatewayAuthorizer`, `agentkernel.integration.adapter` or `WebhookRouteMatcher` loads
  neither `fastapi` nor `slack_bolt`.
- The serverless consumers import `agentkernel.integration` only when an integration message
  arrives, through `IntegrationDelivery._outbound_adapter`.

#### 14. Terraform (`ak-deployment/ak-aws/serverless/`)

1. **The multimodal table reaches the request handler under `queue_mode`** (`state.tf:592`, `:597-598`):
   ```hcl
   # Not nulled under queue_mode, unlike the session and thread wiring around it: messaging
   # integrations download and offload attachments at the edge, in this Lambda (#760).
   create_dynamodb_multimodal_memory_table = var.create_dynamodb_multimodal_memory_table
   dynamodb_multimodal_memory_table_arn    = local.dynamodb_multimodal_memory_table_arn
   dynamodb_multimodal_memory_table_name   = local.dynamodb_multimodal_memory_table_name
   ```
   - The request handler then gets `AK_MULTIMODAL__DYNAMODB__TABLE_NAME` (`modules/request-handler/main.tf:362-364`)
     and the table's IAM policy (`:61-91`).
   - The existing flag drives it; there is no new flag.
   - Session and thread wiring stay nulled under `queue_mode`, as today (`state.tf:591`, `:593-596`, `:599-601`).
2. **The base path reaches the authorizer** (`state.tf:206`):
   ```hcl
   # WebhookRouteMatcher strips /<API_BASE_PATH>/<API_VERSION> the way the router does (#760).
   # AK's values win, as on the request handler (modules/request-handler/main.tf:348-351).
   authorizer_info = var.authorizer == null ? null : merge(var.authorizer, {
     environment_variables = merge(var.authorizer.environment_variables, {
       API_BASE_PATH = var.api_base_path
       API_VERSION   = var.api_version
     })
   })
   ```
   - The `null` guard keeps a stack without an authorizer valid.
   - The merge sits at this call, not in `ak-aws/common/modules/authorizer/main.tf:130`. That module
     is consumed from the registry (`state.tf:202-203`), so an edit there would take effect only
     after `ak-common` is re-released.
3. **The output queue URL reaches the request handler under `queue_mode`.**
   - `WebhookRESTRequestHandler` enqueues through the pipeline transport:
     `IntegrationProducer()` → `RequestProducer(None)` → `QueueTransportFactory.create()`
     (`integration/adapter/producer.py:32`, `pipeline/producer.py:22`), at construction, which is
     module scope on Lambda.
   - The `sqs` branch requires both queue URLs and raises `AKConfigError` otherwise
     (`pipeline/transport/base.py:143-146`). The request handler today gets only
     `AK_EXECUTION__QUEUES__INPUT__URL` (`modules/request-handler/main.tf:388-390`).
   - The chat route never noticed, because it sends through `SQSHandler`, which reads only the
     input URL (`deployment/aws/core/sqs_handler.py:73-80`).
   - So without this item, every `WebhookRESTRequestHandler(...)` on the stock stack fails its
     import.
   - The fix, in the local `modules/request-handler` (`state.tf:546`):
     - a new module input, `variable "output_queue_url" { type = string, default = null }`
     - `var.output_queue_url != null ? { AK_EXECUTION__QUEUES__OUTPUT__URL = var.output_queue_url } : {}`,
       merged beside the input URL
     - `output_queue_url = local.output_queue_url` at the module call (`state.tf:613`, beside
       `input_queue_url`)
   - No IAM change: the request handler never sends to the output queue. Its `sqs:SendMessage`
     stays scoped to the input queue (`modules/request-handler/main.tf:202-205`).
   - This is a module-internal variable, not a stack variable.
4. **Unchanged:**
   - `gateway_endpoints` (`variables.tf:262-290`) already declares webhook routes, for example
     `{ path = "/slack/events", method = "POST" }`. Its entries nest under `/<api_base_path>/<api_version>/`
     (`modules/api-gateway/main.tf:45-62`), which is exactly the prefix the router strips.
   - `authorization` stays `CUSTOM` on every route (`modules/api-gateway/main.tf:94`).
   - The default TTL stays 150 (`variables.tf:300`).
   - Credentials reach the two Lambdas through `request_handler.environment_variables` (`variables.tf:345`)
     and `response_handler.environment_variables` (`:418`).
5. **Module version pins are not edited.** The release chore bumps them. Until `ak-serverless` is
   released with items 1-3, the example's pinned module lacks them. So the example is deployable
   from the release that ships this change, and before that only against a local `source`.
6. `ak-deployment/ak-aws/serverless/README.md` and `modules/request-handler/README.md` (its
   environment-variable list, `:89`) note the new behaviours.

#### 15. Example: `examples/aws-serverless/slack-openai/`

This follows `examples/aws-serverless/schedule-openai/`: one package per Lambda through
`[project.optional-dependencies]`, and `deploy.sh` exporting each with `uv export --extra <name>`.

| File | Contents |
|---|---|
| `lambda_request_handler.py` | `slack = LambdaWebhookHost(WebhookRESTRequestHandler(SlackInboundAdapter()))` at module scope, `@Lambda.register("/slack/events", method="POST")` on a function returning `slack.handle(event, context)`, then `handler = Lambda.handler` (§10) |
| `lambda_agent_runner.py` | an OpenAI Agents SDK agent, `OpenAIModule([...])`, `handler = ServerlessAgentRunner.handle` |
| `lambda_response_handler.py` | `handler = ResponseHandler.handle` |
| `lambda_auth.py` | a demo `AuthValidator`, and `handler = APIGatewayAuthorizer(validator=DemoValidator(), bypass=WebhookRouteMatcher.for_integrations("slack")).handle` |
| `config.yaml` | `execution.mode: rest_async`; `execution.queues.type: sqs`; `execution.response_store.type: dynamodb`; `session.type: dynamodb`; `slack.agent`; a commented `multimodal` block naming `storage_type: dynamodb` and `create_dynamodb_multimodal_memory_table` for attachments |
| `pyproject.toml` | extras: `request_handler` and `response_handler` = `agentkernel[aws,slack]`, `agent_runner` = `agentkernel[aws,openai]`, `authorizer` = `agentkernel[aws]` |
| `deploy/main.tf` | `queue_mode = true`, `execution_mode = "rest_async"`, `create_dynamodb_response_store = true`, `create_dynamodb_memory_table = true`, `gateway_endpoints = [{ path = "/slack/events", method = "POST" }]`, `authorizer = { ..., result_ttl_in_seconds = 0 }`, `SLACK_BOT_TOKEN`/`SLACK_SIGNING_SECRET` in `request_handler.environment_variables` and `response_handler.environment_variables` |
| `deploy/{variables,outputs,providers}.tf`, `terraform.tfvars`, `deploy.sh`, `build.sh` | as in `schedule-openai`, including the `local` wheel branch |
| `lambda_test.py` | a deployed smoke test that needs no Slack workspace (see [Testing](#testing)) |
| `README.md` | Slack app setup, the three places an integration is declared, and the TTL-0 requirement |

- The module version pin is copied from the sibling examples at the time of writing, and is never
  bumped by hand.
- The example is not added to the weekly integration matrix in this change.

### Components and module-level code

Every new component is a class with one job: `IntegrationDelivery`, `WebhookRoute`,
`WebhookRouteMatcher`, `LambdaEventTranslator`, `LambdaWebhookHost` and `LambdaWebhookGuard`. There
are no new module-level functions. The one new module-level value is `BUILTIN_WEBHOOK_ROUTES`, which
is read-only data.

### Concurrency

- **Pipeline:** one `ResponseHandler`, and so one `IntegrationDelivery`, serves every consumer
  thread.
  - The delivery object is built in `__init__` and holds only a logger.
  - Adapters come from the factory's lock-guarded cache.
  - `run_async_sync` drives each coroutine on the calling thread, as today.
- **Serverless:** Lambda runs one invocation at a time per execution environment, and a batch's
  records run in sequence (`serverless/core/sqs_consumer.py:42-62`).
  - The class-level lazies (`ResponseHandler._integration_delivery`, `LambdaWebhookHost._loop`)
    therefore cannot race.
  - The hosts are built, and their endpoints registered, once, at import.
- **Shared, stateless objects:** `WebhookRouteMatcher` and `LambdaEventTranslator` are immutable
  after construction.

### Per-operation cost

| Where | Added work |
|---|---|
| Every output message (both response handlers) | One dict lookup (`integration_of`) |
| Every serverless input message | One pass over at most 10 attributes (`routing_attributes`) |
| First integration message in a process | The lazy import of the adapter factory and the platform SDK. A Lambda without integration traffic never pays it |
| Every authorizer call, with a bypass | One method/path dict lookup |
| Every authorizer call, TTL 0 | The authorizer Lambda runs on every request: chat routes lose policy caching, and each webhook pays one more Lambda call, cold start included. Accepted in Q1 |
| Every webhook delivery | Building the scope, one `run_until_complete` on the reused loop, and response encoding. The adapter's own work is unchanged |

---

## Consumer changes

| Consumer | Deleted | Changed | Checked and unchanged |
|---|---|---|---|
| `pipeline.ResponseHandler` | `_outbound_adapter`, `_reply_context`, `_deliver_integration`; four imports | `__init__`; the integration branches of `process` and `on_permanent_failure` | `_store_response`, `_store_chunk`, `_broadcast`, `_broadcast_error`, `start`, the mode branches |
| `pipeline.AgentRunner` / `StreamAgentRunner` | two imports | `_FORWARDED_ATTRIBUTES`/`_is_forwarded`, two integration checks, one docstring | `process`, `_send_to_output`, `_resolve_request_metadata`, `_record_thread_reply` logic |
| `ServerlessAgentRunner` | — | `process_message`, `_get_record_attributes`, `_send_to_output_queue` | `handle`, `on_permanent_failure` code, `_parse_body`, `_body_from_record` |
| `ServerlessStreamAgentRunner` | — | `process_message`, `on_permanent_failure` | `_get_record_attributes`, `_send_chunk_to_output_queue`, `handle` |
| Serverless `ResponseHandler` | — | `process_message`, `on_permanent_failure`, `_construct_message_for_store`; new `_get_integration_delivery`, `_decode_body` | `_resolve_status_code`, `_broadcast_via_websocket`, `_get_response_store`, `_get_base_ws_handler` |
| `Lambda` | — | — | `handler`, `register`, `_get_router`, `_wrap_response`; the application registers the host's endpoints with `register` |
| `RESTLambdaRouter`, `DefaultEndpointsHandler` | — | — | Unchanged; the application registers the host's endpoints as any route |
| `agentkernel.aws` (`deployment/aws/__init__.py`) | — | the `LambdaWebhookHost` lazy export | every existing export, and `aws.py`'s delegation |
| `APIGatewayAuthorizer` | — | `__init__` (`bypass`), `handle` (one early branch); new `_bypass_policy` | `_build_request`, `_extract_token`, `_build_policy`, `_build_deny_policy` |
| `WebhookRESTRequestHandler` | — | new `adapter` property | `handle`, `challenge`, `get_router`, `requires_pipeline` |
| `InboundAdapter` | — | new `missing_verification_settings` | `verify`, `parse`, `challenge`, `success_response` |
| The six webhook adapters | the path literals | the paths read from the table; four `missing_verification_settings` overrides | `verify`, `parse`, `challenge`, and the outbound halves |
| `IntegrationAdapterContract` | — | one new contract test | the existing tests and hooks |
| `RESTAPI`, `AgentRESTRequestHandler` | — | reached through the lazy `agentkernel.api` | Their modules are unchanged |
| ECS (`ECSAgentRunner`, `ECSOutputConsumer`, `ECSIOHandler`) | — | — | Untouched (design Non-goals) |

## Config changes

**No `AKConfig` change.** No field is added, renamed or re-described.
- The `integration` attribute on a message is the switch for delivery, as in the pipeline.
- Building a `LambdaWebhookHost` and registering its endpoints is the switch for receiving.
- `bypass=` is the switch for the authorizer.
- Existing YAML and `AK_*` variables behave as before.

The changes outside `AKConfig` are packaging (§13) and Terraform (§14). Neither adds a variable.

## Behavioural changes

All of these are intentional.

1. **Integration replies reach the platform on serverless.**
   - In REST modes they no longer land in the response store.
   - In ASYNC and STREAM they no longer fail the WebSocket broadcast and burn their retries.
   - *Why:* pipeline parity.
2. **STREAM mode on serverless runs an integration message as one reply.**
   - Before, `ServerlessStreamAgentRunner` raised before the agent ran.
   - Ordinary post-hooks (`PostHook.on_run`) apply, not `on_stream_event`.
   - *Why:* a platform consumes one reply (`pipeline/agent_runner.py:213`).
3. **A body's `requests` list is honoured on serverless,** in both runners and for every entry point.
   - The Lambda routers already forward a client-supplied `requests` (`rest_lambda.py:143-148`,
     `ws_lambda.py:397`).
   - A prompt is still required: `QueueMessageBody.prompt` (`deployment/aws/core/sqs_handler.py:56`).
   - *Why:* queue-mode parity (D4).
4. **Serverless permanent failures are delivered in every mode.**
   - REST pollers get the 500 record, and WebSocket clients get their `SYSTEM_RESPONSE` or error
     `STREAM_CHUNK`.
   - Before, a `KeyError` was caught and logged and nothing was delivered.
   - *Why:* D1.
5. **Serverless integration traffic whose adapter can't be resolved now fails loudly.** That covers
   an unknown name and a missing extra.
   - It is retried up to `execution.queues.output.max_receive_count` times, then the
     permanent-failure attempt fails the same way and is logged at ERROR.
   - Before, the reply was silently stored.
   - *Why:* pipeline parity.
6. **Webhooks can be served on Lambda,** through a `LambdaWebhookHost` whose endpoints the
   application registers with `Lambda.register`, in `rest_sync`/`rest_async` on `sqs`. A host's
   route answers:
   - `HTTPException` with its own status and `{"detail": ...}`;
   - an unexpected error with `500 Internal Server Error` in plain text, never the exception text.
7. **With a bypass, integration routes pass the authorizer without a token.** The adapter's own
   verification is the check. Every other route is authorized exactly as before.
8. **Installing a webhook platform extra now installs FastAPI,** and `slack` also installs aiohttp.
   - *Why:* both Lambdas import them (Q5).
9. **`agentkernel.api` resolves its exports lazily.** Importing `agentkernel.api` or
   `agentkernel.api.handler` no longer imports `agentkernel.api.http` or `uvicorn`.
   - Code that reached `agentkernel.api.http` as an attribute without ever importing it would now
     need the import. No code in the repo does this.
   - *Why:* Q5.
10. **Terraform, queue mode with `create_dynamodb_multimodal_memory_table = true`:** the request
    handler gains the table's environment variable and IAM policy, and a plan shows that addition.
11. **Terraform, with an authorizer:** the authorizer Lambda gains `API_BASE_PATH` and `API_VERSION`,
    and a plan shows an in-place update. A user variable of either name is overridden.
12. **Terraform, queue mode:** the request handler gains `AK_EXECUTION__QUEUES__OUTPUT__URL`, and a
    plan shows an in-place update. Chat traffic ignores it: `SQSHandler` reads only the input URL.
13. **The pipeline's private delivery helpers are removed.** A subclass overriding them is no longer
    called. They are `_`-prefixed and undocumented.
14. **Log lines:** the serverless response handler logs integration deliveries under
    `ak.aws.responsehandler`. The webhook host's translator logs under `ak.aws.lambda.webhook`.
    Pipeline log names and messages are unchanged.

**What does not change**
- **Layouts:** the response-store record `{session_id, request_id, status_code, body}`, WebSocket
  frame shapes, chunk dedup ids `{dedup}-{receive_count}-{i}`, and the wire attribute names
  (`pipeline/envelope.py:12-14`).
- **Non-integration traffic:** the same output attributes and the same response-store and WebSocket
  deliveries, apart from change 4.
- **Signatures:** the four overridable classmethods of each serverless consumer.
- **The authorizer without a bypass,** and `Lambda.handler`/`register`.
- **Every webhook path,** the pipeline's `WebhookRESTRequestHandler` behaviour, and every surface's
  handling of Slack retries (Q4).
- **Exports:** every existing export of `agentkernel.aws`, `agentkernel.deployment.aws` and
  `agentkernel.pipeline`. The only additions are `LambdaWebhookHost` (lazy, in `agentkernel.aws`
  and `agentkernel.deployment.aws`) and the two in `agentkernel.integration.adapter`.
- **Rolling deploys:**
  - A new response handler reading an old runner's output finds no routing attributes and takes
    today's path.
  - An old response handler stores a new runner's output, as today.
  - So the mixed window never fails a message.

## Error handling

| Failure | Where it surfaces | Outcome |
|---|---|---|
| Unknown `integration` name, or the platform extra missing on the response-handler Lambda | `IntegrationAdapterFactory.create_outbound` raises `AKConfigError` (`integration/adapter/factory.py:55-58`) or `ImportError` naming the extra (`:65`) | `process_message` raises. `LambdaSQSConsumer.handle` reports the record in `batchItemFailures` (`serverless/core/sqs_consumer.py:58-62`), then after the retries `on_permanent_failure` hits the same error, logged at ERROR. The pipeline behaves identically, through `ConsumerLoop` |
| Platform API error in `deliver` | the adapter coroutine raises | Retried; then `deliver_error` is attempted once on permanent failure, and a failure there is logged, never re-raised |
| Platform API error in `deliver_error` for a status >= 400 reply | built-in adapters catch and log it (e.g. `integration/slack/adapter.py:268-272`) | Not retried: the record is deleted with no user notice, as in the pipeline. A bring-your-own adapter that raises gets the retries |
| Malformed output body | `_decode_body` raises `JSONDecodeError` | Retried; the permanent-failure branch needs no body, so the user still gets the error message |
| More than 10 SQS message attributes | `send_message` raises `InvalidParameterValue` in the runner, after the agent ran | Retried, so the agent runs again. Unreachable with the built-ins (at most 9); a bring-your-own adapter with 7 or more `reply_*` keys can reach it (design Non-goals) |
| Integration record fails on the stream runner | raised from the delegated `ServerlessAgentRunner.process_message` | `ServerlessStreamAgentRunner.handle` puts it in `batchItemFailures` |
| No group id on a permanently failed record | `.get("MessageGroupId")` returns `None` | The branches run with `session_id=None`, where before there was a `KeyError` |
| `LambdaWebhookGuard` check fails | `TypeError` or `AKConfigError` from the `LambdaWebhookHost(...)` constructor, at module import | The Lambda's init fails, and every invocation returns the init error until the configuration is fixed. Nothing is registered for that host |
| Queue mode with no response store | `ValueError` from `_get_router()` (`rest_lambda.py:54-57`), on the first `Lambda.register` | The same init failure, with today's message |
| Request handler without `execution.queues.output.url` (a deployment that skips §14 item 3) | `QueueTransportFactory.create()` raises `AKConfigError` when `WebhookRESTRequestHandler(...)` is constructed (`pipeline/transport/base.py:145-146`), before the host is built | The same init failure; the message names both URLs |
| Webhook path in `gateway_endpoints` and the authorizer, but not registered (or registered on another path) | the router finds no route (`rest_lambda.py:409-411`) | `Lambda.handler`'s catch-all: a 500 with `Custom handler error: No registered route …` (`aklambda.py:84-91`), unchanged |
| Adapter `verify` rejects (bad signature or token) | `HTTPException(403)` (`meta.py:35`, `:40`; `telegram/adapter.py:124`) | 403 with `{"detail": ...}`; nothing acknowledged or enqueued |
| Bolt rejects a Slack signature | Bolt's own response (`slack_bolt/middleware/request_verification/request_verification.py:55-56`) | 401 with `{"error": "invalid request"}`, passed through |
| Teams rejects an activity | `HTTPException(401)` (`teams/adapter.py:165-167`) | 401 with `{"detail": "Unauthorized"}` |
| Enqueue fails (SQS unreachable) | `WebhookRESTRequestHandler.handle` logs and re-raises (`webhook.py:74-78`) | 500 `Internal Server Error`, logged by the host too, so the platform retries. Its dedup id makes the retry safe (`producer.py:88`) |
| Malformed event (bad base64 body) | `to_request` raises | 500 `Internal Server Error`, logged |
| An endpoint returns a streaming response | `_proxy_response` raises `TypeError` | 500 `Internal Server Error`, logged |
| Slack delivery marked `x-slack-retry-reason: http_timeout` | `SlackInboundAdapter.parse` returns empty before Bolt verifies (`slack/adapter.py:73-79`) | 200 `{"status": "ok"}` and nothing enqueued. This is today's behaviour on every surface; a forged header gains nothing |
| `bypass` raises | `_bypass_policy` catches it | WARNING log; the request takes the normal path, and a request with no token gets a Deny |
| Authorizer TTL above 0 with a bypass | API Gateway answers 401 before calling the authorizer | Never reaches AK. The docs name this symptom |
| Webhook route registered and in the gateway, but not in the bypass | the validator sees no or a foreign token | Deny, so 401/403, with the validator's own log line |

All new exception scopes are listed above: the host's `except Exception` (every failure becomes a
proxy response, since an unhandled exception would become `Lambda.handler`'s leaking 500), and
`_bypass_policy`'s. `IntegrationDelivery`, `WebhookRouteMatcher` and `LambdaWebhookGuard` catch nothing.

## Testing

Run everything with `cd ak-py && uv run pytest`.

Shared patterns:
- `AK_CONFIG_PATH_OVERRIDE` plus `AKConfig._reset()` for config (`ak-py/tests/test_integration_webhook_handler.py:78-89`).
- `IntegrationAdapterFactory.reset()`, then `_cache[name] = fake`, to inject an outbound adapter
  (`:84-85`).
- `monkeypatch.setenv` for the three base-path variables (`ak-py/tests/test_lambda_router.py:11-19`).
- Lambda-shaped SQS records built by private helpers in each file, as in
  `test_serverless_status_propagation.py:24-39`.
- Every test that touches `Lambda` resets `Lambda._router` and `Lambda._config`, and every host test
  resets `LambdaWebhookHost._loop`.
- Building a host runs its guards, so `test_lambda_webhook_host.py` and `test_lambda_webhook_parity.py`
  set a deployment the host accepts in an autouse fixture: `AK_EXECUTION__MODE=rest_async`,
  `AK_EXECUTION__QUEUES__TYPE=sqs` and the three base-path variables. Their deliveries still go to
  `InMemoryTransport` producers passed to the handler.

### New: `ak-py/tests/test_pipeline_integration_delivery.py`

| Test | Asserts |
|---|---|
| `test_integration_of` | the name when set; `None` when absent, empty, or not a `str` |
| `test_routing_attributes_pick_integration_and_reply_prefix_only` | `request_id`, `user_id`, `status_code` and `endpoint_url` are excluded; values become `str` |
| `test_reply_context_strips_the_prefix` | `{"reply_channel": "C9"}` becomes `{"channel": "C9"}` |
| `test_deliver_sends_the_result_text` | `deliver` gets `AgentReplyText(response="hi")` and the stripped context |
| `test_deliver_on_error_status_sends_the_generic_message` | 400 and 500 send `deliver_error(ERROR_MESSAGE, …)`; the raw error is in the ERROR log (`caplog`), not in the reply |
| `test_non_dict_and_missing_bodies` | `"plain"` becomes `{"result": "plain"}`; `None` becomes `""` |
| `test_delivery_failure_propagates` | a raising adapter makes `deliver` raise |
| `test_deliver_permanent_failure` | `deliver_error(ERROR_MESSAGE, context)` |
| `test_unresolvable_adapter_raises` | `AKConfigError` for `"carrier-pigeon"` |
| `test_module_does_not_import_integration` | the `sys.modules` isolation pattern (`ak-py/tests/test_aws_lazy_exports.py:13-28`): importing `agentkernel.pipeline.integration_delivery` loads no `agentkernel.integration` module |

### New: `ak-py/tests/test_serverless_integration_delivery.py`

**Patch targets:**
- `agentkernel.deployment.aws.serverless.akagentrunner.SQSHandler.send_message_to_output_queue`
- `ServerlessAgentRunner._get_chat_service`
- `agentkernel.deployment.aws.serverless.akresponsehandler.AKConfig` for the mode
- `ResponseHandler._get_response_store` and `ResponseHandler._get_base_ws_handler`

| Group | Tests |
|---|---|
| Runner | `requests=body.requests` reaches `process_chat_request`. `integration` and every `reply_*` are on the output's custom attributes. A non-integration record's output attributes are exactly `status_code`, plus `endpoint_url` when present. The permanent-failure 500 carries the routing attributes |
| Stream runner | WebSocket traffic passes `requests=body.requests` to `process_stream_chat_sync`. An integration record with no `endpoint_url` goes to `ServerlessAgentRunner.process_message`: the stream chat is never called, and one output send carries `status_code`. The same holds for `on_permanent_failure` |
| Response handler | Parametrized over `rest_sync`, `rest_async`, `async` and `stream`: delivery with the stripped context, and neither the store nor the WebSocket handler touched. 4xx/5xx sends `deliver_error`. An unparseable `status_code` takes the 200 path. A raising adapter puts the record in `handle(...)["batchItemFailures"]` |
| Permanent failure | With `integration`: `deliver_error`, and an adapter exception is swallowed. Without it, on a record whose group id is **only** in `attributes.MessageGroupId`: REST modes store a 500 record carrying that `session_id` on the record and in its body; `async` broadcasts `SYSTEM_RESPONSE`; `stream` broadcasts an error `STREAM_CHUNK` with that `session_id`. This is the regression test for the `KeyError` |
| Round trip | See below |
| End to end (part 2) | See below |
| Import hygiene | The `sys.modules` isolation pattern: importing both serverless modules loads no `agentkernel.integration` module |
| Missing extra | `integration: slack` with `sys.modules["agentkernel.integration.slack.adapter"] = None`: `handle()` returns the record in `batchItemFailures`, the log names `agentkernel[slack]`, and the store is untouched |

**Round trip** (the test that would have caught the bug):
1. An `InboundRequest` with Slack's five-key reply context (`channel`, `thread_ts`, `user`, `ack_ts`,
   `ack_channel`) goes through `IntegrationProducer(SQSTransport(input_url=..., output_url=...))`.
   - Only `boto3.client` is patched, so the real `SQSTransport.send` builds the kwargs
     (`pipeline/transport/sqs.py:240-247`). That is the transport the webhook host uses on Lambda,
     and a different send path from the chat route's `SQSHandler`.
2. The captured `send_message` kwargs (`MessageBody`, `MessageAttributes` with their `DataType`,
   `MessageGroupId`, `MessageDeduplicationId`) become a Lambda input record: `body`, `messageAttributes`
   in the event-source-mapping shape, and `attributes.MessageGroupId`.
3. `ServerlessAgentRunner.process_message(record)` runs with the chat service faked.
   - Only `SQSHandler.get_sqs_client` and `get_output_queue_url` are patched, so the real
     `send_message_to_output_queue` builds the attributes. Its `request_id`/`user_id` stamping and
     the duplicate check both run.
   - The test asserts `len(send_message.call_args.kwargs["MessageAttributes"]) <= 10`.
4. The captured `send_message` kwargs become a Lambda output record, and `ResponseHandler.process_message`
   runs on it.
5. The recording adapter must receive the agent's text and the original five-key context.

**End to end** (design, Part 2):
1. A signed Slack `message` event, as an API Gateway event, goes to `Lambda.handler`, with
   `host = LambdaWebhookHost(WebhookRESTRequestHandler(SlackInboundAdapter()))` and
   `Lambda.register("/slack/events", method="POST")(host.handle)`.
   - The handler builds its own producer, so this also proves construction from `execution.queues`:
     `type: sqs` plus both URLs, set as `AK_EXECUTION__QUEUES__*` the way Terraform sets them.
   - `boto3.client` is patched, as in the round trip.
   - `AsyncWebClient.auth_test` is stubbed as in `test_slack_integration.py:175-186`.
   - `execution.mode: rest_async`, with the three base-path variables set.
   - The router's `DefaultEndpointsHandler` is faked as in `test_lambda_router.py:32-45`, so no
     response store is reached.
2. The captured `send_message` kwargs then continue through steps 2-5 of the round trip.
3. The 200 response and the recording adapter's received text are both asserted.

### New: `ak-py/tests/test_lambda_event_translator.py`

- **Bodies:** a base64 body and a plain body each reach `await request.body()` byte-exact, including
  a non-ASCII UTF-8 payload and a binary base64 one; a missing body is `b""`.
- **Headers:** `multiValueHeaders` with a repeated header yields both values from
  `request.headers.getlist(...)`; lookup is case-insensitive (`X-Hub-Signature-256` and
  `x-hub-signature-256`).
- **Query:** `multiValueQueryStringParameters` with a repeated key yields both values.
- **Single-value only:** an event with only `headers` and `queryStringParameters` still yields them.
  A Meta handshake in that shape, through `WhatsAppInboundAdapter.challenge`, returns the challenge
  `int`.
- **Scope:** method, path, scheme and server come from the event, with and without the forwarded
  headers.
- **Responses:**
  - a Starlette `Response` with two `set-cookie` headers keeps its status, both headers and its
    bytes;
  - a dict and an `int` give FastAPI's JSON bytes with status 200 (compared against a one-route
    FastAPI app through `TestClient` returning the same value);
  - a non-UTF-8 body is base64 with `isBase64Encoded: true`;
  - a `StreamingResponse` raises `TypeError`.
- **Errors:**
  - `HTTPException(403, detail="x", headers={"X-A": "1"})` gives 403, the header, and `{"detail": "x"}`;
  - `HTTPException(304)` has no body;
  - `RuntimeError("secret")` gives 500 `Internal Server Error`, and `secret` appears in the log, not
    in the body.

### New: `ak-py/tests/test_lambda_webhook_host.py`

- **Registered routes** (`TestRegisteredRoutes`): each test registers `host.handle` or
  `host.challenge` with `Lambda.register`, as an application does, and drives `Lambda.handler`:
  - `POST /api/v1/fake/webhook` reaches the host and not the chat route, and the delivery is
    enqueued;
  - a rejected delivery keeps its 403 and `{"detail": ...}` body, with nothing enqueued;
  - `GET` with `hub.challenge` on the registered challenge route is answered by the adapter's
    `challenge`.
- **Loop:**
  - two invocations run on the same event loop (an adapter records `asyncio.get_running_loop()`);
  - `asyncio.get_event_loop_policy()` shows no current loop was set on the thread;
  - a closed loop is replaced.
- **Guards** (`TestGuards`), each raised by constructing `LambdaWebhookHost(...)` directly, from the
  fixture's deployable environment with one setting changed:
  - an unset transport type (which resolves to `in_memory`), an `in_memory` one and a `kafka` one
    raise `AKConfigError` naming `queue_mode` and `execution.queues.type`;
  - `async`, `stream` and an unset mode raise `AKConfigError`;
  - each missing base-path variable raises `AKConfigError` naming it;
  - WhatsApp, Messenger, Instagram and Telegram (parametrized) with the secret unset raise
    `AKConfigError` naming `whatsapp.app_secret` and the rest; with it set, the host is built;
  - `SlackInboundAdapter()` with `SLACK_SIGNING_SECRET` unset, and `TeamsInboundAdapter()` with no
    `teams.app_id`, raise `ValueError` at construction;
  - `LambdaWebhookHost(AgentRESTRequestHandler())` raises `TypeError`.
- **Host mirrors FastAPI.** The cases in `ak-py/tests/test_integration_webhook_handler.py:103-189`
  are replayed through `LambdaWebhookHost` with the same `FakeInboundAdapter`/`FakeOutboundAdapter`
  shapes:
  - the delivery is enqueued, and a batched delivery enqueues every message;
  - the acknowledgement extends the reply context;
  - an ignored delivery answers `{"status": "ok"}` and enqueues nothing;
  - an SDK-owned response is returned verbatim (status 201);
  - a verification failure is a 403 with nothing enqueued or acknowledged;
  - an enqueue failure is a 500 with the generic body.

### New: `ak-py/tests/test_lambda_webhook_parity.py`

For each built-in webhook adapter, the same delivery goes to two places: an API Gateway event through
`LambdaWebhookHost`, and an HTTP request through the FastAPI route (`TestClient` over
`WebhookRESTRequestHandler.get_router()`). Each case asserts the same status, the same body bytes, and
the same enqueued message (body and attributes), both on separate `InMemoryTransport` instances.

| Adapter | Where the deliveries come from | Cases |
|---|---|---|
| WhatsApp, Messenger, Instagram | the `IntegrationAdapterContract` subclasses' `valid_delivery`/`ignorable_delivery`/`unauthentic_delivery` (`ak-py/tests/test_integration_adapter_contract.py:53-145`). A helper reads the fake request's `await body()`, `headers` and `query_params` (`:23-35`) into both the event and the `TestClient` call | valid; unauthentic (403); ignored; handshake (`hub.mode=subscribe`, the configured token, `hub.challenge=12345` returns `12345`; a wrong token gives 403) |
| Telegram | the contract subclass (`:148-172`), read the same way | valid; unauthentic (403); ignored |
| Slack | an HTTP-level signed delivery, built with the helper pattern at `test_slack_integration.py:159-173`, with `auth_test` stubbed (`:175-186`) | valid `message` event; unsigned (401 from Bolt); `url_verification` (Bolt's challenge body) |
| Teams | a Bot Framework activity body with `BotFrameworkAdapter.process_activity` stubbed on the adapter instance to call the turn handler, or to raise `PermissionError` | valid; unauthentic (401) |

The contract subclasses are imported from `test_integration_adapter_contract`, so their deliveries
have one definition. Slack's and Teams' hooks can't be reused, because they bypass the SDK dispatch
(`:239-248`, `:314-319`).

### New: `ak-py/tests/test_authorizer_webhook_bypass.py`

**`WebhookRouteMatcher`:**
- `for_integrations("slack")` matches `POST /api/v1/slack/events` under the base-path variables, and
  returns `"slack"`.
- The base path is stripped as the router strips it: for the same variables and path, the matcher's
  stripped path equals what `RESTLambdaRouter.dispatch` looks up (`rest_lambda.py:394-401`).
- `GET /api/v1/slack/events` (a method the route does not declare) returns `None`, and so does a path
  with a trailing `/`.
- WhatsApp's `GET` on its challenge path matches.
- With no base-path variables, the gateway path returns `None` (fails closed).
- An unknown name raises `AKConfigError` listing the built-ins, and no name raises `ValueError`.
- A bring-your-own `WebhookRoute("byo", "/byo/hook")` works through the constructor.
- A header such as `X-Slack-Signature` on a chat path changes nothing.

**`APIGatewayAuthorizer(bypass=...)`:**
- A header-less webhook event on a declared route gets an Allow for its exact `methodArn` with
  principal `integration:slack`, and the validator is not called (`MagicMock` validator,
  `assert_not_called`).
- A chat route with a spoofed `X-Slack-Signature` and no token gets a Deny.
- An undeclared method on a webhook path goes to the validator.
- A raising bypass falls through to the validator.
- A `True`-returning predicate gets principal `integration`.
- An event with no `methodArn` falls through.

**Unmodified:** `ak-py/tests/test_akauthorizer.py`, which proves the no-bypass path.

### New: `ak-py/tests/test_packaging_extras.py`

This is a static guard, reading `ak-py/pyproject.toml` with `tomllib`:
- each of `slack`, `teams`, `telegram`, `whatsapp`, `messenger` and `instagram` names `fastapi`;
- `slack` names `aiohttp`;
- `gmail` does not name `fastapi`.

The clean-environment check itself (below) is a plan verification step, not a unit test: the
development venv has every extra installed.

### Edited

- **`integration/adapter/testing.py`:** the new contract test
  `test_a_builtin_is_served_where_the_authorizer_expects` (§6). It runs for all seven subclasses in
  `test_integration_adapter_contract.py`, skipping Gmail (a poller) and any non-built-in name.
- **`ak-py/tests/test_aws_lazy_exports.py`**, four new tests, each using the file's isolation pattern
  (`:13-28`):
  - importing `agentkernel.aws` and touching `Lambda` loads neither `fastapi`, `starlette`, nor
    `agentkernel.deployment.aws.serverless.core.webhook_host`;
  - touching `LambdaWebhookHost` through `agentkernel.aws` resolves it, loading
    `agentkernel.deployment.aws.serverless.core.webhook_host`
    (`test_touching_the_webhook_host_through_aws_resolves_it`);
  - importing `APIGatewayAuthorizer` and `agentkernel.integration.adapter.WebhookRouteMatcher` loads
    neither `fastapi` nor `slack_bolt`;
  - importing `agentkernel.integration.adapter.webhook` loads neither `agentkernel.api.http` nor
    `uvicorn`.
- **`ak-py/tests/test_akagentrunner_stream.py`:** the fakes of `process_stream_chat_sync` gain
  `requests=None` (their signature predates the real method's `requests` keyword,
  `core/chat_service.py:646-650`). No assertion changes.

### Existing tests that must pass unmodified

These prove there is no behaviour change on the paths that should have none:
- the pipeline: `test_pipeline_response_handler.py`, `test_pipeline_agent_runner.py`,
  `test_integration_roundtrip.py`, `test_thread_pipeline_recording.py`
- the serverless consumers: `test_serverless_status_propagation.py`,
  `test_serverless_agent_runner_schedule.py`, `test_akresponsehandler.py`
- the webhook and adapters: `test_integration_webhook_handler.py`, `test_slack_integration.py`
  (including `:216-234`, which pins Q4's timeout drop), and the other per-platform files
- the Lambda and API layers: `test_lambda_router.py`, `test_akauthorizer.py`, `test_api_http.py`

### Clean-environment verification (plan step)

- `uv venv` with Python 3.12, then install `ak-py[aws,slack]`.
- Then:
  - `IntegrationAdapterFactory.create_outbound("slack")` succeeds;
  - `from agentkernel.integration.adapter.webhook import WebhookRESTRequestHandler` succeeds;
  - `"uvicorn" not in sys.modules`.
- Repeat for `ak-py[aws,whatsapp]` and `ak-py[aws,teams]`.

### Example smoke test: `examples/aws-serverless/slack-openai/lambda_test.py`

This runs against the deployed stack (`AK_TEST_ENDPOINT`) and needs no Slack workspace, only the
signing secret the stack was deployed with:
1. **The chat route still authorizes:** a request with no token gets 401 or 403, and one with the
   demo token gets an answer.
2. **The bypass and Bolt are reached:** an unsigned `POST .../slack/events` with no
   `Authorization` gets Bolt's 401 `{"error": "invalid request"}`, not API Gateway's
   `{"message": "Unauthorized"}`.
3. **The whole edge works:** a `url_verification` signed with the deployed secret gets 200 and its
   challenge.

---

## Docs and skills

The plan orders these; they are listed here so none is missed.

- **`docs/docs/deployment/aws-serverless.md`:** a new "Messaging integrations" section, placed after
  "Scheduling (EventBridge Scheduler)" (`:1204`). It covers:
  - **Delivery:** the agent runner uses the prebuilt list and copies the return address; the
    response handler delivers whatever the mode; `stream` gives one reply.
  - **Packages:** `agentkernel[aws,<platform>]` for the request- and response-handler packages, and
    the platform credentials in both Lambdas' `environment_variables`.
  - **Receiving:** `LambdaWebhookHost(WebhookRESTRequestHandler(...))` at module scope, its `handle`
    registered with `Lambda.register` on the adapter's `webhook_path` (and its `challenge` on the
    `challenge_path`, for WhatsApp, Messenger and Instagram), and the webhook routes in
    `gateway_endpoints`.
  - **Behind an authorizer:** `bypass=WebhookRouteMatcher.for_integrations(...)`, and
    `result_ttl_in_seconds = 0` with the reason.
  - **The three places an integration is declared,** and the symptom when they drift (the design's
    list).
  - **The verification settings** `LambdaWebhookHost` requires, and that Slack and Teams fail at
    construction.
  - **Cold starts versus Slack's 3 s:**
    - keep the request-handler package slim;
    - the authorizer call adds to the budget;
    - provisioned concurrency or a warm-up, configured outside the module for now;
    - a timeout retry is dropped at the edge, so the user still sees one "thinking…" and one reply.
  - **Stores:** a response store is still required (`create_dynamodb_response_store = true`), and
    attachments need `multimodal.enabled` with a shared store. The DynamoDB table now reaches the
    request handler; Redis or Valkey needs network reach from it.
  - **REST modes only.**

  The "Cold Start Mitigation" subsection (`:1257-1261`) links to it.
- **`docs/docs/advanced/queue-mode-guide.md`,** "How It Works in Lambda (Serverless)" (`:375`): one
  bullet each on integration dispatch and on `LambdaWebhookHost`, linking the section.
- **`docs/docs/integrations/overview.md`** (`:77-79`): serverless hosting through `LambdaWebhookHost`
  and `Lambda.register`, linking the section.
- **`docs/docs/integrations/telegram.md:287`, `messenger.md:505`, `instagram.md:530`:** link the
  section instead of the bare examples folder.
- **`ak-deployment/ak-aws/serverless/README.md`:** the two Terraform behaviours in §14.
- **`.agents/skills/ak-dev-architecture/SKILL.md`:**
  - the `agent_runner.py` and `response_handler.py` rows (`:773-774`), plus a new
    `integration_delivery.py` row;
  - coupling rule 2 (`:799`): the lazy-import site becomes `IntegrationDelivery._outbound_adapter`;
  - the `ServerlessAgentRunner` row (`:1014`): integration forwarding and the STREAM delegation;
  - the messaging "Hosting" bullet (`:546`): `LambdaWebhookHost` registered with `Lambda.register`,
    the route table, and `WebhookRouteMatcher`;
  - the `agentkernel.api` lazy exports next to the existing lazy-export notes.
- **`.agents/skills/ak-dev-testing-conventions/SKILL.md`:** rows for the seven new test files, and
  the `test_aws_lazy_exports.py` additions.
- **`.agents/skills/ak-dev-new-messaging-integration/SKILL.md`:**
  - the hosting table (`:29-36`) gains the Lambda row;
  - step 2's `webhook_path` comes from `BUILTIN_WEBHOOK_ROUTES` for a built-in;
  - step 7 adds the route-table entry;
  - a note on `missing_verification_settings`;
  - the checklist (`:300`) gains both.
- **Bundled skills:**
  - `skills/ak-add-integration/SKILL.md` gains the Lambda wiring beside each `IOHandler.run` snippet
    (`:68-73` onwards), or once in Step 3;
  - `skills/ak-cloud-deploy/SKILL.md`, AWS Serverless (`:300`), gains the webhook routes, the bypass
    and TTL 0.
- **Before merge,** confirm with the `ak-dev-sync-docs-from-branch` and `ak-dev-sync-skills-from-branch`
  flows.

---

## Traceability

| Design requirement | Spec section | Proven by |
|---|---|---|
| `IntegrationDelivery`: one class, attribute mappings, interface | §1 | `test_pipeline_integration_delivery.py` |
| Moved unchanged; status parsing per caller | §1, §2, §5 | Pipeline tests unmodified; serverless unparseable status gives 200 |
| Coupling rule; no per-message state | §1, [Concurrency](#concurrency) | `test_module_does_not_import_integration` |
| `ServerlessAgentRunner`: prebuilt list, return address, permanent failure, signatures | §3 | Runner group; round trip |
| `ServerlessStreamAgentRunner` | §4 | Stream-runner group; `test_akagentrunner_stream.py` |
| Serverless `ResponseHandler`: integration first, retries, permanent failure, lazily built | §5 | Response-handler and permanent-failure groups |
| Permanent-failure `KeyError` fix | §5 | Permanent-failure group (system group id only) |
| Pipeline refactor only | §2 | Pipeline tests unmodified |
| SQS 10-attribute limit | §3, [Error handling](#error-handling) | Round trip `<= 10` |
| `LambdaWebhookHost`: wraps, served through `Lambda.register`, routing unchanged | §9, §10 | Registered routes; host mirrors FastAPI |
| `WebhookRESTRequestHandler.adapter` | §7 | `test_the_webhook_handler_exposes_its_adapter`; host guards (verification settings) |
| `LambdaEventTranslator`: body, headers, query and the single-value fallback, responses, errors | §8 | `test_lambda_event_translator.py`; parity |
| One event loop per environment | §9 | Host loop tests |
| Public entry point: `LambdaWebhookHost` registered with `Lambda.register`, webhook handlers only, lazily exported from `agentkernel.aws` | §9, §10, §13 | Guards (`TypeError`); registered routes; lazy-export tests; end to end |
| Authorizer bypass: first, exact `methodArn`, principal, no claims | §12 | `test_authorizer_webhook_bypass.py` |
| `WebhookRouteMatcher`: path and method only, strips like the router, no adapter imports | §11 | Matcher tests; lazy-import test |
| Built-in routes without drift | §6 | Contract test `test_a_builtin_is_served_where_the_authorizer_expects` |
| TTL 0 with a bypass | §12, §15, docs | Example `deploy/main.tf`; smoke test 2 |
| Q4: no code change; timeout retry already dropped | design Q4 | `test_slack_integration.py:216-234`, unmodified |
| Fail-fast guards: secrets, transport, mode, base path, response store | §9, §10 | Host guard tests |
| No new `AKConfig` | [Config changes](#config-changes) | Review |
| Packaging: FastAPI, aiohttp, lazy `agentkernel.api` | §13 | `test_packaging_extras.py`; lazy-export tests; clean-environment step |
| Terraform: routes, no per-route auth, authorizer base path, TTL, attachment table, output queue URL, credentials | §14 | `terraform validate`; plan review; end to end (construction from `execution.queues`); example smoke test |
| Compatibility | [Behavioural changes](#behavioural-changes) | Unmodified suites |
| Example | §15 | `lambda_test.py` |
| Tests (design list) | [Testing](#testing) | — |
| Docs and skills | [Docs and skills](#docs-and-skills) | Sync flows before merge |
