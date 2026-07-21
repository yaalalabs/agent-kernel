"""Sandbox broker: decouples the agentic system from sandbox execution.

The broker's message models and ``SandboxBroker`` ABC live in ``base``; the
flavor-independent execution engine in ``worker`` (``BrokerWorkerCore``); and the
individual flavors in their own modules (``embedded`` here; ``thread`` and the AWS
``sqs`` flavor land in later iterations). Flavors are resolved lazily by
``SandboxBrokerFactory`` so importing this package pulls in no flavor by default.
"""
