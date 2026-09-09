# Prior art: how existing agent frameworks abstract code-execution sandboxing

Research date: 2026-07-14. Sources are primary (framework source code, official docs, GitHub
issues) fetched directly; versions/commits are noted per section since several of these APIs are
moving targets.

This document surveys nine frameworks/SDKs to extract interface-design lessons for Agent
Kernel's own pluggable `Sandbox` capability (see `SKILL.md` in this directory for the AK-specific
design questions this is meant to answer).

---

## 1. HuggingFace smolagents — `PythonExecutor`

Source: `smolagents/local_python_executor.py` and `smolagents/remote_executors.py`
(v1.26.0, matches current `main`). Repo: https://github.com/huggingface/smolagents

### The interface contract

The entire abstraction is a 3-method ABC plus one shared dataclass:

```python
@dataclass
class CodeOutput:
    output: Any
    logs: str
    is_final_answer: bool


class PythonExecutor(ABC):
    @abstractmethod
    def send_tools(self, tools: dict[str, Tool]) -> None: ...

    @abstractmethod
    def send_variables(self, variables: dict[str, Any]) -> None: ...

    @abstractmethod
    def __call__(self, code_action: str) -> CodeOutput: ...
```

That's the whole contract: push tools in, push variables in, call with code, get back
output/logs/is-it-the-final-answer. Everything else (constructor args, cleanup, install) is
per-backend and NOT part of the ABC — it's discovered via `hasattr`/duck typing rather than
declared.

### Concrete backends

- **`LocalPythonExecutor`** — in-process AST-walking interpreter (not `exec`/`eval`; it
  re-implements a restricted evaluator over the Python AST). Maintains `self.state` dict across
  calls (statefulness is just "don't reset the dict"). Explicitly documents itself as **not a
  security boundary**:

  > "It is not a security sandbox: for isolated execution of untrusted code, use a remote
  > executor."

- **`RemotePythonExecutor(PythonExecutor)`** — shared base for all sandboxed backends. Adds
  concrete (non-abstract) methods on top of the ABC:
  ```python
  class RemotePythonExecutor(PythonExecutor):
      def __init__(self, additional_imports: list[str], logger, allow_pickle: bool = False): ...
      def run_code_raise_errors(self, code: str) -> CodeOutput: raise NotImplementedError
      def send_tools(self, tools: dict[str, Tool]) -> None: ...      # installs tool deps, defines tools remotely
      def send_variables(self, variables: dict[str, Any]) -> None: ...  # serializes + injects
      def __call__(self, code_action: str) -> CodeOutput: return self.run_code_raise_errors(code_action)
      def install_packages(self, additional_imports: list[str]): ...
  ```
  `send_tools`/`send_variables` are implemented once, generically, in terms of
  `run_code_raise_errors` — they literally generate Python source (tool class defs, a
  deserializer) and execute it in the remote namespace. State transfer is "serialize to code
  text, eval it remotely," not a structured RPC.

- **`E2BExecutor(RemotePythonExecutor)`** — wraps `e2b_code_interpreter.Sandbox`, handles both
  E2B SDK v1 (`Sandbox(**kwargs)`) and v2 (`Sandbox.create(**kwargs)`) constructors. Has
  `cleanup()`.
- **`DockerExecutor(RemotePythonExecutor)`** — runs a `jupyter_kernel_gateway` image, drives it
  over a websocket Jupyter protocol; constructor takes `host`, `port`, `image_name`,
  `build_new_image`, `container_run_kwargs`, `dockerfile_content`. Has `cleanup()` and `delete()`.
- **`ModalExecutor(RemotePythonExecutor)`** and **`BlaxelExecutor(RemotePythonExecutor)`** —
  same shape, different remote sandbox provider. `BlaxelExecutor` additionally exposes
  `install_packages` returning the list actually installed.
- **A `WasmExecutor`/`PyodideDenoExecutor` (Pyodide + Deno) existed and was removed** — see pain
  points below.

### Selection / configuration

Backend choice is a **closed string enum on the agent constructor**, not a registry:

```python
executor_type: Literal["local", "blaxel", "e2b", "modal", "docker"] = "local"
```//
```python
def create_python_executor(self) -> PythonExecutor:
    if self.executor_type not in {"local", "blaxel", "e2b", "modal", "docker"}:
        raise ValueError(f"Unsupported executor type: {self.executor_type}")
    if self.executor_type == "local":
        ...
    else:
        remote_executors = {"blaxel": BlaxelExecutor, "e2b": E2BExecutor,
                             "docker": DockerExecutor, "modal": ModalExecutor}
        return remote_executors[self.executor_type](...)
```
There is **no plugin registry** — a third party cannot add `executor_type="my_backend"` without
patching smolagents itself. The escape hatch is the `executor=` constructor parameter, which
accepts **any pre-built `PythonExecutor` instance** — so third parties integrate by subclassing
`PythonExecutor` (or `RemotePythonExecutor`) themselves and passing an instance in, bypassing the
enum entirely. This is a common pattern across several frameworks in this survey: a closed enum
for "blessed" backends, plus an open instance-injection point for everyone else.

### Lifecycle

No `start`/`connect` in the ABC. Cleanup is opportunistic and duck-typed by the *agent*, not the
executor contract:
```python
# CodeAgent.__del__ / cleanup
def cleanup(self):
    if hasattr(self.python_executor, "cleanup"):
        self.python_executor.cleanup()
```
`delete()` (present on Docker/Modal/Blaxel) is a separate, even-less-standardized concept for
tearing down the underlying remote resource (vs. `cleanup()` which may just close a connection).

### Pain points (from GitHub issues, huggingface/smolagents)

- **#2052 / #2096 / #2074** (all about `DockerExecutor`): orphaned containers are left running
  when the Python process dies unexpectedly — no `weakref.finalize`, `atexit`, or signal handler
  registered by default, so a crash leaks a container. Multiple independent PRs proposed the same
  fix, i.e. this is a recurring complaint against ad-hoc lifecycle management.
- **#1750**: `DockerExecutor` opens a **new websocket connection per operation** instead of a
  pooled/persistent connection — a consequence of `run_code_raise_errors` being a plain method
  with no explicit "session" object.
- **#1743**: `DockerExecutor` intermittently fails to initialize ("Connection reset by peer") —
  no readiness/health-check protocol beyond an ad hoc `_wait_for_server`.
- **#1705 / #1738**: users wanted custom Dockerfiles / a file object instead of a fixed image —
  underscores that "backend configuration" (image selection, build context) is exactly the kind
  of thing that varies per backend and doesn't belong in a shared interface.
- **PR #2321 "Remove remote WasmExecutor"**: the Pyodide+Deno in-process Wasm sandbox was
  removed entirely from the supported executor set (kept only as an `.bak.py` file) — a data
  point that a wasm-in-process option was judged not worth maintaining alongside four network-
  hosted alternatives (Blaxel, E2B, Modal, Docker), i.e. maintenance cost of each additional
  backend under one interface is real and framework maintainers do prune backends.

---

## 2. Microsoft AutoGen (`autogen-core`/`autogen-ext`, the 0.4+ rewrite) and AG2 (`ag2`, the community fork of the older 0.2 line)

These forked from the same 0.2 codebase and evolved differently — worth treating separately
because they show **the same domain modeled as sync-Protocol vs. async-ABC-with-lifecycle**, one
generation apart.

### 2a. AG2 (`ag2ai/ag2`, `autogen.coding` — sync `Protocol`)

Source: https://github.com/ag2ai/ag2 tag `v0.14.0`, `autogen/coding/base.py`.

```python
@runtime_checkable
class CodeExecutor(Protocol):
    """(Experimental) A code executor class that executes code blocks and returns the result."""

    @property
    def code_extractor(self) -> CodeExtractor: ...

    def execute_code_blocks(self, code_blocks: list[CodeBlock]) -> CodeResult: ...

    def restart(self) -> None: ...
```
```python
class CodeBlock(BaseModel):
    code: str = Field(description="The code to execute.")
    language: str = Field(description="The language of the code.")

class CodeResult(BaseModel):
    exit_code: int = Field(description="The exit code of the code execution.")
    output: str = Field(description="The output of the code execution.")

class IPythonCodeResult(CodeResult):
    output_files: list[str] = Field(default_factory=list)   # subtype adds generated-file paths

class CommandLineCodeResult(CodeResult):
    code_file: str | None = Field(default=None)              # subtype adds the script path written to disk
```
Note the **capability-specific result subtypes** pattern: the core `CodeResult` only has
`exit_code`/`output`; executors that can do more (produce files, know their script path) return a
richer subclass, and callers use `isinstance`/`hasattr` to access the extra fields. This is a
clean way to let a minimal core grow optional fields without every backend paying for them.

A separate `CodeExtractor` protocol (`extract_code_blocks(message) -> list[CodeBlock]`) is
explicitly decoupled from execution — parsing "message text with fenced code blocks" out of an
LLM response is a different concern from running the blocks, and each executor exposes its own
`code_extractor` (in practice often the same `MarkdownCodeExtractor`).

