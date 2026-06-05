from agentkernel.deployment.aws.containerized import ECSRESTService

# REST Service entrypoint — no agent definitions needed here.
# Thread 1: FastAPI handles POST /chat (enqueues to Input Queue, waits on DynamoDB)
#           and GET /chat/{sessionId} (REST Async mode only)
# Thread 2: Output-queue poller — writes responses to DynamoDB (sync/async)
#           or pushes via WebSocket PostToConnection (async/WS mode)
runner = ECSRESTService.run

if __name__ == "__main__":
    runner()
