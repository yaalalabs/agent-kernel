from agentkernel.aws import Lambda

from evaluator.api import EvaluationAPI

# /chat is served by Lambda.handler itself: it enqueues each request for the agent runner
api = EvaluationAPI.from_env()


@Lambda.register("/eval", method="POST")
def start_evaluation(event, context):
    """Fetches the session's traces and starts grading the ready ones."""
    return api.start_evaluation(event, context)


@Lambda.register("/check", method="GET")
def check_progress(event, context):
    """Counts the session's traces by progress."""
    return api.check_progress(event, context)


@Lambda.register("/grade", method="POST")  # internal: /eval invokes it; not exposed by API Gateway
def grade_traces(event, context):
    """Judges the traces /eval marked grading and stores the results."""
    return api.grade_traces(event, context)


handler = Lambda.handler
