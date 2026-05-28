---
name: ak-dev-new-knowledgebase-integration
description: >
  Step-by-step guide for adding a new knowledge base backend to Agent Kernel.
  Use this skill when you need to integrate a new storage system with the
  KnowledgeBase interface and expose it through KnowledgeBuilder tools.
license: Apache-2.0
metadata:
  author: yaalalabs
  category: developer
---

# Adding a New Knowledge Base Integration

Use this skill to add a new knowledge base backend under `ak-py/src/agentkernel/knowledgebase/`.

This applies when you are integrating any durable source not already covered by:
- `ChromaManager` (semantic vector search)
- `Neo4jManager` (graph relationships)
- `StarburstManager` (read-only SQL via Trino)

## Prerequisites

- Understand architecture and contribution patterns from `.agents/skills/ak-dev-architecture/SKILL.md`
- Understand existing knowledge base APIs:
  - `ak-py/src/agentkernel/knowledgebase/base.py`
  - `ak-py/src/agentkernel/knowledgebase/knowledgebuilder.py`
- Have provider credentials and a local/dev test instance for the target backend

## Step-by-Step

### 1. Create Backend Module

Create a new file:

`ak-py/src/agentkernel/knowledgebase/<backend>.py`

Use lowercase file names (for example `qdrant.py`, `milvus.py`, `elasticsearch.py`).

### 2. Subclass `KnowledgeBase`

Implement a concrete class that extends `KnowledgeBase`:

```python
from typing import Any, Iterable, List, Mapping

from .base import KnowledgeBase, Record


class MyBackendManager(KnowledgeBase):
    def __init__(self, name: str = "", description: str | None = None, **kwargs):
        super().__init__()
        self.name = name
        self.description = description or "my backend"
        self._client = None
        self.connect(**kwargs)

    @property
    def backend_name(self) -> str:
        return self.name if self.name else "mybackend"

    def connect(self, **kwargs) -> None:
        # Initialize backend client and verify connectivity.
        self._client = ...

    def write(self, records: Iterable[Record], **kwargs) -> None:
        for record in records:
            text = str(record.get("text", "")).strip()
            metadata = dict(record.get("metadata", {}))
            if not text:
                continue
            # Persist text + metadata using backend-native API.
            self._client.store(text=text, metadata=metadata)

    def read(self, query: str, limit: int = 3, **kwargs) -> List[Mapping[str, Any]]:
        rows = self._client.search(query=query, limit=limit)
        return [{"text": row["text"], "metadata": row.get("metadata", {})} for row in rows]

    def get_description(self) -> str:
        return f"{self.backend_name}: {self.description}"
```

### 3. Respect the Record Contract

All reads must return normalized rows compatible with `KnowledgeBuilder`:
- `{"text": str, "metadata": dict}`

All writes accept the same shape through `write(records=[...])`.

If the provider result is not in this shape, normalize inside `read()`.

### 4. Define Backend Constraints Explicitly

If the backend is read-only, enforce it in code:

```python
def write(self, records, **kwargs) -> None:
    raise NotImplementedError("This backend is read-only.")
```

Do not silently ignore writes.

### 5. Add Robust Connection Handling

- Validate required configuration fields in `connect()`
- Fail fast with clear `ValueError` messages for missing settings
- Add reconnection logic when the provider client commonly drops stale sessions
- Implement `close()` if the backend has sockets, cursors, or open sessions

### 6. Add Optional Dependencies

Update `ak-py/pyproject.toml` with a new optional dependency group:

```toml
[project.optional-dependencies]
mybackend = [
    "provider-sdk>=x.y.z",
]
```

Keep dependency groups narrow and provider-specific.

### 7. Add Usage Example

Add or update example code under `examples/cli/knowledgebase/openai/` showing:
- backend initialization
- schema registration via `.add_schema(...)`
- `KnowledgeBuilder([...], semantic_map=...)`
- tool binding using `OpenAIToolBuilder.bind(kb.build())`

Reference pattern:
- `examples/cli/knowledgebase/openai/chromadb/demo.py`
- `examples/cli/knowledgebase/openai/neo4j/demo.py`
- `examples/cli/knowledgebase/openai/starburst/demo.py`
- `examples/cli/knowledgebase/openai/multi/demo.py`

### 8. Add/Update Documentation

Document the backend in:
- `docs/docs/architecture/knowledge-bases.md`
- `docs/docs/core-concepts/overview.md` (if backend list appears there)

Include:
- when to use this backend
- read/write constraints
- required environment variables
- schema/query guidance for routing agents

### 9. Add Tests

Add tests in `ak-py/tests/` for:
- successful connection path
- input validation for missing config
- `read()` normalization (`text` + `metadata`)
- `write()` behavior (including read-only exception if applicable)
- `backend_name` uniqueness assumptions and descriptive output

Prefer mocked provider clients to avoid flaky external calls.

### 10. Verify KnowledgeBuilder Compatibility

Validate that your backend works with `KnowledgeBuilder.build()` and tools:
- `get_schemas()` returns your backend schema
- `read_kb()` routes correctly to your backend name
- `write_kb()` behaves as expected (or returns readable errors)

## Checklist

- [ ] New backend module created under `ak-py/src/agentkernel/knowledgebase/`
- [ ] Class subclasses `KnowledgeBase` and implements required members
- [ ] Read results normalized to `{"text", "metadata"}` records
- [ ] Connection handling includes validation and clear errors
- [ ] Optional dependency group added to `ak-py/pyproject.toml`
- [ ] Example added/updated under `examples/cli/knowledgebase/openai/`
- [ ] Documentation updated in knowledge base architecture docs
- [ ] Tests added for connect/read/write/constraints
- [ ] Backend verified through `KnowledgeBuilder` tools
