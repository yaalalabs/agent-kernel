import os
import time


def get_timestamp() -> int:
    return int(time.time() * 1000)


def get_timestamp_seconds() -> int:
    return int(time.time())


def get_env_var(variable_name):
    return os.environ.get(variable_name)
