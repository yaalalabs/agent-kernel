"""REST service entrypoint: chat ingress plus the scheduled-task management routes.

`ECSIOHandler.run()` starts the two peer threads this container needs — the REST API and the
output-queue consumer. The schedule routes are not mounted from config, so they are passed as
`handlers` and served alongside the API's own chat route, exactly as on the pipeline's `IOHandler`.

Those routes are served **in this process**, not through the queues: they talk to the shared
DynamoDB task store and EventBridge Scheduler directly, so a listing or a cancellation does not
need a round trip through the queues.

Who is calling comes from the `identity` block in config.yaml: the identity dependency on every
route turns the bearer token into the request's principal, a task belongs to the principal whose
request created it, and the management routes serve the caller's own tasks. The handler refuses to
build without the block.
"""

from agentkernel.aws import ECSIOHandler
from agentkernel.schedule import ScheduleRESTRequestHandler

if __name__ == "__main__":
    ECSIOHandler.run(handlers=[ScheduleRESTRequestHandler()])
