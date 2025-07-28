from ak_common.model.error import Error
from ak_common.util.common import get_timestamp
from ak_core.agent import Agent


class OrchestratorAgent(Agent):
    def __init__(self):
        super().__init__()

    @staticmethod
    def get_error():
        timestamp = get_timestamp()
        return Error(
            code="SAMPLE_ERROR_CODE",
            message=f"Error generated at {timestamp}"
        )
