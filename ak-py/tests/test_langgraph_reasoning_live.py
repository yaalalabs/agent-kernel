"""LangGraph reasoning against a REAL reasoning model (spec #523 §10).

The unit suite in `test_langgraph_runner.py` feeds hand-built `AIMessageChunk`s, which pins the mapping
but not the premise: that the model emits a reasoning summary in the first place, and that LangChain
surfaces it in the shape the adapter reads. Both of those are the model provider's and the SDK's
behaviour, and getting them wrong is invisible to a suite that supplies its own chunks — an earlier
attempt at this mapping passed its unit tests while showing nothing at all in a browser.

Skipped unless a model is named, so the normal unit run is unaffected:

    AK_TEST_REASONING_MODEL=gpt-5.6 OPENAI_API_KEY=... \
        uv run --all-extras pytest tests/test_langgraph_reasoning_live.py -q --no-cov

Two things this file has to get right, both of which cost an earlier attempt its verification:

- **`reasoning={"effort": ..., "summary": "auto"}` on the model.** Agent Kernel maps the reasoning
  *summary*; a reasoning-capable model asked for no summary streams none, so the whole chain looks
  broken when nothing is actually wrong with it. Setting `reasoning` also routes `ChatOpenAI` onto the
  Responses API, which is where summaries come from.
- **Bare `StateGraph`, not `create_react_agent`.** The test needs only one model call, so a ReAct loop adds nothing.
  Using a bare graph also avoids unnecessary `langgraph.prebuilt` version coupling. The original workaround is no longer
  required since #586 lifted the `langgraph` pin.

`langchain_openai` is guarded with `importorskip` because ak-py does not depend on it — it arrives only
through `ragas`, the test-judge extra. pytest imports every test module at collection, so an unguarded
import would fail the whole suite rather than this file if that transitive ever moves; the class-level
`skipif` runs too late to help.
"""

import os
from types import SimpleNamespace

import pytest

pytest.importorskip("langchain_openai")

from langchain_core.messages import AIMessageChunk
from langchain_openai import ChatOpenAI
from langgraph.graph import MessagesState, StateGraph

from agentkernel.core import Session
from agentkernel.core.event import MessageStart, ReasoningDelta, ReasoningEnd, ReasoningStart, TextDelta
from agentkernel.core.model import AgentRequestText
from agentkernel.framework.langgraph.langgraph import LangGraphRunner

REASONING_MODEL = os.getenv("AK_TEST_REASONING_MODEL")

# Long enough to need planning, short enough to keep the call cheap. A prompt with nothing to weigh up
# lets a model skip reasoning entirely and answer straight away, which would fail this test for a
# reason that is about the prompt rather than the adapter.
PROMPT = "I have to post a parcel, buy milk, and collect a prescription. Which order, and why? Answer in two sentences."


def _graph(model: ChatOpenAI):
    """A one-node graph that calls the model and appends its reply."""

    async def call_model(state: MessagesState) -> dict:
        return {"messages": [await model.ainvoke(state["messages"])]}

    graph = StateGraph(MessagesState)
    graph.add_node("model", call_model)
    graph.set_entry_point("model")
    graph.set_finish_point("model")
    return graph.compile()


@pytest.mark.skipif(not REASONING_MODEL, reason="AK_TEST_REASONING_MODEL not set: the live reasoning check is opt-in")
class TestLangGraphReasoningLive:
    """The adapter driven end to end against a live model."""

    @pytest.mark.asyncio
    async def test_a_reasoning_summary_reaches_ak_as_reasoning_events(self):
        model = ChatOpenAI(model=REASONING_MODEL, reasoning={"effort": "medium", "summary": "auto"})
        agent = SimpleNamespace(_system_prompt="", agent=_graph(model))

        runner = LangGraphRunner()
        events = [event async for event in runner.stream(agent, Session("live-reasoning"), [AgentRequestText(prompt=PROMPT)])]
        kinds = [event.type for event in events]

        assert isinstance(events[0], ReasoningStart), kinds
        assert any(isinstance(event, ReasoningDelta) for event in events), kinds
        assert any(isinstance(event, ReasoningEnd) for event in events), kinds

        thinking = "".join(event.content for event in events if isinstance(event, ReasoningDelta))
        assert thinking.strip(), "reasoning events arrived carrying no text"

        # The answer still arrives, so the reasoning split did not swallow it.
        answer = "".join(event.content for event in events if isinstance(event, TextDelta))
        assert answer.strip(), kinds

        # Two streams, two ids — a client renders the thinking block separately from the reply.
        thinking_ids = {e.message_id for e in events if isinstance(e, (ReasoningStart, ReasoningDelta, ReasoningEnd))}
        answer_ids = {e.message_id for e in events if isinstance(e, (MessageStart, TextDelta))}
        assert thinking_ids and answer_ids
        assert not (thinking_ids & answer_ids), (thinking_ids, answer_ids)

        # Thinking is bracketed, and closes before the reply opens.
        assert kinds.index("reasoning_end") < kinds.index("message_start"), kinds

    @pytest.mark.asyncio
    async def test_the_model_actually_streams_a_summary_langchain_can_normalise(self):
        """Isolates the premise from the mapping.

        If this fails but the mapping's unit tests pass, the problem is upstream of Agent Kernel — the
        model was not asked for a summary, or the provider changed where it puts one — and no adapter
        change will help. That is the diagnosis the earlier attempt lacked.
        """
        model = ChatOpenAI(model=REASONING_MODEL, reasoning={"effort": "medium", "summary": "auto"})

        found = []
        async for chunk in model.astream(PROMPT):
            assert isinstance(chunk, AIMessageChunk)
            found.extend(block for block in chunk.content_blocks if block.get("type") == "reasoning")

        assert found, "the model streamed no reasoning block; check the model supports summaries"
        assert any(block.get("reasoning") or block.get("summary") for block in found), found