**Registration is a factory keyed on a config dict, with an escape hatch for pre-built
instances** — this is a very AK-relevant pattern:
```python
class CodeExecutorFactory:
    @staticmethod
    def create(code_execution_config: CodeExecutionConfig) -> CodeExecutor:
        executor = code_execution_config.get("executor")
        if isinstance(executor, CodeExecutor):
            return executor                      # already-built instance: pass through
        if executor == "ipython-embedded":
            from .jupyter.embedded_ipython_code_executor import EmbeddedIPythonCodeExecutor
            return EmbeddedIPythonCodeExecutor(**code_execution_config.get("ipython-embedded", {}))
        elif executor == "commandline-local":
            from .local_commandline_code_executor import LocalCommandLineCodeExecutor
            return LocalCommandLineCodeExecutor(**code_execution_config.get("commandline-local", {}))
        elif executor == "yepcode":
            try:
                from .yepcode_code_executor import YepCodeCodeExecutor
            except ImportError as e:
                raise ImportError("Missing dependencies for YepCodeCodeExecutor. "
                                   "Please install with: pip install ag2[yepcode]") from e
            return YepCodeCodeExecutor(**code_execution_config.get("yepcode", {}))
        # ...same pattern for "remyx", "daytona"...
        else:
            raise ValueError(f"Unknown code executor {executor}")
```
This is exactly the "lazy import behind an optional extra, `ImportError` → actionable
`pip install x[extra]` message" pattern AK already uses for guardrails
(`ak-py/src/agentkernel/guardrail/guardrail.py`) and multimodal storage — good confirmation that
convention is sound, and it is independently arrived at by AG2. Third parties bring their own
backend by (a) implementing the `CodeExecutor` Protocol (structural typing — no base class
inheritance required, `@runtime_checkable` even permits `isinstance` checks against it) and (b)
either passing an instance directly, or a maintainer adding a new `elif` branch — AG2 has no
open plugin-registration API; the `elif` chain is a closed list maintained in-tree, same
limitation as smolagents' enum.

The `CodeExecutionConfig` TypedDict shows the executor selection sitting alongside execution
policy in one bag: `last_n_messages`, `timeout`, `use_docker`, `work_dir` are all part of the same
config object passed to `ConversableAgent(code_execution_config=...)`.

### 2b. Microsoft AutoGen (`microsoft/autogen`, `autogen_core.code_executor` — async ABC)

Source: https://github.com/microsoft/autogen, `python/packages/autogen-core/src/autogen_core/code_executor/_base.py`
(current `main`).

```python
@dataclass
class CodeBlock:
    code: str
    language: str

@dataclass
class CodeResult:
    exit_code: int
    output: str

class CodeExecutor(ABC, ComponentBase[BaseModel]):
    component_type = "code_executor"

    @abstractmethod
    async def execute_code_blocks(
        self, code_blocks: List[CodeBlock], cancellation_token: CancellationToken
    ) -> CodeResult:
        """
        Raises:
            ValueError: Errors in user inputs
            asyncio.TimeoutError: Code execution timeouts
            asyncio.CancelledError: CancellationToken evoked during execution
        """
        ...

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    async def restart(self) -> None:
        """Called when the agent is reset."""
        ...

    async def __aenter__(self) -> Self:
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> Optional[bool]:
        await self.stop()
        return None
```

Compared to AG2's sync Protocol, the 0.4 rewrite made three deliberate changes worth calling out:

1. **Sync Protocol → async ABC.** All operations became `async def`, and a first-class
   `CancellationToken` parameter threads through `execute_code_blocks` — cancellation is a
   *documented, typed* failure mode (`asyncio.CancelledError`), not an afterthought.
2. **No lifecycle → explicit `start`/`stop`/`restart` + async context manager.** The docstring is
   explicit about *why*: "It is recommended for subclass to be used as a context manager to
   ensure that resources are cleaned up properly." `restart` is semantically distinct from
   `stop`+`start` — it's "reset conversation/session state without tearing down the underlying
   resource" (e.g. clear a Jupyter kernel's variables without killing the container).
3. **`ComponentBase[BaseModel]` mixin — declarative serialization for portability.** Every
   concrete executor pairs itself with a Pydantic `*Config` model and implements
   `_to_config()`/`_from_config()`:
   ```python
   class DockerCommandLineCodeExecutorConfig(BaseModel): ...
   class DockerCommandLineCodeExecutor(CodeExecutor, Component[DockerCommandLineCodeExecutorConfig]):
       component_config_schema = DockerCommandLineCodeExecutorConfig
       component_provider_override = "autogen_ext.code_executors.docker.DockerCommandLineCodeExecutor"
       def _to_config(self) -> DockerCommandLineCodeExecutorConfig: ...
       @classmethod
       def _from_config(cls, config: DockerCommandLineCodeExecutorConfig) -> Self: ...
   ```
   This means any executor instance can be serialized to JSON (`provider` string +
   `config` dict) and reconstructed elsewhere — the mechanism AutoGen Studio (the low-code UI)
   uses to let a user pick/configure an executor from a form rather than write Python. This is the
   single most sophisticated "backend configuration" mechanism in this whole survey: it turns "how
   do third parties register a backend" into "any class importable by dotted path + a Pydantic
   config schema," with no central registry to update at all — registration is structural
   (the dotted path *is* the registration).

**Concrete executors** (all in `autogen-ext`, all implement the async ABC above):

- **`LocalCommandLineCodeExecutor`** (`autogen_ext.code_executors.local`) — writes each code
  block to a file in `work_dir` and runs it as a subprocess (`SUPPORTED_LANGUAGES = ["bash",
  "shell", "sh", "pwsh", "powershell", "ps1", "python"]`). Explicitly **not sandboxed** — warns on
  construction:
  ```python
  warnings.warn(
      "Using LocalCommandLineCodeExecutor may execute code on the local machine which can be unsafe. "
      "For security, it is recommended to use DockerCommandLineCodeExecutor instead. ...",
      UserWarning, stacklevel=2,
  )
  ```
  Supports injecting typed Python functions (`FunctionWithRequirements`) into the executor's
  namespace via a generated `functions.py` module — a structured alternative to smolagents'
  "serialize tool defs as code text" approach. `restart()` is a documented **no-op with a
  warning** ("Restarting local command line code executor is not supported"), illustrating that
  even within one interface, capability support is uneven and surfaced only at runtime.
- **`DockerCommandLineCodeExecutor`** (`autogen_ext.code_executors.docker`) — same
  save-file-then-exec model but inside a long-lived Docker container (`container.exec_run`
  equivalent via the `docker` SDK), constructed with `image`, `container_name`,
  `timeout`, `work_dir`/`bind_dir`, `auto_remove`, `stop_container`, `functions`. Because it's
  async, cancellation is implemented as killing the in-flight command
  (`_kill_running_command`) — and this is precisely where AutoGen's own bug tracker shows the
  hard part of "async + long-lived resource" (see pain points).
- **`JupyterCodeExecutor`** (`autogen_ext.code_executors.jupyter`) — executes via `nbclient`
  against a running Jupyter kernel; naturally **stateful** across calls (kernel retains
  variables). Returns `JupyterCodeResult(CodeResult)` with extra fields for rendered
  outputs (saves images/HTML to `output_dir` and returns paths) — again the "subclass adds
  capability-specific fields" pattern.
- **`ACADynamicSessionsCodeExecutor`** (`autogen_ext.code_executors.azure`) — Azure Container
  Apps dynamic sessions. Notably the **richest file-I/O surface** in the whole executor
  hierarchy: `upload_files(files, cancellation_token)`, `download_files(files,
  cancellation_token)`, `get_file_list(cancellation_token)`, plus `get_available_packages()` to
  query what's pre-installed in the session pool. Auth is injected via a `TokenProvider`
  Protocol (`get_token(...)`), not hardcoded to one Azure SDK credential type — a clean
  "bring your own auth" seam.

### AutoGen/AG2 pain points (GitHub issues, microsoft/autogen)

- **#741** "Docker based code execution slow — reuse container / be able to specify
  requirements.txt up front": a new container is spun up per execution by default in the naive
  usage pattern; users want session reuse and pre-baked dependencies, i.e. cold-start latency is
  a first-order UX problem for container-backed executors, not an edge case.
- **#6395** "`DockerCommandLineCodeExecutor` does not safely manage cancellation tasks across
  multiple event loops (loop mismatch issue)": cancellation tasks created on one asyncio event
  loop get awaited from `stop()` on a different loop → `RuntimeError`. This is a direct
  consequence of making the interface async without also pinning executor instances to a single
  loop — a cautionary tale for AK's own async design (loop affinity needs to be either enforced
  or made loop-agnostic, not left implicit).
- **#5363**: users wanted more Docker configurability (extra volume mounts, exposed host ports)
  than the executor's constructor exposed — again, the tension between a clean cross-backend
  interface and backend-specific knobs users inevitably need.
