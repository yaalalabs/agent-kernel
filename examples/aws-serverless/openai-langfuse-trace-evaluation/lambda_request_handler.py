from agentkernel.aws import Lambda

from evaluator.api import EvaluationAPI

# /chat is served by Lambda.handler itself: it enqueues each request for the agent runner
api = EvaluationAPI()


@Lambda.register("/eval", method="POST")
def start_evaluation(event, context):
    """Starts grading the session's traces."""
    return api.start_evaluation(event, context)


@Lambda.register("/check", method="GET")
def check_results(event, context):
    """Returns the session's graded rows."""
    return api.check_results(event, context)


def handler(event, context):
    """Runs the grading when /eval invoked this Lambda with START_GRADE; routes every API request as usual."""
    # START_GRADE is a plain Lambda event, not an API Gateway request, so it can't be sent through the API
    if event.get("action") == EvaluationAPI.START_GRADE:
        return api.grade(event)
    return Lambda.handler(event, context)
