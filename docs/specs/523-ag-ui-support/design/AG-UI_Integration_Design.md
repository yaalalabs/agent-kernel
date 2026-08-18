# AG-UI Integration Design

## Overview

AG-UI is an event based protocol that standardizes how AI agents connect to user-facing applications. It is built as framework agnostic in its both ends, backend agent and user interface.

This change gives Agent Kernel its own AG-UI surface, alongside the existing protocol surfaces, and widens what Agent Kernel's internal streaming can carry so that the richer information already arriving from agent frameworks reaches the interface instead of being reduced to plain text.

## Motivation

1. Agent Kernel only knows about 3 stages in the Agent's run. They are run finished, here are more texts and run failed. But AG-UI introduces a total of 25 events like this including tool calls, reasoning status, state changes etc. They are required by most of the modern UIs.
2. Currently, these events reported by frameworks are discarded so with this feature we will be able to expose them as well.
3. Two of the six framework adapters (crew ai and smolagents) are documented as unable to stream. Both frameworks have since gained streaming support, so the limit is Agent Kernel's own adapter code rather than the frameworks: full coverage across all six is achievable, not four.

## Functional Requirements

1. A compliant AG-UI client (UI) can start a run against a named agent and receive the resulting event stream, without knowing which agent framework is behind it.
2. The set of agents reachable over AG-UI is discoverable, and lists only agents that can actually serve a run.
3. AG-UI is inert unless explicitly enabled, and can be restricted to a named subset of agents.

## Technical Requirements

1. AG-UI communicates with a series of events. So streaming should be enabled for it to work.
2. The user_id should be obtained from the bearer token. A pluggable authoriser should be provided for custom logic.

## Architecture

![Architecture diagram: Web UI connects bidirectionally to the AG-UI handler. The AG-UI handler writes to an Input Queue, which feeds the Agent Runner. The Agent Runner writes to an Output Queue, which feeds the Response Handler. The Response Handler writes to a Response Store, which the AG-UI handler reads from to respond to the Web UI.](assets/architecture_diagram.png)

The Web UI communicates with the AG-UI handler. Requests flow from the handler into an Input Queue, which is consumed by the Agent Runner. The Agent Runner's output flows into an Output Queue, consumed by the Response Handler, which writes into a Response Store. The AG-UI handler reads from the Response Store to stream responses back to the Web UI.

## Non Goals

1. Tools that run in the user's browser instead of on the server. AG-UI lets an interface offer its own tools. Agent Kernel will ignore them.
2. Saving AG-UI conversations into Agent Kernel's own conversation history.
3. A sample frontend application. Verification is by automated tests against the protocol.
