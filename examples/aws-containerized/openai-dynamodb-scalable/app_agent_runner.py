import logging
import signal
import sys
import time

logging.basicConfig(level=logging.INFO)

running = True


def shutdown(*args):
    global running
    logging.info("Shutdown requested")
    running = False


signal.signal(signal.SIGTERM, shutdown)
signal.signal(signal.SIGINT, shutdown)

logging.info("Agent Runner starting")

while running:
    time.sleep(30)
    logging.info("Agent Runner heartbeat")

logging.info("Agent Runner stopping")
sys.exit(0)