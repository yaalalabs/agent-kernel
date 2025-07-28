from ak_agents.orchestrator import OrchestratorAgent
from ak_common.log.logger import get_logger

log = get_logger("Main")


def main():
    print("Hello from travel-manager-agent!")
    orchestrator = OrchestratorAgent()
    error = orchestrator.get_error()
    log.info(f"Error Message: {error}")


if __name__ == "__main__":
    main()
