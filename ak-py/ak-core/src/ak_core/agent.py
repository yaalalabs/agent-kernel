from ak_common.log.logger import get_logger


class Agent:
    def __init__(self):
        log = get_logger(Agent.__name__)
        log.info("Agent initialized!")
