"""
LlamaIndex RAG System for Agent Kernel Documentation and Examples
"""
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from llama_index.core import (
    VectorStoreIndex,
    StorageContext,
    load_index_from_storage,
    Settings,
)
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.query_engine import RetrieverQueryEngine
from llama_index.core.response_synthesizers import ResponseMode
from llama_index.core.retrievers import VectorIndexRetriever
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.llms.openai import OpenAI

from rag_loader import AgentKernelDataLoader


class AgentKernelRAG:
    """LlamaIndex-based RAG system for Agent Kernel documentation and examples."""

    def __init__(
            self,
            repo_path: str = "/tmp/agent-kernel-rag",
            persist_dir: str = "./rag_storage",
            rebuild_index: bool = False,
            chunk_size: int = 1024,
            chunk_overlap: int = 200,
            top_k: int = 5,
    ):
        """
        Initialize the RAG system.
        
        :param repo_path: Path to cloned agent-kernel repository
        :param persist_dir: Directory to persist the vector index
        :param rebuild_index: Force rebuild of index even if it exists
        :param chunk_size: Size of text chunks for embedding
        :param chunk_overlap: Overlap between chunks
        :param top_k: Number of top results to retrieve
        """
        self.repo_path = repo_path
        self.persist_dir = Path(persist_dir)
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.top_k = top_k

        # Configure LlamaIndex settings
        Settings.llm = OpenAI(model="gpt-4o-mini", temperature=0.1)
        Settings.embed_model = OpenAIEmbedding(model="text-embedding-3-small")
        Settings.node_parser = SentenceSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

        # Initialize index
        self.index = None
        self.query_engine = None

        # Load or build index
        if not rebuild_index and self._index_exists():
            print("Loading existing index from storage...")
            self._load_index()
        else:
            print("Building new index...")
            self._build_index()

        # Create a query engine
        self._create_query_engine()

    def _index_exists(self) -> bool:
        """Check if a persisted index exists."""
        return (self.persist_dir / "docstore.json").exists()

    def _load_index(self) -> None:
        """Load index from persistent storage."""
        try:
            storage_context = StorageContext.from_defaults(persist_dir=str(self.persist_dir))
            self.index = load_index_from_storage(storage_context)
            print("Index loaded successfully from storage")
        except Exception as e:
            print(f"Error loading index: {e}")
            print("Building new index instead...")
            self._build_index()

    def _build_index(self) -> None:
        """Build the index from scratch by loading all documents."""
        # Load documents
        loader = AgentKernelDataLoader(self.repo_path)
        documents = loader.load_all_documents()

        if not documents:
            raise ValueError("No documents loaded. Cannot build index.")

        print(f"Building index from {len(documents)} documents...")

        # Create index
        self.index = VectorStoreIndex.from_documents(
            documents,
            show_progress=True,
        )

        # Persist index
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.index.storage_context.persist(persist_dir=str(self.persist_dir))
        print(f"Index built and persisted to {self.persist_dir}")

    def _create_query_engine(self) -> None:
        """Create a query engine with a custom retriever."""
        if self.index is None:
            raise ValueError("Index not initialized")

        # Create retriever
        retriever = VectorIndexRetriever(
            index=self.index,
            similarity_top_k=self.top_k,
        )

        # Create the query engine
        self.query_engine = RetrieverQueryEngine.from_args(
            retriever=retriever,
            response_mode=ResponseMode.COMPACT,
        )
        print("Query engine created")

    def query(self, query_text: str) -> Dict[str, object]:
        """
        Query the RAG system.
        
        :param query_text: The query string
        :return: Dictionary with response and source information
        """
        if self.query_engine is None:
            raise ValueError("Query engine not initialized")

        print(f"Querying RAG: {query_text}")
        start_time = datetime.now()

        try:
            response = self.query_engine.query(query_text)

            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()

            # Extract source information
            sources = []
            if hasattr(response, 'source_nodes'):
                for node in response.source_nodes:
                    source_info = {
                        "score": node.score if hasattr(node, 'score') else None,
                        "text": node.text[:500] + "..." if len(node.text) > 500 else node.text,
                    }
                    if node.metadata:
                        source_info.update({
                            "file_path": node.metadata.get("file_path", "unknown"),
                            "source_type": node.metadata.get("source_type", "unknown"),
                            "file_name": node.metadata.get("file_name", "unknown"),
                        })
                        # Add an example project name if available
                        if "example_project" in node.metadata:
                            source_info["example_project"] = node.metadata["example_project"]
                    sources.append(source_info)

            result = {
                "query": query_text,
                "response": str(response),
                "sources": sources,
                "duration_seconds": duration,
                "timestamp": end_time.isoformat(),
            }

            print(f"Query completed in {duration:.2f}s")
            return result

        except Exception as e:
            print(f"Error during query: {e}")
            return {
                "query": query_text,
                "error": str(e),
                "timestamp": datetime.now().isoformat(),
            }

    def rebuild_index(self) -> None:
        """Force rebuild of the index."""
        print("Forcing index rebuild...")
        self._build_index()
        self._create_query_engine()
        print("Index rebuild complete")


# Singleton instance
_rag_instance: Optional[AgentKernelRAG] = None


def get_rag_instance(rebuild: bool = False) -> AgentKernelRAG:
    """
    Get or create the singleton RAG instance.
    
    :param rebuild: Force rebuild of the index
    :return: AgentKernelRAG instance
    """
    global _rag_instance

    if _rag_instance is None or rebuild:
        _rag_instance = AgentKernelRAG(rebuild_index=rebuild)

    return _rag_instance
