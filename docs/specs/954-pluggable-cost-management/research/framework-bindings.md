# Framework bindings for the gateway client

Where each framework lets Agent Kernel add attribution headers to each LLM call, and whether Python contextvars (`Session.current()`, `Agent.current()`) reach the code that makes the call.

This was checked on 2026-11-17 by a delegated pass that read the source of the `ak-py/uv.lock` versions, from the uv cache and `ak-py/.venv`. **V** = read in source. **U** = not read in source.

## Verdict

| Framework | Binding seam | Granularity | Context propagation | Caveats |
|---|---|---|---|---|
| openai-agents 0.20.0 | `LitellmModel._merge_headers(model_settings)` (`agents/extensions/models/litellm_model.py:890-891`) returns `{**HEADERS, **extra_headers, **HEADERS_OVERRIDE.get()}`, passed as `extra_headers` to `litellm.acompletion` (`:654`, `:670`). The `HEADERS_OVERRIDE` ContextVar is SDK-internal (`agents/models/chatcmpl_helpers.py:37`). **V** | per call | async **V** | none |
| google-adk 2.8.0 | `LiteLlm.llm_client: LiteLLMClient` (`google/adk/models/lite_llm.py:3042`); `LiteLLMClient.acompletion(model, messages, tools, **kwargs)` (`:868`), the only one called (`:3280`, `:3413`). Merges `extra_headers` from `llm_request.config.http_options.headers` (`:3145-3155`). **V** | per call | async **V** | merge with the existing headers |
| smolagents 1.26.0 | `LiteLLMModel._prepare_completion_kwargs(...)` (`smolagents/models.py:502`), used in `generate` (`:1274`) and `generate_stream` (`:1317`). **V** | per call | AK calls `agent.run` via `asyncio.to_thread` (`ak-py/src/agentkernel/framework/smolagents/smolagents.py:170`); parallel tools and managed agents copy context (`smolagents/agents.py:1426-1430`). **V** | none |
| crewai 1.15.18 | `LLM._prepare_completion_params(...)` (`crewai/llm.py:749-799`), used by `call` (`:1884`) and `acall` (`:2023`) before `litellm.completion` / `acompletion`. **V** | per call | AK calls `kickoff_async` (`framework/crewai/crewai.py:384`), which uses `asyncio.to_thread` (`crewai/crew.py:1160`); async tasks use `copy_context().run` (`crewai/task.py:617-621`); parallel tools copy context (`crewai/agents/crew_agent_executor.py:768-771`). **V** | `LLM.__new__` returns a native-provider model unless `is_litellm=True` (`crewai/llm.py:394-517`); `__copy__` / `__deepcopy__` rebuild a plain `LLM` (`:2561`, `:2622`), used only by `train` / `kickoff_for_each`; sync tools via `run_in_executor` lose context (`crewai/tools/structured_tool.py:410`) |
| agent-framework-core 1.24.0 | No LiteLLM client in core. A `BaseChatClient` subclass implements `_inner_get_response(messages, stream, options, **kwargs)`; `Agent.run(client_kwargs=...)` reaches it (`agent_framework/_agents.py:1188-1279`, `_clients.py:485`). **V** | per call | async; sync tools via `asyncio.to_thread` (`_tools.py:914`). **V** | `agent-framework-openai` is not locked |
| LangChain | `ChatLiteLLM` is gone from `langchain-community` 0.4.2 (no litellm entry in RECORD). `langchain-litellm` is not in `uv.lock`. **V** Its seam (`model_kwargs`, `_default_params`, `_generate` / `_agenerate`) is **U** | per call (**U**) | **U** | new optional dependency |
| claude-agent-sdk 0.2.179 | `ClaudeAgentOptions.env` (`claude_agent_sdk/types.py:2492`) is merged over `os.environ` when the CLI subprocess starts (`_internal/transport/subprocess_cli.py:819-824`). The bundled CLI reads `ANTHROPIC_CUSTOM_HEADERS`. **V** Value format and `ANTHROPIC_BASE_URL` routing: **U** | per run: AK starts one `ClaudeSDKClient` per run (`framework/claude/claude.py:674`, `:748`, `:809`) | n/a | `request_id` identifies the run, not each call |

## LiteLLM itself

- `acompletion` runs `completion` in an executor inside `contextvars.copy_context()` (`litellm/main.py:647-650`), and `extra_headers` is a direct parameter (`:445`, `:604`). Headers built in the caller's context survive. **V** (litellm 1.95.1)
- `litellm.headers` is a module-level global (`litellm/__init__.py`), shared by concurrent runs, so it is never used for per-run headers. **V**
