"""Knowledge-base capability declaration and record typing.

A backend declares what it actually supports in a :class:`KnowledgeCapabilities`;
:class:`agentkernel.knowledgebase.base.KnowledgeBase` routes on that declaration and
``KnowledgeBuilder`` gates its agent tools on it. An operation a backend does not
declare raises :class:`agentkernel.knowledgebase.errors.KnowledgeCapabilityError`
rather than returning an empty result, so an honest declaration is load-bearing.

The two ``TypedDict``s here document the record shape that travels between backends
and tools. They are never validated at runtime — ``Record = Mapping[str, Any]``
stays the annotation on every signature.
"""

from typing import Literal, TypedDict

from pydantic import BaseModel, Field


class KnowledgeCapabilities(BaseModel):
    """What a backend actually supports; undeclared operations raise ``KnowledgeCapabilityError``."""

    # Intentionally free of cross-field validators. The two invariants a declaration must
    # satisfy — being reachable at all, and query/query_language coherence — are enforced in
    # KnowledgeBase.__init__, because each error has to name the offending backend and a
    # capabilities object does not know its owner. An application can therefore build one of
    # these for inspection without owning a backend.

    kinds: list[str] = Field(default_factory=list)  # open taxonomy: vector|structured|graph|document|…
    search: bool = False  # relevance retrieval
    search_mode: Literal["semantic", "lexical"] | None = None  # advisory only; deliberately not bidirectional with search
    query: bool = False  # query-language retrieval
    query_language: str | None = None  # e.g. "cypher", "sql"
    fetch: bool = False  # retrieval by identity
    browse: bool = False  # namespace enumeration
    writable: bool = False
    derives_schema: bool = False  # schema() self-describes without add_schema()


class KnowledgeMetadata(TypedDict, total=False):
    """Conventional metadata keys on a record; documentation-only, never validated.

    ``id`` is required in the metadata of every record a backend declaring ``fetch``
    returns, and must contain no ``,`` (the tool surface splits id lists on it). That
    rule is asserted by ``KnowledgeBaseContract``, not at runtime — a backend is free
    to carry keys beyond these.
    """

    id: str  # backend-native identity
    source: str
    title: str
    kind: str
    trust: str
    stale: bool
    links: list[str]


class KnowledgeRecord(TypedDict, total=False):
    """One record as backends return it and tools format it; documentation-only, never validated."""

    text: str
    metadata: KnowledgeMetadata
