from ak_common.log.logger import get_logger


class Agent:
    def __init__(self, name):
        log = get_logger(name)
        log.info("Agent initialized")
