from ak_agents.orchestrator import OrchestratorAgent
from ak_common.log.logger import get_logger


class TravelAgentOrchestrator(OrchestratorAgent):
    def __init__(self):
        self.log = get_logger(self.__class__.__name__)
        super().__init__()
        self.log.info("Hello from travel manager!")

    def execute(self):
        error = self.get_error()
        self.log.error(f"Execution error: {error}")
        return error