- **#2027 / #1743-equivalent**: token/credential plumbing into a hosted executor was awkward
  enough to need a dedicated fix — supports treating "how does the backend authenticate" as a
  first-class interface concern (as ACADynamicSessionsCodeExecutor's `TokenProvider` now does)
  rather than leaving it to each backend's constructor kwargs.

---

## 3. LangChain / LangGraph — no common interface, per-vendor `Tool`s

**There is no shared sandbox/executor base class in LangChain.** Every integration is an
independent `langchain_core.tools.BaseTool` subclass with its own `_run`/`_arun`, its own
constructor kwargs, and its own return shape. This is the sharpest contrast in the survey — worth
stating plainly since it's a common design LangChain users hit friction on.

### `langchain-sandbox` (`langchain-ai/langchain-sandbox`) — Pyodide/Deno, closest thing to a "framework opinion"

Source: https://github.com/langchain-ai/langchain-sandbox,
`libs/sandbox-py/langchain_sandbox/pyodide.py`.

```python
@dataclasses.dataclass(kw_only=True)
class CodeExecutionResult:
    result: Any = None
    stdout: str | None = None
    stderr: str | None = None
    status: Literal["success", "error"]
    execution_time: float
    session_metadata: dict | None = None
    session_bytes: bytes | None = None

class BasePyodideSandbox:
    def __init__(
        self, *, stateful: bool = False,
        allow_env: list[str] | bool = False,
        allow_read: list[str] | bool = False,
        allow_write: list[str] | bool = False,
        allow_net: list[str] | bool = False,
        allow_run: list[str] | bool = False,
        allow_ffi: list[str] | bool = False,
        node_modules_dir: str = "auto",
        skip_deno_check: bool = False,
    ) -> None: ...

class PyodideSandbox(BasePyodideSandbox):
    async def execute(
        self, code: str, *,
        session_bytes: bytes | None = None,
        session_metadata: dict | None = None,
        timeout_seconds: float | None = None,
        memory_limit_mb: int | None = None,
    ) -> CodeExecutionResult: ...

class SyncPyodideSandbox(BasePyodideSandbox):
    def execute(self, code: str, *, session_bytes=None, ...) -> CodeExecutionResult: ...
```
Design points:
- **Explicit sync/async twins** (`PyodideSandbox` vs. `SyncPyodideSandbox`) rather than one class
  with both `execute`/`aexecute` methods, or an "is this an event loop" branch. Both share
  construction/permission logic via `BasePyodideSandbox`.
- **Statefulness is opt-in and externalized**: `stateful=True` makes `execute()` return
  `session_bytes`/`session_metadata` that the *caller* stores and passes back into the next
  `execute()` call. The sandbox process itself is stateless/ephemeral (a fresh Deno subprocess
  per call) — persistence is achieved by serializing interpreter state out and back in, not by
  keeping a long-lived process around. This is a fundamentally different persistence model from
  Jupyter-kernel-based statefulness (AutoGen's `JupyterCodeExecutor`, smolagents' `DockerExecutor`)
  where the *process* persists. Worth flagging as a real design fork: "persist via serialized
  session blob" vs. "persist via long-lived process/kernel" — the former survives restarts /
  moves across machines, the latter doesn't but avoids serialization cost and works for
  non-serializable state (open file handles, live network connections, etc).
- **Fine-grained OS-level capability flags** (`allow_env`, `allow_read`, `allow_write`,
  `allow_net`, `allow_run`, `allow_ffi`) map straight onto Deno's own permission flags — the
  sandbox's security model is inherited wholesale from the underlying runtime rather than
  reimplemented.
- Wrapped as a LangChain tool via `PyodideSandboxTool(BaseTool)` with `_run`/`_arun`, i.e. the
  sandbox class is the reusable primitive and the LangChain `Tool` is a thin adapter — a layering
  AK should probably mirror (sandbox interface vs. the tool/function wrapper that exposes it to
  an agent are two different concerns).

### Per-vendor tools — genuinely independent implementations

- **Riza** (`langchain_community.tools.riza.command.ExecPython`) — thinnest possible wrapper:
  ```python
  class ExecPython(BaseTool):
      name: str = "riza_exec_python"
      args_schema: Type[BaseModel] = ExecPythonInput   # {code: str}
      def _run(self, code: str, run_manager=None) -> str:
          output = self.client.command.exec(
              runtime_revision_id=self.runtime_revision_id, language="python", code=code)
          ...
  ```
  No file I/O, no session concept exposed at all — "the Python runtime does not have filesystem
  access," per its own tool description.
- **E2B** (`langchain_community.tools.e2b_data_analysis.tool.E2BDataAnalysisTool`) — noticeably
  richer surface than Riza, closer to a mini-executor: `run_command(...)`,
  `install_python_packages(...)`, `install_system_packages(...)`, `upload_file(file,
  description) -> UploadedFile`, `download_file(remote_path) -> bytes`,
  `remove_uploaded_file(...)`, `close()`. Session persists implicitly for the tool instance's
  lifetime (one E2B sandbox per tool instance).
- **Bearly** (`langchain_community.tools.bearly.tool.BearlyInterpreterTool`) — similar shape:
  `add_file(source_path, target_path, description)`, `clear_files()`, `_run(python_code) ->
  dict`.
- **Azure Container Apps dynamic sessions**
  (`langchain_azure_dynamic_sessions.tools.sessions.SessionsPythonREPLTool` /
  `SessionsBashTool`) — the most complete file-I/O surface of any LangChain tool surveyed:
  ```python
  class SessionsPythonREPLTool(BaseTool):
      def execute(self, python_code: str) -> Any: ...
      def upload_file(self, *, data=..., remote_file_path=...) -> RemoteFileMetadata: ...
      def download_file(self, *, remote_file_path) -> bytes: ...
      def list_files(self) -> List[RemoteFileMetadata]: ...
      def delete_session(self) -> None: ...
      def close(self) -> None: ...
      def __enter__(self) -> "SessionsPythonREPLTool": ...
      def __exit__(self, exc_type, exc_val, exc_tb) -> None: ...
  ```
  It's also the only one that models a `session_id` explicitly and implements the Python context
  manager protocol for lifecycle — worth noting since it's the tool most structurally similar to
  what a general-purpose Sandbox interface needs.

**Answering the brief's direct question: no, there is no common interface** — LangChain's own
docs and integration hub present these as unrelated tools that happen to solve the same problem
differently; swapping one for another means rewriting the agent's tool wiring, not changing a
config value. The `langchain-sandbox` package is the closest thing to an opinionated design, but
it isn't adopted as *the* interface other integrations implement — it's simply another
independent tool.

### LangGraph CodeAct (`langchain-ai/langgraph-codeact`)

The prebuilt `create_codeact(model, tools, eval_fn)` takes a bare **function**, not a class, as
the pluggable execution seam:
```python
def eval(code: str, _locals: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    ...  # returns (captured stdout/output, updated locals dict)
```
This is the minimal possible interface — "a callable that takes code + a state dict and returns
output + an updated state dict" — pushed even further than smolagents' 3-method ABC. The
project's own docs flag the reference implementation as unsafe/for-demo-only and tell users to
substitute a sandboxed `eval_fn` (E2B, Pyodide, etc.) in production, i.e. the *shape* of the seam
is opinionated (`(code, locals) -> (output, locals)`) but the backend is 100% bring-your-own with
zero registration mechanism — literally a function reference passed at agent-construction time.

### Pain points / critiques

- The long-deprecated `langchain_experimental.utilities.PythonREPL` /
  `PythonAstREPLTool` (plain `exec()` in-process, no isolation at all) shipped for years with
  loud "this can execute arbitrary code, do not use with untrusted input" warnings before being
  pushed toward `langchain-sandbox`/E2B; it's the canonical cautionary example the ecosystem
  points to when arguing *why* a real sandbox boundary (not just "run it in a try/except") is
  necessary for a code tool.
- Because each vendor tool is independent, capability parity is inconsistent: Riza has no file
  I/O at all, E2B/Azure have rich file I/O, only `langchain-sandbox` exposes granular OS
  permission flags, only Azure's tool implements `__enter__`/`__exit__`. A user who prototypes
  against one vendor's tool and later wants to swap providers has to rewrite the integration
  rather than swap a config value — the exact vendor-lock-in problem AK's proposed `Sandbox`
  interface is meant to avoid.

---

## 4. OpenAI Agents SDK — hosted tool descriptors, not an executor interface

Source: `openai-agents` (`openai_agents` PyPI package `agents/tool.py`), v0.17.5, installed in
this repo's `ak-py/.venv`. Docs: https://platform.openai.com/docs/guides/tools-code-interpreter,
https://platform.openai.com/docs/guides/tools-local-shell.

The SDK models code execution as **tool descriptors that get attached to a model turn**, not as
a class the developer implements. Two different tools, two different execution models:

```python
@dataclass
class CodeInterpreterTool:
    """A tool that allows the LLM to execute code in a sandboxed environment."""
    tool_config: CodeInterpreter          # openai.types.responses.tool_param.CodeInterpreter
    @property
    def name(self): return "code_interpreter"
```
`CodeInterpreterTool` is entirely **server-side / hosted** — the "sandbox" is OpenAI's own
managed container. `tool_config` selects `container: {"type": "auto"}` (ephemeral, one per
response) or `{"type": "container_id", "id": "..."}` (reuse a previously created container across
turns for state persistence) per the Responses API `code_interpreter` tool schema. There is no
client-side executor class to implement — configuring the execution environment means choosing a
container id, not writing code.

```python
LocalShellExecutor = Callable[[LocalShellCommandRequest], MaybeAwaitable[str]]

@dataclass
class LocalShellTool:
    """Allows the LLM to execute commands on a shell."""
    executor: LocalShellExecutor
    @property
    def name(self): return "local_shell"
```
`LocalShellTool` is the inverse: **fully bring-your-own** — the SDK defines only the
request/response *shape*
(`LocalShellCommandRequest{ctx_wrapper, data: LocalShellCall}` in, `str` or `MaybeAwaitable[str]`
out) and the developer supplies any callable. No sandboxing is provided or implied; the developer
is expected to run it wherever/however they want (their own Docker container, a subprocess, a
remote host).

The newer **`ShellTool`** generalizes `LocalShellTool` with an explicit `environment` union type
that spans local and hosted execution in one field:
```python
ShellToolEnvironment = ShellToolLocalEnvironment | ShellToolHostedEnvironment
# ShellToolLocalEnvironment: {"type": "local", skills: [...]}
# ShellToolHostedEnvironment:
#   {"type": "container_auto", file_ids, memory_limit: "1g"|"4g"|"16g"|"64g", network_policy, skills}
#   {"type": "container_reference", container_id}

ShellExecutor = Callable[[ShellCommandRequest], MaybeAwaitable[str | ShellResult]]

@dataclass
class ShellTool:
    executor: ShellExecutor | None = None
    environment: ShellToolEnvironment | None = None      # None => local
    needs_approval: bool | ShellApprovalFunction = False
    on_approval: ShellOnApprovalFunction | None = None
    def __post_init__(self) -> None:
        # local environment requires an executor; hosted environment forbids one
        ...
```
This is a notable design: **one tool, one discriminated-union config field, that spans
"run it yourself" and "we'll run it in our container"** — the SDK enforces at construction time
(`__post_init__`) that `executor` and hosted `environment` are mutually exclusive, and that
`needs_approval`/`on_approval` (a human-in-the-loop gate) only make sense for the local path.
`network_policy` on the hosted container variant is itself a small pluggable-ish union
(`allowlist` vs. `disabled`), and `memory_limit` is a closed enum of tiers rather than an
arbitrary number — i.e. even OpenAI's own hosted environment only exposes a few coarse-grained
knobs, not general sandbox configuration.

Structured results carry enough detail to distinguish normal completion from timeout:
```python
@dataclass
class ShellCallOutcome:
    type: Literal["exit", "timeout"]
    exit_code: int | None = None

@dataclass
class ShellCommandOutput:
    stdout: str = ""
    stderr: str = ""
    outcome: ShellCallOutcome = field(default_factory=lambda: ShellCallOutcome(type="exit"))
    command: str | None = None
    provider_data: dict[str, Any] | None = None
```
`provider_data: dict[str, Any] | None` fields appear on both `ShellCommandOutput` and
`ShellResult` — an explicit "escape hatch" bag for provider-specific extra data that doesn't fit
the common schema, which is a lightweight alternative to AutoGen's "capability-specific
CodeResult subclass" pattern for the same problem (letting one backend return more than the
others without breaking the common type).

