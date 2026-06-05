from agentkernel.deployment.aws.containerized import ECSRESTService

# REST Service entrypoint — NO agent definitions.
# Agents are ONLY defined in the Agent Runner (app_agent_runner.py).
# 
# Thread 1: FastAPI handles POST /chat (enqueues to Input Queue, waits on DynamoDB)
#           Agent validation happens in the Agent Runner, not here.
# Thread 2: Output-queue poller — writes responses to DynamoDB (sync/async)
runner = ECSRESTService.run

if __name__ == "__main__":
    runner()
