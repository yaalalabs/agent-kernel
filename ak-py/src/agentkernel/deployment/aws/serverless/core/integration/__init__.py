"""The Lambda side of the features in ``agentkernel/integration/``.

Messaging webhooks (``integration/adapter``) and conversation threads (``integration/thread``)
ship FastAPI-style request handlers that the REST API mounts on uvicorn. This package serves the
same handlers from the request-handler Lambda, the function behind API Gateway.

A *host* is an object that runs an existing handler inside that Lambda; it is not a server or a
machine. It is needed because the handlers expect a Starlette ``Request``, are ``async`` and raise
``HTTPException``, while Lambda calls a plain function with an API Gateway event dict and expects a
proxy-response dict back. A host translates the event to a request, awaits the handler, and
translates its answer, or the exception, back to a proxy response.

An application builds a host at module scope in its request-handler file and registers the host's
``(event, context)`` methods with ``Lambda.register``. Creating the host is what switches the feature
on: its constructor runs the cold-start checks and wires whatever the feature needs.

- ``base.py``: ``LambdaHost`` and ``LambdaHostGuard``, the shared host and cold-start checks.
- ``event_translator.py``: ``LambdaEventTranslator``, API Gateway event <-> Starlette.
- ``webhook.py``: ``LambdaWebhookHost``, a messaging platform's webhook delivery and handshake routes.
- ``thread.py``: ``LambdaThreadHost``, the thread read routes and the chat route's thread recording.

Hosts run in the request-handler Lambda only, never in the agent runner.

Every module here imports FastAPI and Starlette at module scope, so this package imports nothing
and ``serverless.core`` does not import it. The hosts are reached only through the lazy exports in
``deployment/aws/__init__.py``, which keeps ``from agentkernel.aws import Lambda`` FastAPI-free for
applications that use neither feature.
"""