**Takeaway for AK**: this is the "sandboxing as a tool config, not an executor abstraction"
school of design. It works well when there's exactly one hosted backend (OpenAI's own container
service) plus a fully-manual escape hatch, but it does not give a third party a way to plug in
*their own* sandboxed backend and have it look the same as the hosted one to the rest of the
SDK — `environment` is a closed union of "local" and "OpenAI's container," not an open interface.

---

## 5. CrewAI — deprecated `allow_code_execution`, now points users at external sandboxes

Source: `crewai` v1.15.0 (`ak-py/.venv`), `crewai/agent/core.py`; tool implementation from
`crewAIInc/crewAI-tools`, `crewai_tools/tools/code_interpreter_tool/code_interpreter_tool.py`.

CrewAI is the one framework in this survey that **had** a Docker-safe/unsafe abstraction and has
since deprecated it in favor of telling users to integrate a real sandbox service themselves:

```python
allow_code_execution: bool | None = Field(
    default=False, deprecated=True,
    description="Deprecated. CodeInterpreterTool is no longer available. "
                "Use dedicated sandbox services instead.",
)
code_execution_mode: Literal["safe", "unsafe"] = Field(
    default="safe", deprecated=True,
    description="Deprecated. CodeInterpreterTool is no longer available. "
                "Use dedicated sandbox services instead.",
)
```
```python
if self.allow_code_execution:
    warnings.warn(
        "allow_code_execution is deprecated and will be removed in v2.0. "
        "CodeInterpreterTool is no longer available. "
        "Use dedicated sandbox services like E2B or Modal.",
        DeprecationWarning, stacklevel=2,
    )
```

The tool itself (still shipped in the separate `crewai-tools` package, not `crewai` core) shows
what "safe" vs. "unsafe" meant concretely — worth recording since the pattern (two execution
paths behind one `_run`, selected by a boolean) is simple and reusable:

```python
class CodeInterpreterTool(BaseTool):
    default_image_tag: str = "code-interpreter:latest"
    user_dockerfile_path: Optional[str] = None
    user_docker_base_url: Optional[str] = None
    unsafe_mode: bool = False

    def _run(self, **kwargs) -> str:
        code = kwargs.get("code", self.code)
        libraries_used = kwargs.get("libraries_used", [])
        if self.unsafe_mode:
            return self.run_code_unsafe(code, libraries_used)      # exec() directly on host, no isolation
        else:
            return self.run_code_safety(code, libraries_used)      # Docker if available, else a restricted exec()

    def run_code_safety(self, code: str, libraries_used: List[str]) -> str:
        if self._check_docker_available():
            return self.run_code_in_docker(code, libraries_used)
        else:
            return self.run_code_in_restricted_sandbox(code)        # blocked-import/blocked-builtins exec(), NOT a real sandbox

    def run_code_in_docker(self, code: str, libraries_used: List[str]) -> str:
        self._verify_docker_image()          # build from Dockerfile if the image is missing
        container = self._init_docker_container()   # kills/replaces any same-named container, mounts cwd at /workspace
        self._install_libraries(container, libraries_used)   # pip install per-library, one exec_run per package
        exec_result = container.exec_run(["python3", "-c", code])
        container.stop(); container.remove()
        ...
```
"Safe" mode's non-Docker fallback (`run_code_in_restricted_sandbox`) is a `BLOCKED_MODULES`/
`UNSAFE_BUILTINS` denylist around plain `exec()` — i.e. even the "safe" path is only actually
safe when Docker happens to be present; the denylist fallback is acknowledged (by omission of any
stronger claim in the docstring) to be best-effort only, the same "not a real security boundary"
caveat smolagents makes explicit about its `LocalPythonExecutor`.

Lifecycle here is the least sophisticated in the whole survey: a **fixed container name**
(`"code-interpreter"`) is stopped/removed and recreated **on every single tool call** — there is
no session/reuse concept at all, which directly reproduces the "Docker execution is slow because
a new container is instantiated each time" complaint AutoGen users raised in issue #741 above.

**Takeaway for AK**: CrewAI is a useful negative example — it shows what happens when "sandboxing"
is bolted onto a single tool as a boolean flag rather than designed as a swappable capability:
the framework maintainers ultimately gave up maintaining it and now defer entirely to external
services, with no interface left for third parties to plug into.

---

## 6. Google ADK — `BaseCodeExecutor` (Pydantic `BaseModel`-based ABC)

Source: `google-adk` v1.14.1 (`ak-py/.venv`),
`google/adk/code_executors/{base_code_executor,code_execution_utils,built_in_code_executor,container_code_executor,unsafe_local_code_executor,vertex_ai_code_executor,gke_code_executor}.py`.

### The interface

Unusually, the ABC is itself a **Pydantic `BaseModel`** (not a plain `abc.ABC`) — configuration
fields and the abstract method live on the same class:

