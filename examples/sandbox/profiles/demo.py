from agentkernel.cli import CLI
from agentkernel.openai import OpenAIModule
from agents import Agent

# The sandbox capability injects the list of available profiles into the agent's system
# prompt, so the agent's instructions only need to say *when* to use which profile.
coder_agent = Agent(
    name="coder",
    instructions=(
        "You are a coding assistant with access to an execution sandbox that offers two profiles: "
        "'workspace' (persistent, for multi-step work whose files should survive across turns) and "
        "'scratch' (a fresh throwaway sandbox per call, for one-off checks). "
        "Use the workspace profile by default; use the scratch profile when the user asks for a quick, "
        "isolated one-off. Give short, direct answers backed by what you actually executed."
    ),
)

OpenAIModule([coder_agent])

if __name__ == "__main__":
    CLI.main()
