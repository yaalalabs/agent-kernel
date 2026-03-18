import asyncio
import os
import uuid
from typing import Any, Dict, List, Mapping

import chromadb
import yaml

from chromadb.utils import embedding_functions

from base import AbstractKnowledgeBase
#from openai_model import model



CHROMA_KB_PATH = "./chroma_knowledge_db"

class KnowledgeBaseManager(AbstractKnowledgeBase):
    def __init__(self, persist_path: str = CHROMA_KB_PATH):
        self.client = chromadb.PersistentClient(path=persist_path)
        self.collection = self.client.get_or_create_collection(
            name="knowledge_base",
            embedding_function=embedding_functions.DefaultEmbeddingFunction()
        )

    def add_documents(self, texts: List[str], metadatas: List[Dict]) -> None:
        # UUIDs avoid duplicate-ID failures across repeated loads.
        ids = [f"doc_{uuid.uuid4().hex}" for _ in texts]
        self.collection.add(
            documents=texts,
            metadatas=metadatas,
            ids=ids
        )

    def add_records(self, records: List[Mapping[str, Any]], **kwargs) -> None:
        texts = [str(r["text"]) for r in records]
        metadatas = [dict(r.get("metadata", {})) for r in records]
        self.add_documents(texts, metadatas)

    def add(self, texts: List[str], metadatas: List[Dict]) -> None:
        records = [
            {"text": text, "metadata": metadata}
            for text, metadata in zip(texts, metadatas)
        ]
        self.add_records(records)

    def search_records(self, query: str, limit: int = 3, **kwargs):
        results = self.collection.query(
            query_texts=[query],
            n_results=limit
        )

        normalized = []
        for i in range(len(results["documents"][0])):
            normalized.append(
                {
                    "text": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i] or {},
                }
            )
        return normalized

    def search(self, query: str, k: int = 3):
        return self.search_records(query, limit=k)





def _load_kb_file(file_path: str) -> List[str]:
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".txt":
        with open(file_path, "r") as f:
            return [line.strip() for line in f if line.strip()]
    elif ext in (".yaml", ".yml"):
        with open(file_path, "r") as f:
            data = yaml.safe_load(f)
            if isinstance(data, list):
                return [str(item) for item in data]
            elif isinstance(data, dict):
                return [f"{k}: {v}" for k, v in data.items()]
            else:
                return [str(data)]
    else:
        raise ValueError("Unsupported file type. Use .txt or .yaml/.yml")

kb_manager = KnowledgeBaseManager()


def load_knowledge_base_impl(file_path: str) -> str:
    """
    Load a knowledge base from a .txt or .yaml file into ChromaDB.
    Each line (txt) or entry (yaml) is treated as a knowledge document.
    """
    try:
        if not os.path.exists(file_path):
            return f"Failed to load knowledge base: file not found: {file_path}"
        docs = _load_kb_file(file_path)
        if not docs:
            return f"Failed to load knowledge base: no valid entries in {file_path}"
        metadatas = [{"source": os.path.basename(file_path)} for _ in docs]
        kb_manager.add(docs, metadatas)
        return f"Loaded {len(docs)} knowledge entries from {file_path} into ChromaDB."
    except Exception as e:
        return f"Failed to load knowledge base: {e}"
    



def query_knowledge_base_impl(query: str, k: int = 3) -> str:
    """
    Query the ChromaDB knowledge base for relevant information.
    """
    try:
        results = kb_manager.search(query, k=k)
        if not results:
            return "No relevant knowledge found."
        return "\n".join(
            [
                f"- {doc['text']} (Source: {doc.get('metadata', {}).get('source', 'N/A')})"
                for doc in results
            ]
        )
    except Exception as e:
        return f"Knowledge base query failed: {e}"