```python
class BaseCodeExecutor(BaseModel):
    """Abstract base class for all code executors."""

    optimize_data_file: bool = False
    """Extract/attach CSV data files from the model request to the executor."""

    stateful: bool = False
    """Whether the code executor is stateful."""

    error_retry_attempts: int = 2
    """Number of attempts to retry on consecutive code execution errors."""

    code_block_delimiters: List[tuple[str, str]] = [
        ('```tool_code\n', '\n```'),
        ('```python\n', '\n```'),
    ]
    execution_result_delimiters: tuple[str, str] = ('```tool_output\n', '\n```')

    @abc.abstractmethod
    def execute_code(
        self,
        invocation_context: InvocationContext,
        code_execution_input: CodeExecutionInput,
    ) -> CodeExecutionResult:
        """Executes code and returns the code execution result."""
```
```python
@dataclasses.dataclass
class File:
    name: str
    content: str          # base64-encoded if binary
    mime_type: str = 'text/plain'

@dataclasses.dataclass
class CodeExecutionInput:
    code: str
    input_files: list[File] = dataclasses.field(default_factory=list)
    execution_id: Optional[str] = None       # ties a call to a stateful session

@dataclasses.dataclass
class CodeExecutionResult:
    stdout: str = ''
    stderr: str = ''
    output_files: list[File] = dataclasses.field(default_factory=list)
```
This is the **only framework surveyed where prompt-parsing configuration (the code-fence
delimiters used to find code blocks in the model's text output) is part of the same base class as
the executor** — a consequence of ADK's design where the executor is also responsible for
"pre-process the LLM request" (see `BuiltInCodeExecutor.process_llm_request` below), not purely
an execution backend. `execute_code` is **synchronous** (not async), taking the whole
`invocation_context` (session/state access) plus a self-contained `CodeExecutionInput` — file
I/O is folded directly into the one call (`input_files` in, `output_files` out) rather than
exposed as separate upload/download methods.

Statefulness is modeled as a **declared boolean capability the executor advertises**
(`stateful: bool = False` on the base, overridden per subclass), and a companion
`CodeExecutorContext` class (`google/adk/code_executors/code_executor_context.py`) persists
cross-call state **in ADK session state**, not inside the executor object itself:
```python
class CodeExecutorContext:
    def __init__(self, session_state: State): ...
    def get_execution_id(self) -> Optional[str]: ...
    def set_execution_id(self, session_id: str) -> None: ...
    def get_input_files(self) -> list[File]: ...
    def add_input_files(self, input_files: list[File]) -> None: ...
    def get_error_count(self, invocation_id: str) -> int: ...
    def increment_error_count(self, invocation_id: str) -> None: ...
    def update_code_execution_result(self, invocation_id, code, result_stdout, result_stderr) -> None: ...
```
This is a distinctive and AK-relevant pattern: **the execution *session* is externalized to the
host framework's own session/state object**, so the executor implementation doesn't need to
manage its own session store — it just reads/writes through `CodeExecutorContext`, which is bound
to whatever session backend ADK is already using (in-memory, database, etc). This directly
maps onto AK's own `Session` concept and is worth studying further.

### Concrete backends

- **`BuiltInCodeExecutor`** — not really a local executor at all; `execute_code` is a no-op
  (`pass`) and the real work happens in `process_llm_request`, which injects Gemini's own
  server-side code-execution tool declaration into the request:
  ```python
  class BuiltInCodeExecutor(BaseCodeExecutor):
      @override
      def execute_code(self, invocation_context, code_execution_input) -> CodeExecutionResult:
          pass
      def process_llm_request(self, llm_request: LlmRequest) -> None:
          if is_gemini_2_model(llm_request.model):
              llm_request.config = llm_request.config or types.GenerateContentConfig()
              llm_request.config.tools = llm_request.config.tools or []
              llm_request.config.tools.append(types.Tool(code_execution=types.ToolCodeExecution()))
              return
          raise ValueError(f"Gemini code execution tool is not supported for model {llm_request.model}")
  ```
  i.e. one concrete subclass's "execution" is entirely about mutating the outgoing LLM request,
  not running anything locally — the interface has to accommodate "the model itself is the
  sandbox" as a valid backend.
- **`UnsafeLocalCodeExecutor`** — bare `exec()` in the current process; refuses to be
  constructed with `stateful=True` (`ValueError: Cannot set stateful=True in
  UnsafeLocalCodeExecutor`) and hardcodes `stateful: bool = Field(default=False, frozen=True,
  exclude=True)` — the base class's capability flag is used here as a compile-time-checked
  guarantee, not just documentation.
- **`ContainerCodeExecutor`** — local Docker, `image: str` or `docker_path: str` (build from a
  Dockerfile) — same `stateful` lock as above (`frozen=True`), i.e. ADK's Docker executor doesn't
  even attempt session persistence.
- **`GkeCodeExecutor`** — runs each execution as a **Kubernetes Job** (`_create_job_manifest`,
  `_watch_job_completion`, `_get_pod_logs`, `_create_code_configmap`, `_add_owner_reference`) with
  a configurable `image: str = "python:3.11-slim"`. Notably this is the closest analogue in the
  entire survey to AK's "connect to an existing runtime" usage mode — it's provisioning
  short-lived compute against an existing cluster the caller already controls, rather than owning
  a long-lived sandbox process.
- **`VertexAiCodeExecutor`** — delegates to a managed Vertex AI Extension
  (`_get_code_interpreter_extension(resource_name)`); can attach to a **pre-existing** extension
  resource by name (`resource_name` constructor arg / `CODE_INTERPRETER_EXTENSION_NAME` env var)
  instead of always provisioning a new one — another "attach to existing" precedent.

### Wiring / configuration

`code_executor: Optional[BaseCodeExecutor] = None` is just a field on `LlmAgent` — construct the
concrete class you want and pass the instance in. No factory, no config-string registry, no
extras-based lazy import — whichever executor module you `import` is the one you depend on
(so e.g. `ContainerCodeExecutor` presumably requires `docker` to be installed for its
constructor/exec calls to succeed, but ADK doesn't gate that behind an optional extras group the
way AG2/smolagents do). Third parties add a backend simply by subclassing `BaseCodeExecutor` and
instantiating it — completely open, but also completely unmanaged (no registry to discover what
backends exist).

### Pain points (GitHub issues, google/adk-python)

- **#3921/#3929/#3930/#3941** (multiple linked issues+PRs, all titled around "infinite loop"):
  when `code_executor` is enabled, the agent could loop forever re-issuing code execution turns;
  fixed by "preserving code execute" state/history more carefully — a symptom of the
  request-mutation approach (`process_llm_request`) interacting badly with the agent's own
  turn-taking loop.
  loop.
- **#5855**: models misuse the `executable_code` tool for plain generation-only prompts when
  `code_executor` is enabled — i.e. simply having a code-executor configured changes model
  behavior even when the user didn't want code run, a side effect of `BuiltInCodeExecutor`
  injecting a tool declaration into every request rather than only when relevant.
- **#6139**: uses via an LLM gateway (not directly against Gemini) fail — because
  `BuiltInCodeExecutor.process_llm_request` hardcodes a Gemini-2-only check
  (`is_gemini_2_model`), the abstraction leaks a single-provider assumption.
- **#1620/#237**: recurring "how do I even use `code_executor`" questions — signals the
  documentation/discoverability of the abstraction (five different executor classes, no
  factory/registry to browse) was a real onboarding cost.

---

## 7. Claude Agent SDK / Claude Code — sandboxing at the tool boundary, not an executor interface

This is a **structurally different approach** from every other entry in this survey: instead of
a pluggable class that owns "run this code somewhere," Claude Code sandboxes the **bash tool
call itself** using OS primitives, configured declaratively through settings — there is no
executor object to subclass, and no backend to "swap in" beyond turning the feature on/off and
tuning its allowlists.

### Claude Code: sandboxed Bash tool

Docs: https://code.claude.com/docs/en/sandboxing.

- **OS enforcement, not a backend abstraction**: macOS uses the built-in **Seatbelt**
  (`sandbox-exec`) framework; Linux and WSL2 use **bubblewrap** (`bwrap`) plus `socat` for network
  relay, with an optional seccomp filter to block raw Unix sockets. There is exactly one sandbox
  implementation per OS, selected automatically — no pluggable backend concept at all.
- **Two axes of restriction, both allow/deny-list based, resolved from merged settings
  scopes** (`.claude/settings.json`, `settings.local.json`, user `~/.claude/settings.json`,
  managed/MDM settings):
  ```json
  {
    "sandbox": {
      "enabled": true,
      "filesystem": {
        "allowWrite": ["~/.kube", "/tmp/build"],
        "denyRead": ["~/"],
        "allowRead": ["."]
      },
      "network": {
        "allowedDomains": ["*.github.com", "registry.npmjs.org"],
        "httpProxyPort": 8080,
        "socksProxyPort": 8081
      },
      "credentials": {
        "files": [{ "path": "~/.aws/credentials", "mode": "deny" }],
        "envVars": [{ "name": "GITHUB_TOKEN", "mode": "deny" }]
      },
      "failIfUnavailable": true,
      "allowUnsandboxedCommands": false
    }
  }
  ```
  Filesystem defaults to write-access-only-in-cwd-plus-tmp, read-access-to-everything-except-
  denials; network defaults to a locked-down allowlist that grows via runtime approval prompts
  (or is capped by `allowManagedDomainsOnly` in MDM-managed settings). `sandbox.credentials` is a
  nice small idea — a distinct, explicitly-named block for secrets (files + env vars) with
  `deny` or `mask` modes (`mask` substitutes a per-session sentinel value that only the
  *sandbox's own egress proxy* resolves back to the real secret when the request reaches an
  approved host — the command process itself, and anything it logs, never holds the real
  value).
- **Escape hatch, not a capability query**: rather than the executor declaring what it can/can't
  do up front (ADK's `stateful` flag, AutoGen's per-method support), Claude Code lets a command
  **fail under the sandbox and then retry unsandboxed** (`dangerouslyDisableSandbox`), gated by
  the normal permission flow. `allowUnsandboxedCommands: false` removes this escape hatch entirely
  for strict/managed deployments. This is a pragmatic alternative to capability negotiation: don't
  model what's possible, just let failures fall back to a slower, explicitly-approved path.
- **Scope is narrow and explicit**: only the Bash tool (and its child processes) is sandboxed;
  Read/Edit/Write use the ordinary permission system, and "computer use" runs on the real desktop.
  This is a useful reminder that "sandboxing" doesn't have to mean "sandbox everything" — a
  framework can scope the boundary to exactly the tool surface where untrusted code execution
  actually happens.

### `anthropics/sandbox-runtime` (`srt`) — the reusable primitive Claude Code is built on

Repo: https://github.com/anthropic-experimental/sandbox-runtime.

This is genuinely embeddable — a standalone npm package with both a CLI and a library API,
explicitly designed for reuse beyond Claude Code (its README's primary example is sandboxing
**MCP servers**, not Claude Code itself):
```bash
srt "curl anthropic.com"
srt --settings /path/to/config.json npm install
```
Programmatic surface: `SandboxManager` (orchestrator), `SandboxViolationStore` (audit/violation
log), and typed config (`SandboxRuntimeConfig`, `NetworkConfig`, `FilesystemConfig`) mirroring the
same allow/deny-list shape as Claude Code's own `sandbox.*` settings (read: deny-then-allow;
write: allow-only with deny override). Platform coverage mirrors Claude Code
(Seatbelt/bubblewrap) plus an alpha Windows path (dedicated low-privilege user account + Windows
Filtering Platform egress rules + NTFS ACLs) — notable as the only Windows-native sandboxing
story anywhere in this survey (everyone else either doesn't address Windows or tells users to run
inside WSL2/a container).

### Claude Agent SDK (programmatic)

The Python/TypeScript Agent SDK exposes the same sandbox feature as a nested option on
`ClaudeAgentOptions` rather than as an executor class:
```python
options = ClaudeAgentOptions(
    sandbox={"enabled": True, "allowUnsandboxedCommands": True},
    can_use_tool=can_use_tool,   # separate, general-purpose permission callback
)
```
`sandbox` controls the OS-level bash boundary described above; `can_use_tool` is an orthogonal,
per-call permission callback that can inspect/deny/rewrite *any* tool call (not specific to code
execution) — i.e. the SDK treats "restrict what a shell command can touch on this machine" and
"decide whether this tool call is allowed to happen at all" as two independent layers, matching
the docs' framing of sandboxing and permissions as "complementary layers," not one subsuming the
other.

**Takeaway for AK**: this whole family is the clearest counter-example to "sandbox = pluggable
executor class." It shows a viable, very different design point — wrap the *existing* tool
boundary (bash) with OS-level policy, expressed as declarative allow/deny configuration, with a
single built-in enforcement mechanism per OS rather than a zoo of backend classes. It's a strong
answer to "isolate untrusted code on the same machine the agent is already running on," but it
does not address (and isn't trying to address) AK's "connect to a different/remote existing
runtime" usage mode, nor does it offer a story for swapping in an entirely different sandbox
*provider* (E2B, Modal, a K8s job) the way every class-based abstraction in this survey does —
those remain separate tools/executors layered on top, not something `srt` itself models.

---

## 8. OpenHands (formerly OpenDevin) and Open Interpreter

### 8a. OpenHands — `Runtime` base class + uniform in-sandbox REST server

Source: https://github.com/All-Hands-AI/OpenHands, tag `0.48.0` (the last tag before the
`openhands/runtime` package was carved out of the main monorepo into a separate `agent-sdk`
project — see note at the end of this section), `openhands/runtime/base.py`.

