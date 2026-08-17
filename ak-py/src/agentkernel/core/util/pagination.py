"""
Shared cursor-pagination helpers for resource listings (conversation threads,
scheduled tasks).

The cursor is an opaque wrapper over a numeric offset: stores work purely in
(limit, offset) terms and return (page, next_offset); the service layer owns
the encode/decode, so backends need no cursor awareness.
"""

import base64
from typing import Optional

# Cap applied to every requested page size.
MAX_PAGE_SIZE = 200


def encode_cursor(offset: Optional[int]) -> Optional[str]:
    """Encode a numeric page offset into an opaque cursor token, or None."""
    if offset is None:
        return None
    return base64.urlsafe_b64encode(str(offset).encode()).decode()


def decode_cursor(cursor: Optional[str]) -> int:
    """Decode an opaque cursor token back into a numeric offset (0 when absent).

    :raises ValueError: If the cursor is present but malformed.
    """
    if not cursor:
        return 0
    try:
        offset = int(base64.urlsafe_b64decode(cursor.encode()).decode())
    except Exception:
        raise ValueError("Invalid pagination cursor")
    if offset < 0:
        raise ValueError("Invalid pagination cursor")
    return offset


def clamp_limit(limit: Optional[int], default: int) -> int:
    """Clamp a requested page size into [1, MAX_PAGE_SIZE], defaulting when absent."""
    if not limit or limit < 1:
        return default
    return min(limit, MAX_PAGE_SIZE)


def paginate(items: list, limit: int, offset: int) -> tuple[list, Optional[int]]:
    """Slice an in-order list into an offset/limit page.

    For backends that hold or fetch the whole ordered collection (in-memory maps, scans,
    document reads) and page it in the store layer.

    :param items: The full, ordered list of items.
    :param limit: Maximum number of items in the page.
    :param offset: Zero-based index of the first item.
    :return: A tuple of (page, next_offset); next_offset is None on the last page.
    """
    if offset < 0:
        offset = 0
    page = items[offset : offset + limit]
    next_offset = offset + limit if offset + limit < len(items) else None
    return page, next_offset
