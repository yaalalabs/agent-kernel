import os
import re
from collections import Counter
from urllib.parse import urlparse

TOKEN = re.compile(r"[a-z0-9]{2,}")


def chunk_pages(pages, target=1200, overlap=180):
    """Split each page independently so every returned excerpt remains an exact citation."""
    chunks = []
    for page_number, page in enumerate(pages, 1):
        text = page.strip()
        start = 0
        ordinal = 0
        while start < len(text):
            end = min(start + target, len(text))
            if end < len(text):
                boundary = max(text.rfind("\n", start + target // 2, end), text.rfind(". ", start + target // 2, end))
                if boundary > start:
                    end = boundary + (1 if text[boundary] == "\n" else 2)
            excerpt = text[start:end].strip()
            if excerpt:
                chunks.append({"page": page_number, "ordinal": ordinal, "text": excerpt})
                ordinal += 1
            if end >= len(text):
                break
            start = max(start + 1, end - overlap)
    return chunks


def _ollama_url():
    configured = os.getenv("SCOPEWISE_OLLAMA_URL")
    if not configured:
        configured = os.getenv("SCOPEWISE_MODEL_URL", "http://127.0.0.1:11434/v1")
        configured = configured.removesuffix("/v1")
    parsed = urlparse(configured)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
        "127.0.0.1",
        "localhost",
        "::1",
        "host.docker.internal",
        "ollama",
    }:
        raise ValueError("The embedding service must be the local Ollama instance.")
    return configured.rstrip("/") + "/api/embed"


async def embed_texts(texts):
    import httpx

    model = os.getenv("SCOPEWISE_EMBED_MODEL", "nomic-embed-text:latest")
    vectors = []
    async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
        for start in range(0, len(texts), 48):
            response = await client.post(_ollama_url(), json={"model": model, "input": texts[start : start + 48]})
            response.raise_for_status()
            vectors.extend(response.json()["embeddings"])
    if len(vectors) != len(texts) or any(not vector for vector in vectors):
        raise ValueError("Ollama returned an incomplete embedding index.")
    return model, vectors


async def index_document(store, owner, course_id, document, semantic=True):
    chunks = chunk_pages(document["pages"])
    store.replace_chunks(owner, course_id, document["id"], chunks)
    status = "lexical"
    model = None
    if semantic and chunks:
        try:
            model, vectors = await embed_texts([chunk["text"] for chunk in chunks])
            store.update_chunk_embeddings(owner, document["id"], vectors, model)
            status = "semantic"
        except Exception:
            # Uploads remain useful and searchable if Ollama or the embedding model is unavailable.
            status = "lexical"
    document.update(index_status=status, chunk_count=len(chunks), embedding_model=model)
    return store.put(owner, "document", course_id, document, document["id"])


def _tokens(text):
    return TOKEN.findall(text.lower())


async def search_chunks(store, owner, course_id, query, *, document_ids=None, limit=6, semantic=True):
    query = query.strip()
    if len(query) < 2:
        raise ValueError("Enter at least two characters to search your sources.")
    rows = store.list_chunks(owner, course_id, document_ids=document_ids)
    if not rows:
        return {"mode": "lexical", "results": []}
    query_counts = Counter(_tokens(query))
    lexical = []
    for row in rows:
        counts = Counter(_tokens(row["text"]))
        lexical.append(sum(min(counts[token], count) for token, count in query_counts.items()) / max(1, sum(query_counts.values())))

    semantic_scores = None
    if semantic and any(row.get("embedding") for row in rows):
        try:
            model, vectors = await embed_texts([query])
            query_vector = vectors[0]
            semantic_scores = [
                sum(a * b for a, b in zip(query_vector, row["embedding"])) if row.get("embedding") and row.get("embed_model") == model else 0
                for row in rows
            ]
        except Exception:
            semantic_scores = None

    scored = []
    for index, row in enumerate(rows):
        if semantic_scores is None:
            score = lexical[index]
        else:
            score = 0.72 * max(0.0, semantic_scores[index]) + 0.28 * lexical[index]
        if score > 0:
            scored.append((score, row))
    scored.sort(key=lambda item: (-item[0], item[1]["page"], item[1]["ordinal"]))
    results = [
        {
            "document_id": row["document_id"],
            "page": row["page"],
            "text": row["text"],
            "score": round(score, 4),
        }
        for score, row in scored[:limit]
    ]
    return {"mode": "semantic" if semantic_scores is not None else "lexical", "results": results}