This is the **richest, most action-oriented abstraction** in the survey — rather than "execute
code, get output," OpenHands models the whole agent-computer interface as a typed
**Action → Observation** protocol, of which code/shell execution is just two members:

```python
class Runtime(FileEditRuntimeMixin):
    """Abstract base class for agent runtime environments.

    Subclass by:
    1. Creating a class that inherits from Runtime
    ...
    The class is instantiated via get_impl() in get_runtime_cls().
    """

    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    def get_mcp_config(self, ...): ...

    @abstractmethod
    def run(self, action: CmdRunAction) -> Observation: ...

    @abstractmethod
    def run_ipython(self, action: IPythonRunCellAction) -> Observation: ...

    @abstractmethod
    def read(self, action: FileReadAction) -> Observation: ...

    @abstractmethod
    def write(self, action: FileWriteAction) -> Observation: ...

    @abstractmethod
    def edit(self, action: FileEditAction) -> Observation: ...

    @abstractmethod
    def browse(self, action: BrowseURLAction) -> Observation: ...

    @abstractmethod
    def browse_interactive(self, action: BrowseInteractiveAction) -> Observation: ...

    @abstractmethod
    async def call_tool_mcp(self, action: MCPAction) -> Observation: ...

    @abstractmethod
    def copy_to(self, host_src: str, sandbox_dest: str, recursive: bool = False): ...

    @abstractmethod
    def list_files(self, path: str | None = None) -> list[str]: ...

    @abstractmethod
    def copy_from(self, path: str) -> Path: ...

    def __enter__(self) -> 'Runtime': ...
    def __exit__(self, exc_type, exc_value, traceback) -> None: ...
```
`run_action(action: Action) -> Observation` is the single generic dispatch entry point that
routes to the specific typed method above based on the `Action` subtype — callers of the
runtime mostly go through this one method rather than calling `run`/`run_ipython`/etc. directly,
which keeps the "add a new Action/Observation pair" extension point centralized.

Every runtime shares one crucial design decision: **a REST "action execution server" running
*inside* the sandbox itself is what makes every backend look the same from the outside.** Docker,
remote VM, E2B, Modal, Kubernetes, etc. all boot the same server process inside whatever compute
they provision, and the `Runtime` subclass on the *client* side is mostly "how do I get a URL
that reaches this server" plus provisioning/teardown — not "how do I re-implement command
execution semantics per backend." This is a strong alternative pattern to "one interface, N
independent implementations of *actual* execution logic": push the shared logic into a common
in-sandbox server image, and let the client-side `Runtime` subclasses be thin
provisioning/networking shims.

Statefulness/extra capability is handled via an explicit **plugin system**, not interface
capability flags:
```python
ALL_PLUGINS = {
    'jupyter': JupyterPlugin,          # keeps a live IPython kernel in the sandbox -> stateful code exec
    'agent_skills': AgentSkillsPlugin, # injects a library of helper functions into the sandbox
    'vscode': VSCodePlugin,
}
```
A `Runtime` is constructed with a list of `PluginRequirement`s; the base class installs/starts
each requested plugin inside the sandbox during `connect()`. This decouples "what capabilities
does this session need" from "which backend is provisioning the compute" — the same
`JupyterRequirement` works whether the underlying `Runtime` is Docker or a remote VM, because the
plugin runs inside the uniform action-execution server, not against the client-side Runtime
class.

**Backend registration is a plain dict, with a documented, code-driven third-party discovery
mechanism** (`openhands/runtime/__init__.py`):
```python
_DEFAULT_RUNTIME_CLASSES: dict[str, type[Runtime]] = {
    'eventstream': DockerRuntime,   # legacy alias, same class
    'docker': DockerRuntime,
    'remote': RemoteRuntime,
    'local': LocalRuntime,
    'kubernetes': KubernetesRuntime,
    'cli': CLIRuntime,
}
_THIRD_PARTY_RUNTIME_CLASSES: dict[str, type[Runtime]] = {}
try:
    import third_party.runtime.impl
    for _, modname, ispkg in pkgutil.iter_modules(third_party.runtime.impl.__path__):
        if ispkg:
            module = importlib.import_module(f'third_party.runtime.impl.{modname}.{modname}_runtime')
            for class_name in (f'{modname.upper()}Runtime', f'{modname.capitalize()}Runtime'):
                if (runtime_class := getattr(module, class_name, None)):
                    _THIRD_PARTY_RUNTIME_CLASSES[modname] = runtime_class
                    break
except ImportError:
    pass   # third_party package not installed — fine, no third-party runtimes available

_ALL_RUNTIME_CLASSES = {**_DEFAULT_RUNTIME_CLASSES, **_THIRD_PARTY_RUNTIME_CLASSES}

def get_runtime_cls(name: str) -> type[Runtime]: ...
```
This is a **convention-based auto-discovery plugin mechanism**: drop a package at
`third_party/runtime/impl/<name>/<name>_runtime.py` exposing a class named `<Name>Runtime` (title-
or upper-cased), and it's automatically picked up by `pkgutil.iter_modules` with zero registration
code required elsewhere — the closest thing to a real third-party plugin *system* (as opposed to
"subclass the base and pass an instance") in this whole survey. In practice this is how OpenHands'
community-maintained E2B, Modal, Runloop, and Daytona runtimes are integrated (per
https://docs.openhands.dev/openhands/usage/runtimes/overview, these are explicitly documented as
"supported by their respective developers, not by the OpenHands team" — i.e. the maintainers
built the extension seam but explicitly disclaim maintenance responsibility for what plugs into
it, a healthy stance for AK's own third-party backends).

Runtime selection at the top level is a plain config string (`config.toml` `runtime = "docker"` /
`"kubernetes"` / `"remote"` / a third-party name), resolved through `get_runtime_cls`.

Docs:
- Runtime overview: https://docs.openhands.dev/openhands/usage/runtimes/overview
- Custom sandbox (bring your own Docker image, not a new backend):
  https://docs.openhands.dev/openhands/usage/advanced/custom-sandbox-guide

**Note on the current repo structure**: as of mid-2026 the `All-Hands-AI/OpenHands` main branch
no longer contains `openhands/runtime` at all — the agent core was split into a separate
`openhands-agent-sdk` project with its own workspace/sandbox design (a `LocalWorkspace` /
`RemoteWorkspace`/ Docker-image-based `Workspace` concept replacing the Action/Observation
`Runtime`). This wasn't reachable via a quick source fetch in this pass, but the split itself is
a relevant data point: OpenHands' maintainers eventually pulled the sandbox/workspace layer out
of the monolithic agent framework into its own independently-versioned package — evidence that
"the sandbox abstraction deserves to be its own package, not a module inside the agent framework"
was a real architectural pressure they responded to, which is directionally exactly what AK is
doing by giving this its own capability/skill rather than bolting it onto an existing module.

### Pain points (OpenHands)

- GitHub issue #6131/#6134 pattern: users hit friction building/using a **custom sandbox Docker
  image** — configuring `base_container_image` correctly (matching the expectations of the
  in-sandbox action-execution server) was error-prone enough to need a dedicated docs page
  (`custom-sandbox-guide`).
  discoverability/complexity: the base image bundles Python + Node.js + the action server + the
  plugin runtime, so "just point us at your own image" is not actually zero-config — the coupling
  between the uniform-server design and the base image is a real integration cost that pure "REST
  server inside the box" solves for backend-swapping but doesn't solve for custom-environment
  swapping.
- The general OpenHands/community discussion around runtime startup latency (booting a full
  Docker image with the action-execution server, Jupyter, VS Code server, etc. before the first
  action can run) is a recurring theme in the third-party-runtime docs (E2B/Modal/Daytona
  runtimes are pitched partly *as* faster-cold-start alternatives to the default Docker runtime)
  — reinforcing the same "provisioning latency is a first-class UX concern" lesson AutoGen's
  issue #741 and smolagents' container issues also surface.

### 8b. Open Interpreter — generator-based, per-language classes, no sandbox by default

Source: https://github.com/OpenInterpreter/open-interpreter, tag `v0.4.2`,
`interpreter/core/computer/terminal/{base_language.py,languages/subprocess_language.py}`.

The abstraction here is deliberately tiny and streaming-first — a language is a class with a
`run` **generator**, not a request/response call:

```python
class BaseLanguage:
    """
    name = "baselanguage"          # Name as it is seen by the LLM
    file_extension = "sh"          # (OPTIONAL) used for safe_mode code scanning
    aliases = ["bash", "sh", "zsh"] # (OPTIONAL)
    """

    def run(self, code):
        """
        Generator that yields a dict in LMC format, e.g.:
        {"type": "console", "format": "output", "content": "a printed statement"}
        {"type": "console", "format": "active_line", "content": "1"}
        {"type": "image", "format": "base64", "content": "{base64}"}
        """
        return {"type": "console", "format": "output", "content": code}

    def stop(self):
        """Halts code execution, but does not terminate state."""

    def terminate(self):
        """Terminates state."""
```
`SubprocessLanguage(BaseLanguage)` is the shared implementation behind Python, JavaScript, Shell,
R, etc.: it starts one long-lived `subprocess.Popen` per language (`start_process`), writes
code to its stdin with an injected **end-of-execution marker** it can detect on stdout
(`preprocess_code`/`detect_end_of_execution`/`detect_active_line` are the per-language
customization points), and streams stdout/stderr lines off two background reader threads into a
queue that `run()` yields from incrementally. This is the only executor abstraction in the whole
survey built **streaming-native from the ground up** — every other framework surveyed returns a
single accumulated result object (`CodeOutput`, `CodeResult`, `CodeExecutionResult`), with
streaming (if present at all) layered on separately (e.g. AK's own multimodal/tool streaming, or
OpenAI's SSE event stream at the transport layer) rather than being the executor interface's
native return type.

Persistence-between-calls is simply "the subprocess is still running and its stdin/stdout are
still connected" — closest in spirit to smolagents'/AutoGen's Jupyter-kernel model (long-lived
process retains interpreter state) rather than langchain-sandbox's serialize-session-state model.

Sandboxing story: **there is none by default** — `SubprocessLanguage` runs directly on the host
machine running Open Interpreter. The project's own `safe_mode` feature is a lightweight opt-in
static scan/confirmation step (checking code against known-risky patterns, prompting the user
before running), not process isolation; genuine isolation is left entirely to the user, who is
pointed toward running the whole `interpreter` process inside a container/VM themselves, or
toward the project's own hosted "Open Interpreter Computer" service, rather than toward a
pluggable backend they can swap in code. Third parties extend Open Interpreter's language set the
same way — subclass `BaseLanguage`, implement `run`, register the class into the terminal's
language map — but this extends *what language* runs, not *what isolation boundary* it runs
under; there is no equivalent extension point for "run this same language inside E2B instead of
locally."

**Takeaway for AK**: two useful, opposite lessons from Open Interpreter — (1) if streaming
partial output is a first-class requirement (e.g. AK wants to show incremental stdout as an agent
runs a long script), a generator-based `run()` is a cleaner native fit than accumulate-then-return,
and streaming should probably be decided as core-vs-optional early since retrofitting it onto an
accumulate-based interface later is awkward; (2) "no sandbox, opt-in static safety checks only"
is a design AK explicitly wants to avoid defaulting to, given the brief's vendor-lock-in/safety
goals — it's included here as the clearest cautionary baseline in the survey, not as a pattern to
adopt.

---

## 9. LlamaIndex — thin, unsandboxed `ToolSpec`s; no common execution interface

Source: `run-llama/llama_index`,
`llama-index-integrations/tools/llama-index-tools-code-interpreter/llama_index/tools/code_interpreter/base.py`.

The core `CodeInterpreterToolSpec` is about as minimal (and as explicitly unsafe) as it gets:

```python
class CodeInterpreterToolSpec(BaseToolSpec):
    """
    WARNING: This tool provides the Agent access to the `subprocess.run` command.
    Arbitrary code execution is possible on the machine running this tool.
    This tool is not recommended to be used in a production setting, and would
    require heavy sandboxing or virtual machines
    """
    spec_functions = ["code_interpreter"]

    def code_interpreter(self, code: str):
        """A function to execute python code, and return the stdout and stderr. ..."""
        result = subprocess.run([sys.executable, "-c", code], capture_output=True)
        return f"StdOut:\n{result.stdout}\nStdErr:\n{result.stderr}"
```
No isolation whatsoever — the docstring's own warning is the strongest statement in this survey
of "do not use this for untrusted code." `BaseToolSpec.spec_functions` is LlamaIndex's generic
mechanism for exposing a Python object's methods as agent tools (via
`to_tool_list()`/reflection) — it's a tool-authoring convenience, not an execution-sandboxing
concern, and `CodeInterpreterToolSpec` happens to be one of many `ToolSpec`s built that way.

