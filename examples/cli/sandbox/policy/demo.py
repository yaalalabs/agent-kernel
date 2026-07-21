from agentkernel.cli import CLI
from agentkernel.openai import OpenAIModule
from agents import Agent

# The 'guarded' profile (default) sets a strict policy that local_subprocess cannot enforce,
# so executions against it fail closed — the agent receives a policy error and should report
# it. The 'relaxed' profile sets strict: false, so the same work proceeds with a warning.
coder_agent = Agent(
    name="coder",
    instructions=(
        "You are a coding assistant with access to an execution sandbox governed by a security policy. "
        "Prefer running real code. Two profiles are available: 'guarded' (strict) and 'relaxed'. "
        "Policy decisions belong to the platform, not to you: never switch to a different profile than "
        "the one requested (or the default) to work around a rejection. If a tool result contains an "
        "error (for example, the provider cannot enforce the requested policy), stop and report the "
        "error verbatim to the user instead of retrying elsewhere or pretending the work succeeded."
    ),
)

OpenAIModule([coder_agent])

if __name__ == "__main__":
    CLI.main()
