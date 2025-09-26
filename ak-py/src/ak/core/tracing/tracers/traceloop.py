from typing import Any, Dict, Optional
from traceloop.sdk import Traceloop

from .base import Tracer


class TraceloopTracer(Tracer):
    def __init__(self, app_name: str = "ak-py", variables: Optional[Dict[str, Any]] = None):
        super().__init__(app_name=app_name, variables=variables)
        self.init()

    def init(self) -> None:
        Traceloop.init(app_name=self.app_name)

    def set_custom_tracing_params(self, params: Dict[str, Any]) -> None:
        Traceloop.set_association_properties(params)