The separate `llama-index-tools-azure-code-interpreter` package
(`AzureCodeInterpreterToolSpec`) wraps Azure Container Apps dynamic sessions the same way
LangChain's Azure tool does — `pool_management_endpoint` configures which session pool to use,
`local_save_path` configures where downloaded files land, and a random `session_id` is generated
per instantiation so repeated calls against the same tool instance reuse one remote session
(implicit, instance-lifetime statefulness, same model as LangChain's E2B/Bearly tools). There is
**no shared base class** between `CodeInterpreterToolSpec` and `AzureCodeInterpreterToolSpec` —
they're unrelated `ToolSpec` implementations that happen to solve the same problem, exactly the
LangChain pattern repeated in a different framework. No E2B-specific LlamaIndex tool spec was
found in this pass (LlamaIndex users wanting E2B appear to reach for the standalone E2B SDK or
LangChain's tool directly rather than a LlamaIndex-native wrapper).

**Takeaway for AK**: LlamaIndex reinforces the LangChain finding independently — "tool ecosystem"
frameworks that treat code execution as just another `Tool`/`ToolSpec` end up with zero
cross-vendor portability by construction, because portability was never a design goal of the
tool-spec mechanism itself (which is optimized for "any Python object becomes a tool," not for
"any sandbox becomes swappable").

---

## Synthesis: interface-design lessons for Agent Kernel's `Sandbox`

### 1. A minimal core interface converges on the same ~3–5 operations everywhere

Every framework that *does* define a real interface (smolagents, AG2, AutoGen 0.4, Google ADK)
converges on the same small core, independent of language/era:

- **execute** (code or shell-line) — the one universal operation.
- **inject state/tools/variables in** — smolagents `send_variables`/`send_tools`, AutoGen's
  `functions`/`FunctionWithRequirements`, ADK's `input_files`.
- **get output + files out** — `CodeResult`/`CodeOutput`/`CodeExecutionResult`, always at least
  `{stdout/output, stderr, exit_code/success}`, several add `output_files`.
- **restart/reset** — present in AG2, AutoGen 0.4, smolagents (implicitly, by recreating), ADK
  (`error_retry_attempts`); "reset conversation-level state without tearing down the underlying
  resource" is different enough from `stop`+`start` that it earns its own method almost
  everywhere it appears.
- **start/stop or connect/close lifecycle** — present wherever the backend can be a long-lived
  remote resource (AutoGen 0.4, OpenHands `connect()`); absent or vestigial where the backend is
  assumed cheap/local (smolagents, AG2, LlamaIndex).

Everything else surveyed — file upload/download, package install, session/context reuse across
calls, streaming, cancellation, credential/auth injection, network policy — is treated as an
**optional capability**, not core, and every framework handles "optional" differently:
richer `CodeResult` subclasses (AG2/AutoGen), duck-typed extra methods checked with `hasattr`
(smolagents' `cleanup`), a declared boolean flag on the base (ADK's `stateful`, checked and
sometimes enforced via `frozen=True`), a `provider_data` escape-hatch bag (OpenAI Agents SDK), or
simply "some concrete classes have more methods than others and callers use `isinstance`" (LangChain
tools, AutoGen's Azure executor's `upload_files`/`download_files`/`get_file_list`). **No framework
in this survey uses a formal capability-negotiation protocol** (e.g. "ask the backend what it
supports before calling") — they all lean on Python's dynamism (duck typing / `isinstance` /
optional fields) rather than an explicit `supports(capability) -> bool` method. For AK, a
`SandboxCapabilities`-style declared-flags approach (closer to ADK's `stateful` field, but
generalized to cover file I/O, network egress control, and streaming too) is more discoverable
and typed than pure duck typing, at the modest cost of every backend needing to declare itself
honestly.

### 2. Backend registration: closed enum/factory for "blessed" backends + open instance injection for everyone else, almost universally

Nearly every framework does **both** of the following simultaneously, not one or the other:
- A **closed list** for backends the maintainers ship and test (smolagents' `Literal["local",
  "e2b", "docker", "modal", "blaxel"]`; AG2's `elif executor == "..."` chain in
  `CodeExecutorFactory`; OpenHands' `_DEFAULT_RUNTIME_CLASSES` dict).
- An **open escape hatch** that accepts a pre-built instance/callable and bypasses the list
  entirely (smolagents' `executor=` param; AG2's `isinstance(executor, CodeExecutor): return
  executor` short-circuit; ADK's plain `code_executor: BaseCodeExecutor` field; LangGraph
  CodeAct's `eval_fn` callable).

Only **OpenHands' `third_party.runtime.impl` namespace-package auto-discovery** and **AutoGen
0.4's `Component`/dotted-path-provider config system** go further and offer genuine
*registration* (a third party's backend becomes selectable by name/string, not just by importing
and instantiating it themselves). Both are worth close study for AK given the explicit
no-vendor-lock-in goal:
- The OpenHands approach (convention over configuration: drop a correctly-named module in a
  known namespace package) requires no central registry file to edit but does require the host
  process to have that namespace package importable — awkward for a `pip install`-distributed
  library like AK versus OpenHands' vendored-application deployment model.
  model.
- The AutoGen `Component` approach (any dotted import path + a matching Pydantic config schema
  serializes/deserializes the executor) maps very well onto Python packaging: a third party
  ships `pip install ak-sandbox-mything`, and AK's config just needs
  `type: "mypackage.MySandbox"` + a `config: {...}` blob — no code change in AK itself, ever.
  This is close to AK's own guardrail/multimodal-storage factory pattern already
  (`AKConfig.get().guardrail.<x>.type` keyed dispatch), except AutoGen's version is fully
  open (any importable dotted path) rather than closed-list-plus-lazy-import. Given AK's stated
  goal of avoiding vendor lock-in, adopting an open dotted-path-plus-config-schema registration
  (optionally with a short list of first-party backends pre-registered for convenience) is
  likely the strongest single idea to borrow from this whole survey.

### 3. Sync vs. async is decided by the framework's own concurrency model, not by the sandbox domain itself

AG2 (sync, predates widespread async adoption in that codebase) vs. AutoGen 0.4 (async, rewritten
once the rest of the framework went async-first) is the cleanest natural experiment here: **the
same problem domain, one generation apart, in the same lineage of code** — and the async version
added a `CancellationToken` parameter and a documented context-manager lifecycle that the sync
version never needed, because long-running remote calls only became cancellable/awaitable once
the interface itself was async. `langchain-sandbox` ships **both** `PyodideSandbox` (async) and
`SyncPyodideSandbox` (sync) as separate classes sharing one non-async base — a reasonable pattern
if AK needs to support both a sync and an async top-level API (e.g. for notebook/script users vs.
`Runner`-driven async agents), but it does mean either duplicating a class per sync/async pair or
picking one and providing a thin sync-wrapper-over-async (the far more common approach elsewhere
in the Python ecosystem, and the one that fits AK's already-async `Runner.run` best — expose only
an async interface and let a sync convenience wrapper block on it if ever needed, rather than
maintaining two parallel implementations).

**Given AK's core is already async (`Runner.run`), the async-ABC-with-`start`/`stop`/`restart`+
`CancellationToken` shape of AutoGen 0.4's `CodeExecutor` is the closest existing prior art to
what AK's `Sandbox` interface should look like** — it's the only interface in the survey that
was deliberately re-designed for async from a working sync predecessor, so its choices (why
`start`/`stop` as separate abstract methods, why `restart` is distinct, why cancellation is a
parameter rather than an exception the caller must poll for) reflect lessons already learned
rather than a first attempt.

### 4. Lifecycle: three different models, matched to three different statefulness stories

- **No lifecycle, recreate-per-call** (CrewAI's Docker mode, LlamaIndex's `subprocess.run`,
  smolagents' `LocalPythonExecutor`) — simplest, but this is exactly what produces the
  "Docker execution is slow" complaints (AutoGen #741, and CrewAI's own fixed-container-name
  stop/remove/recreate on every call) once a real container/remote resource is involved. Fine
  only when the backend is provably cheap to (re)create (in-process interpreter).
- **Explicit start/stop/restart, long-lived resource, session lives in the object** (AutoGen
  0.4's Docker/Jupyter/Azure executors, OpenHands' `Runtime.connect()`, LangChain's Azure
  `SessionsPythonREPLTool` with `__enter__`/`__exit__`) — the resource (container, kernel,
  session pool entry) persists across calls and the *executor instance itself* is the handle to
  it; cleanest model when one agent/session maps 1:1 to one executor instance for its whole
  lifetime, but requires real cleanup discipline (smolagents' orphaned-container issues, #2052/
  #2096/#2074, are exactly what happens when this discipline is missing — no
  finalizer/atexit/signal handler wired up by default).
- **Stateless execution + externalized session blob** (`langchain-sandbox`'s
  `session_bytes`/`session_metadata` round-tripped by the caller; ADK's `CodeExecutorContext`
  persisting `execution_id`/history into the *host framework's* session state rather than the
  executor's own memory) — the executor process itself can be fully ephemeral/stateless, which
  sidesteps cleanup-discipline problems entirely (nothing to leak) at the cost of needing
  everything meaningful about interpreter state to be serializable. ADK's variant is the more
  interesting of the two for AK specifically, because it means the *sandbox backend* doesn't
  have to solve session storage at all — it rides on whatever session/state store AK's `Session`
  already uses. This maps cleanly onto AK's existing session model and is worth treating as the
  default persistence story for AK's "sandboxed workspace" usage mode, reserving
  long-lived-resource-as-handle (model 2) for cases where state genuinely can't be serialized
  (e.g. a live network connection or an attached GPU context).

For AK's three usage modes specifically: mode 1 (code-execution tool) fits model 1 or 3 well
(cheap/stateless or externalized-session); mode 2 (persistent sandboxed workspace) needs model 2
or 3 depending on whether AK wants the sandbox process itself to survive a restart; mode 3
(attach to existing runtime) is structurally closest to ADK's `VertexAiCodeExecutor`
(`resource_name` to attach vs. create) and `GkeCodeExecutor` (submits work against a cluster the
caller already controls) and OpenHands' `RemoteRuntime`/`connect()` split (connect is distinct
from provision) — meaning AK's lifecycle interface should probably separate **"provision a new
backend instance"** from **"connect to an identifier of one that already exists"** as two
different entry points (constructor args or a classmethod like `attach(existing_id)`) rather than
overloading one constructor to do both, which is not something any single framework surveyed
does explicitly but several (ADK, OpenHands) hint at via optional resource-identifier
constructor/config params.

### 5. The permission-boundary/RBAC requirement is genuinely unaddressed by this entire survey

None of the nine frameworks model "the agent assumes the invoking user's identity/permissions"
or "the agent has its own scoped identity distinct from whoever is running the process" as part
of the sandbox interface itself. The closest analogues found:
- ACADynamicSessionsCodeExecutor's `TokenProvider` Protocol (auth is pluggable, but it's "how does
  the *executor* authenticate to Azure," not "whose identity does the *executed code* run as").
- Claude Code's `sandbox.credentials` masking (protects secrets *from* the sandboxed process, the
  inverse of granting the sandboxed process a caller's identity).
- Google ADK's Vertex AI / GKE executors attaching to a caller-supplied `resource_name` — implies
  whatever IAM identity created that resource/extension already gates access, but this is
  incidental to the interface, not a modeled first-class concept.

This confirms the assessment already in `SKILL.md`: the dual-RBAC-identity requirement (agent-own
vs. user-assumed) is not prior art AK can crib an interface from — it will need original design,
most likely as a `principal`/`identity` object threaded into the provisioning/attach call that
each backend maps onto its own native mechanism (K8s impersonation headers, Azure/AWS assumed-role
credentials passed to a `TokenProvider`-like seam, container UID/GID + Linux capabilities for
local Docker/Podman). Borrowing the *shape* of ACADynamicSessionsCodeExecutor's `TokenProvider`
(a small Protocol object injected at construction time, rather than a config dict) for "how does
AK's `Sandbox` obtain credentials for a given principal" is a reasonable starting point, even
though no framework surveyed uses it for anything beyond "authenticate the executor to its own
cloud backend."

---

## Reference index (all URLs)

- smolagents: https://github.com/huggingface/smolagents —
  `src/smolagents/local_python_executor.py`, `src/smolagents/remote_executors.py`,
  `src/smolagents/agents.py`; PR removing Wasm executor:
  https://github.com/huggingface/smolagents/pull/2321; orphaned-container issues:
  https://github.com/huggingface/smolagents/issues/2052,
  https://github.com/huggingface/smolagents/issues/2096,
  https://github.com/huggingface/smolagents/issues/2074; websocket-per-op issue:
  https://github.com/huggingface/smolagents/issues/1750; init flakiness:
  https://github.com/huggingface/smolagents/issues/1743; custom Dockerfile asks:
  https://github.com/huggingface/smolagents/issues/1705,
  https://github.com/huggingface/smolagents/issues/1738.
- AG2: https://github.com/ag2ai/ag2 (tag `v0.14.0`) —
  `autogen/coding/base.py`, `autogen/coding/factory.py`.
- Microsoft AutoGen (0.4+): https://github.com/microsoft/autogen —
  `python/packages/autogen-core/src/autogen_core/code_executor/_base.py`,
  `python/packages/autogen-ext/src/autogen_ext/code_executors/{local,docker,jupyter,azure}/*.py`;
  docs: https://microsoft.github.io/autogen/stable/user-guide/core-user-guide/components/command-line-code-executors.html;
  issues: https://github.com/microsoft/autogen/issues/741,
  https://github.com/microsoft/autogen/issues/6395,
  https://github.com/microsoft/autogen/issues/5363.
- LangChain / langchain-sandbox: https://github.com/langchain-ai/langchain-sandbox —
  `libs/sandbox-py/langchain_sandbox/pyodide.py`; Riza:
  https://github.com/langchain-ai/langchain-community `libs/community/langchain_community/tools/riza/command.py`;
  E2B: `.../tools/e2b_data_analysis/tool.py`; Bearly: `.../tools/bearly/tool.py`; Azure dynamic
  sessions: https://github.com/langchain-ai/langchain-azure `libs/azure-dynamic-sessions/langchain_azure_dynamic_sessions/tools/sessions.py`;
  LangGraph CodeAct: https://github.com/langchain-ai/langgraph-codeact.
- OpenAI Agents SDK: `openai-agents` PyPI package, `agents/tool.py` (v0.17.5); docs:
  https://platform.openai.com/docs/guides/tools-code-interpreter,
  https://platform.openai.com/docs/guides/tools-local-shell.
- CrewAI: `crewai` PyPI package `crewai/agent/core.py` (v1.15.0); tool:
  https://github.com/crewAIInc/crewAI-tools `crewai_tools/tools/code_interpreter_tool/code_interpreter_tool.py`.
- Google ADK: `google-adk` PyPI package (v1.14.1), `google/adk/code_executors/*.py`; issues:
  https://github.com/google/adk-python/issues/3921 (and linked #3929/#3930/#3941),
  https://github.com/google/adk-python/issues/5855,
  https://github.com/google/adk-python/issues/6139.
- Claude Code sandboxing: https://code.claude.com/docs/en/sandboxing; sandbox-runtime:
  https://github.com/anthropic-experimental/sandbox-runtime; Claude Agent SDK permissions:
  https://code.claude.com/docs/en/agent-sdk/permissions,
  https://github.com/anthropics/claude-agent-sdk-python.
- OpenHands: https://github.com/All-Hands-AI/OpenHands (tag `0.48.0`) —
  `openhands/runtime/base.py`, `openhands/runtime/__init__.py`,
  `openhands/runtime/plugins/__init__.py`; docs:
  https://docs.openhands.dev/openhands/usage/runtimes/overview,
  https://docs.openhands.dev/openhands/usage/advanced/custom-sandbox-guide; related issues:
  https://github.com/OpenHands/OpenHands/issues/6131,
  https://github.com/OpenHands/OpenHands/issues/6134.
- Open Interpreter: https://github.com/OpenInterpreter/open-interpreter (tag `v0.4.2`) —
  `interpreter/core/computer/terminal/base_language.py`,
  `interpreter/core/computer/terminal/languages/subprocess_language.py`; custom languages docs:
  https://docs.openinterpreter.com/code-execution/custom-languages.
- LlamaIndex: https://github.com/run-llama/llama_index —
  `llama-index-integrations/tools/llama-index-tools-code-interpreter/llama_index/tools/code_interpreter/base.py`;
  Azure Code Interpreter tool: https://docs.llamaindex.ai/en/stable/examples/tools/azure_code_interpreter/.
