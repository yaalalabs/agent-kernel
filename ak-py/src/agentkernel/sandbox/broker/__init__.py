"""Sandbox broker: decouples the agentic system from sandbox execution.

The broker's message models and ``ExecutionBroker`` ABC live in ``base``; the
flavor-independent execution engine in ``worker`` (``BrokerWorkerCore``); and the
individual flavors in their own modules (``embedded`` and ``thread`` here; the AWS
``sqs`` flavor lands in a later iteration). Flavors are resolved lazily by
``ExecutionBrokerFactory`` so importing this package pulls in no flavor by default.
"""
