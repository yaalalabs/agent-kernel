from ak import CLI
from ak_openai import AgentModule

from agent import triage_agent, math_agent, history_agent

AgentModule([triage_agent, math_agent, history_agent])

if __name__ == "__main__":
    CLI.main()
