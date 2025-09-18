from .. import Agent
from ..core import Runtime


class A2A:

    @staticmethod
    def get_cards():
        cards = []
        agents: dict[str, Agent] = Runtime.instance().agents()
        for agent in agents.values():
            cards.append(agent.get_a2a_card())
