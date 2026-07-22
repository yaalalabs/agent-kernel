from agentkernel.cli import CLI
from agentkernel.openai import OpenAIModule
from agents import Agent

# All profiles are docker-backed. 'guarded' (default) sets a fully enforceable policy, so
# executions run inside the envelope (no network, cpu/memory limits). 'restricted' sets an
# egress allowlist docker cannot enforce, so with strict: true executions against it fail
# closed. 'relaxed' opts out with strict: false and proceeds with a warning.
coder_agent = Agent(
    name="coder",
    instructions=(
        "You are a coding assistant with access to an execution sandbox governed by a security policy. "
        "Prefer running real code. Three profiles are available: 'guarded' (default), 'restricted', and "
        "'relaxed'. Policy decisions belong to the platform, not to you: never switch to a different "
        "profile than the one requested (or the default) to work around a rejection or a blocked "
        "network. If a tool result contains an error (for example, the provider cannot enforce the "
        "requested policy), stop and report the failure honestly instead of retrying elsewhere or "
        "pretending the work succeeded; if the user asked for a specific reply on failure, answer "
        "with exactly that."
    ),
)

OpenAIModule([coder_agent])

if __name__ == "__main__":
    CLI.main()
