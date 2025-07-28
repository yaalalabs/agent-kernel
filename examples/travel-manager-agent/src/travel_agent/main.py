from ak_common.log.logger import get_logger

from travel_agent.travel_agent_orchestrator import TravelAgentOrchestrator

log = get_logger("Main")


def main():
    print("Hello from travel-manager-agent!")
    travel_manager = TravelAgentOrchestrator()
    message = travel_manager.execute()
    log.info(f"Execution Message: {message}")


if __name__ == "__main__":
    main()
