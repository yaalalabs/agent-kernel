"""
Pickle-safety checks shared by the two things Agent Kernel persists on a session.

The session store pickles the whole session, so a value that cannot be pickled breaks the store
long after the code that stored it has returned. Both `Runner`'s per-run framework context and the
human-in-the-loop paused-run record therefore fail fast at write time instead, and share these
helpers so the check has one implementation.
"""

import pickle
from typing import Any, Mapping


def not_picklable(value: Any) -> bool:
    """
    Checks whether the given value can be pickled.

    :param value: The value to test.
    :return: True if the value cannot be pickled.
    """
    try:
        pickle.dumps(value)
        return False
    except Exception:
        return True


def first_unpicklable_entry(mapping: Mapping[str, Any]) -> str:
    """
    Names the first entry in a mapping that cannot be pickled, for use in an error message.

    :param mapping: The mapping to inspect.
    :return: A "key (type)" description, or "<unknown key>" when every entry pickles on its own.
    """
    return next(
        (f"{key!r} ({type(value).__name__})" for key, value in mapping.items() if not_picklable(value)),
        "<unknown key>",
    )
