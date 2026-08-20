"""REST service entrypoint: chat ingress plus the scheduled-task management routes.

`ECSIOHandler.run()` would be enough for chat alone, but it builds the FastAPI app from
`AWSRestAPI`'s default handlers, which do not include `ScheduleRESTRequestHandler`. This module
composes the same two peer threads ECSIOHandler runs — the REST API and the output-queue
consumer — with the schedule routes added to the app, using only public API.
"""

from agentkernel.aws import AWSRestAPI, ECSOutputConsumer
from agentkernel.pipeline import ThreadRunner
from agentkernel.schedule import ScheduleRESTRequestHandler


class ScheduleAwareRestAPI(AWSRestAPI):
    """AWSRestAPI plus the schedule management routes.

    The inherited default handler enqueues chat requests to SQS (validation and execution happen
    in the agent runner). ScheduleRESTRequestHandler is served in this process instead: it talks
    to the shared DynamoDB task store and EventBridge Scheduler directly, so a listing or a
    cancellation does not need a round trip through the queues.

    Pass `authoriser=` to protect the routes; without one they are open and accept any `user_id`.
    """

    @classmethod
    def get_default_handlers(cls):
        return AWSRestAPI.get_default_handlers() + [ScheduleRESTRequestHandler()]


def main() -> None:
    ThreadRunner.run(
        tasks=[
            ThreadRunner.Task(
                execution_function=ScheduleAwareRestAPI.run,
                thread_name="rest-api",
                stop_all_on_failure=True,
                graceful=True,
                # uvicorn.run() only stops on an OS signal, so it cannot report completion.
                awaited_on_shutdown=False,
            ),
            ThreadRunner.Task(
                execution_function=lambda: ECSOutputConsumer.run(),
                thread_name="output-queue-consumer",
                stop_all_on_failure=True,
            ),
        ],
        max_workers=2,
    )


if __name__ == "__main__":
    main()
