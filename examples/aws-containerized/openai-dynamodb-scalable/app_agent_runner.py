# from agentkernel.deployment.aws.containerized import ECSAgentRunner
# from agentkernel.openai import OpenAIModule
# from agents import Agent

# math_agent = Agent(
#     name="math",
#     handoff_description="Specialist agent for math questions",
#     instructions="You provide help with math problems. Explain your reasoning at each step and include examples. \
#         If prompted for anything else you refuse to answer.",
# )

# history_agent = Agent(
#     name="history",
#     handoff_description="Specialist agent for historical questions",
#     instructions="You provide assistance with historical queries. Explain important events and context clearly.",
# )

# triage_agent = Agent(
#     name="triage",
#     instructions="You determine which agent to use based on the user's question.",
#     handoffs=[history_agent, math_agent],
# )

# OpenAIModule([triage_agent, math_agent, history_agent])

# # Agent Runner entrypoint - polls Input Queue, runs agent, sends to Output Queue.
# handler = ECSAgentRunner.run

# if __name__ == "__main__":
#     handler()

import logging
import signal
import sys
import time

logging.basicConfig(level=logging.INFO)

running = True


def shutdown(*args):
    global running
    logging.info("Shutdown requested")
    running = False


signal.signal(signal.SIGTERM, shutdown)
signal.signal(signal.SIGINT, shutdown)

logging.info("Agent Runner starting")

while running:
    time.sleep(30)
    logging.info("Agent Runner heartbeat")

logging.info("Agent Runner stopping")
sys.exit(0)