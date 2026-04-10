import hashlib
from typing import Any, Iterable, List, Mapping, Optional

import chromadb
from chromadb.utils import embedding_functions

from .base import KnowledgeBase


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
        embedding_function: Optional[any] = None,
    ):  # pass in a description
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
        return self.name if self.name else "chromadb"

    def connect(self, **kwargs) -> None:
        self.client = chromadb.PersistentClient(path=self.persist_path)
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            embedding_function=self.embedding_function,
        )

    def write(self, records: Iterable[Mapping[str, Any]], **kwargs) -> None:
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
        results = self.collection.query(query_texts=[query], n_results=limit)
        if not results["documents"] or not results["documents"][0]:
            return []
        return [{"text": doc, "metadata": meta or {}} for doc, meta in zip(results["documents"][0], results["metadatas"][0])]

    def get_description(
        self,
    ) -> str:
        """Provide a human-readable description of this backend for the agent."""
        return f"{self.backend_name}: {self.description}"
