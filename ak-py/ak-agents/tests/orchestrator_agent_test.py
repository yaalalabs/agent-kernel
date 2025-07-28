import unittest

from ak_agents.orchestrator import OrchestratorAgent
from ak_common.log.logger import get_logger


class OrchestratorAgentTest(unittest.TestCase):
    def test_orchestrator(self):
        orchestrator = OrchestratorAgent()
        log = get_logger("SampleLogger")
        log.info(f"Error message: {orchestrator.get_error()}")
        self.assertEqual(True, True)  # add assertion here
