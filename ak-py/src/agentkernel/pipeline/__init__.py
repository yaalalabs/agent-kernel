"""Unified queue execution pipeline (#495).

Hosts the five-component chat execution pipeline — Request Handler, Input Queue, Agent Runner,
Output Queue, Response Handler — and its supporting pieces (queue transports, response stores,
WebSocket delivery, ThreadRunner). Populated incrementally; see
docs/specs/495-onprem-kubernetes/plan.md for the iteration order.
"""
