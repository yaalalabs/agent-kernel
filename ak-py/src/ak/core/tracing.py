from traceloop.sdk import Traceloop

class TraceloopTracing:
    def __init__(self, app_name:str="ak-py"):
        Traceloop.init(app_name=app_name)

    def set_custom_tracing_params(self, params:dict):
        Traceloop.set_association_properties(params)