from typing import Any
import chromadb
from chromadb.api import ClientAPI
from chromadb.api.models.Collection import Collection

from app.config import CHROMA_DIR

_client: ClientAPI | None = None
MAIN_COLLECTION_NAME = "knowvia_knowledge_base"


def get_client() -> ClientAPI:
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    return _client


def get_main_collection() -> Collection:
    client = get_client()
    return client.get_or_create_collection(
        name=MAIN_COLLECTION_NAME,
        metadata={"description": "Knowvia Multi-Repo and Document Knowledge Graph"},
    )


def delete_source_chunks(source_id: str) -> None:
    collection = get_main_collection()
    try:
        collection.delete(where={"source_id": source_id})
    except Exception:
        pass


def upsert_code_chunks(repo_id: str, repo_name: str, chunks: list[Any]) -> int:
    collection = get_main_collection()
    delete_source_chunks(repo_id)
    if not chunks:
        return 0

    batch = 100
    count = 0
    for start in range(0, len(chunks), batch):
        part = chunks[start : start + batch]
        ids = [f"{repo_id}_{start + i}" for i in range(len(part))]
        documents = [c.text for c in part]
        metadatas = [
            {
                "source_id": repo_id,
                "source_type": "repo",
                "source_name": repo_name,
                "path": c.path,
                "page": 1,
                "start_line": int(c.start_line),
                "end_line": int(c.end_line),
            }
            for c in part
        ]
        collection.add(ids=ids, documents=documents, metadatas=metadatas)
        count += len(part)
    return count


def upsert_doc_chunks(doc_id: str, doc_name: str, chunks: list[Any]) -> int:
    collection = get_main_collection()
    delete_source_chunks(doc_id)
    if not chunks:
        return 0

    batch = 100
    count = 0
    for start in range(0, len(chunks), batch):
        part = chunks[start : start + batch]
        ids = [f"{doc_id}_{start + i}" for i in range(len(part))]
        documents = [c.text for c in part]
        metadatas = [
            {
                "source_id": doc_id,
                "source_type": "document",
                "source_name": doc_name,
                "path": c.path,
                "page": int(getattr(c, "page", 1)),
                "start_line": int(c.start_line),
                "end_line": int(c.end_line),
            }
            for c in part
        ]
        collection.add(ids=ids, documents=documents, metadatas=metadatas)
        count += len(part)
    return count


def count_source_chunks(source_id: str) -> int:
    collection = get_main_collection()
    try:
        results = collection.get(where={"source_id": source_id})
        return len(results.get("ids", []))
    except Exception:
        return 0


def get_total_chunks() -> int:
    collection = get_main_collection()
    try:
        return collection.count()
    except Exception:
        return 0


def query_chunks(
    question: str,
    target_id: str | None = None,
    source_type: str | None = None,
    k: int = 10,
) -> list[dict]:
    collection = get_main_collection()
    total = collection.count()
    if total == 0:
        return []

    where_filter: dict[str, Any] | None = None
    if target_id and source_type:
        where_filter = {"$and": [{"source_id": target_id}, {"source_type": source_type}]}
    elif target_id:
        where_filter = {"source_id": target_id}
    elif source_type:
        where_filter = {"source_type": source_type}

    query_params: dict[str, Any] = {
        "query_texts": [question],
        "n_results": min(k, total),
        "include": ["documents", "metadatas", "distances"],
    }
    if where_filter:
        query_params["where"] = where_filter

    try:
        result = collection.query(**query_params)
    except Exception:
        # Fallback without where filter if filter matches 0 or errors
        query_params.pop("where", None)
        result = collection.query(**query_params)

    documents = (result.get("documents") or [[]])[0]
    metadatas = (result.get("metadatas") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]

    hits = []
    for doc, meta, dist in zip(documents, metadatas, distances):
        hits.append(
            {
                "text": doc,
                "source_id": meta.get("source_id", ""),
                "source_type": meta.get("source_type", "repo"),
                "source_name": meta.get("source_name", ""),
                "path": meta.get("path", ""),
                "page": int(meta.get("page", 1)),
                "start_line": int(meta.get("start_line", 1)),
                "end_line": int(meta.get("end_line", 1)),
                "distance": dist,
            }
        )
    return hits
