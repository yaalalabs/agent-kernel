from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import state


class MemoryCache:
    def __init__(self) -> None:
        self.data: dict[str, object] = {}

    def get(self, key: str, default=None):
        return copy.deepcopy(self.data.get(key, default))

    def set(self, key: str, value) -> None:
        self.data[key] = copy.deepcopy(value)

    def delete(self, key: str) -> bool:
        return self.data.pop(key, None) is not None


@pytest.fixture
def memory_cache(monkeypatch) -> MemoryCache:
    cache = MemoryCache()
    monkeypatch.setattr(state, "_cache", lambda: cache)
    return cache
