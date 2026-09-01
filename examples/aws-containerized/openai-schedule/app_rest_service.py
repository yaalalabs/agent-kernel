"""REST service entrypoint: chat ingress plus the scheduled-task management routes.

`ECSIOHandler.run()` starts the two peer threads this container needs — the REST API and the
output-queue consumer. The schedule routes are not mounted from config, so they are passed as
`handlers` and served alongside the API's own chat route, exactly as on the pipeline's `IOHandler`.

Those routes are served **in this process**, not through the queues: they talk to the shared
DynamoDB task store and EventBridge Scheduler directly, so a listing or a cancellation does not
need a round trip through the queues.

Add `authoriser=...` to the `ScheduleRESTRequestHandler(...)` call below to protect them; without
one they are open and accept any `user_id`.
"""

from agentkernel.aws import ECSIOHandler
from agentkernel.schedule import ScheduleRESTRequestHandler

if __name__ == "__main__":
    ECSIOHandler.run(handlers=[ScheduleRESTRequestHandler()])
