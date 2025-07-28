import unittest
from travel_agent.travel_agent_orchestrator import TravelAgentOrchestrator


class OrchestratorAgentTest(unittest.TestCase):
    def test_travel_agent(self):
        orchestrator = TravelAgentOrchestrator()
        message = orchestrator.execute()
        self.assertEqual(True, True)  # add assertion here
