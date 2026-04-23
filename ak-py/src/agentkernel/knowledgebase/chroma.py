import hashlib
import logging
from typing import Any, Iterable, List, Mapping, Optional

import chromadb
from chromadb.utils import embedding_functions

from .base import KnowledgeBase

log = logging.getLogger("ak.ChromaManager")


class ChromaManager(KnowledgeBase):
    """
    ChromaDB backend — best for semantic / fuzzy text recall.
    Use this when the agent needs to find information by meaning, not exact structure.
    """

    def __init__(
        self,
        persist_path: str = "./chroma_db",
        name: str = "",
        collection_name: str = "knowledge_base",
        description: str = "chroma vector database",
        embedding_function: Optional[Any] = None,
    ):  # pass in a description
        """
        Initialize a ChromaDB-backed knowledge manager.

        :param persist_path: Filesystem path where Chroma persists collection data.
        :param name: Logical backend name exposed to the agent tool layer.
        :param collection_name: Chroma collection name used for reads and writes.
        :param description: Human-readable backend description for tool selection.
        :param embedding_function: Optional Chroma embedding function implementation.
            If omitted, the default Chroma embedding function is used.
        :return: None.
        """
        super().__init__()
        self.persist_path = persist_path
        self.client = None
        self.collection = None
        self.name = name
        self.description = description
        self.collection_name = collection_name
        self.embedding_function = embedding_function or embedding_functions.DefaultEmbeddingFunction()
        self.connect()

    @property
    def backend_name(self) -> str:
        """
        Return the backend identifier used by the knowledge router.

        :return: Configured backend name, or ``chromadb`` when name is empty.
        """
        log.debug(f"[backend_name] returning backend_name={self.name if self.name else 'chromadb'}")
        return self.name if self.name else "chromadb"

    def connect(self, **kwargs) -> None:
        """
        Create or open the Chroma persistent collection connection.

        :param kwargs: Reserved for interface compatibility.
        :return: None.
        """
        try:
            self.client = chromadb.PersistentClient(path=self.persist_path)
            self.collection = self.client.get_or_create_collection(
                name=self.collection_name,
                embedding_function=self.embedding_function,
            )
            log.debug(f"[connect] Connected to ChromaDB at {self.persist_path}, collection '{self.collection_name}' ready.")
        except Exception as e:
            log.error(f"[connect] Failed to connect to ChromaDB at {self.persist_path}: {e}")
            raise

    def write(self, records: Iterable[Mapping[str, Any]], **kwargs) -> None:
        """
        Upsert text records into the Chroma collection.

        Empty text payloads are skipped. Record ids are deterministically derived
        from content and source metadata to make repeated writes idempotent.

        :param records: Iterable of records containing ``text`` and optional
            ``metadata`` keys.
        :param kwargs: Reserved for interface compatibility.
        :return: None.
        """
        texts, metadatas, ids = [], [], []
        for r in records:
            text = str(r.get("text", "")).strip()
            if not text:
                continue
            meta = dict(r.get("metadata", {}))
            texts.append(text)
            metadatas.append(meta)

            ids.append(hashlib.md5((text + str(meta.get("source", ""))).encode()).hexdigest())

        if texts:
            self.collection.upsert(documents=texts, metadatas=metadatas, ids=ids)

    def read(self, query: str, limit: int = 3, **kwargs) -> List[Mapping[str, Any]]:
        """
        Query the Chroma collection for semantically similar documents.

        :param query: Natural-language query text.
        :param limit: Maximum number of matching documents to return.
        :param kwargs: Reserved for interface compatibility.
        :return: List of normalized records with ``text`` and ``metadata`` keys.
        """
        results = self.collection.query(query_texts=[query], n_results=limit)
        if not results["documents"] or not results["documents"][0]:
            return []
        return [{"text": doc, "metadata": meta or {}} for doc, meta in zip(results["documents"][0], results["metadatas"][0])]

    def get_description(
        self,
    ) -> str:
        """
        Provide a human-readable description of this backend for agent routing.

        :return: Description string in ``<backend_name>: <description>`` format.
        """
        return f"{self.backend_name}: {self.description}"
