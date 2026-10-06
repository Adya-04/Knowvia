from dataclasses import dataclass
from pathlib import Path
import re
import shutil

from app.chunking import collect_chunks, extract_pdf_chunks, extract_text_doc_chunks
from app.config import DOCS_DIR, REPOS_DIR
from app.github import clone_repo, parse_github_url
from app.store import upsert_code_chunks, upsert_doc_chunks
from app import workspace


@dataclass
class RepoIngestResult:
    repo_id: str
    repo_name: str
    file_count: int
    chunk_count: int
    capped: bool
    status: str


@dataclass
class DocIngestResult:
    doc_id: str
    doc_name: str
    file_type: str
    page_count: int
    chunk_count: int
    status: str


def sanitize_id(raw: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "_", raw).strip("_")
    return cleaned[:60] or "source"


def ingest_repo(repo_url: str) -> RepoIngestResult:
    url = repo_url.strip()
    is_local = Path(url).is_dir()

    if is_local:
        local_dir = Path(url).resolve()
        repo_name = local_dir.name
        repo_id = sanitize_id(f"local_{repo_name}")
        dest = local_dir
    else:
        repo_id, dest = clone_repo(url)
        _, _, repo_name = parse_github_url(url)

    workspace.save_repo(
        {
            "id": repo_id,
            "name": repo_name,
            "url": url if not is_local else str(dest),
            "is_local": is_local,
            "local_path": str(dest),
            "status": "indexing",
            "file_count": 0,
            "chunk_count": 0,
            "capped": False,
        }
    )

    try:
        chunks, file_count, capped = collect_chunks(dest, repo_id=repo_id, repo_name=repo_name)
        chunk_count = upsert_code_chunks(repo_id, repo_name, chunks)
        record = {
            "id": repo_id,
            "name": repo_name,
            "url": url if not is_local else str(dest),
            "is_local": is_local,
            "local_path": str(dest),
            "status": "ready",
            "file_count": file_count,
            "chunk_count": chunk_count,
            "capped": capped,
        }
        workspace.save_repo(record)
        return RepoIngestResult(
            repo_id=repo_id,
            repo_name=repo_name,
            file_count=file_count,
            chunk_count=chunk_count,
            capped=capped,
            status="ready",
        )
    except Exception as exc:
        workspace.save_repo(
            {
                "id": repo_id,
                "name": repo_name,
                "url": url if not is_local else str(dest),
                "is_local": is_local,
                "local_path": str(dest),
                "status": "error",
                "error": str(exc),
            }
        )
        raise


def ingest_document(filename: str, content: bytes) -> DocIngestResult:
    ext = Path(filename).suffix.lower()
    if ext not in {".pdf", ".md", ".markdown", ".txt", ".json", ".yaml", ".yml"}:
        raise ValueError(f"Unsupported document format '{ext}'. Supported: .pdf, .md, .txt, .json, .yaml")

    clean_base = sanitize_id(Path(filename).stem)
    doc_id = f"doc_{clean_base}_{len(content) % 10000}"
    dest_path = DOCS_DIR / f"{doc_id}_{filename}"
    dest_path.write_bytes(content)

    doc_type = "pdf" if ext == ".pdf" else "markdown" if ext in {".md", ".markdown"} else "text"
    workspace.save_doc(
        {
            "id": doc_id,
            "name": filename,
            "filename": filename,
            "file_type": doc_type,
            "file_size": len(content),
            "local_path": str(dest_path),
            "status": "indexing",
            "page_count": 0,
            "chunk_count": 0,
        }
    )

    try:
        if doc_type == "pdf":
            chunks, page_count = extract_pdf_chunks(dest_path, doc_id=doc_id, doc_name=filename)
        else:
            chunks = extract_text_doc_chunks(dest_path, doc_id=doc_id, doc_name=filename)
            page_count = 1

        chunk_count = upsert_doc_chunks(doc_id, filename, chunks)
        record = {
            "id": doc_id,
            "name": filename,
            "filename": filename,
            "file_type": doc_type,
            "file_size": len(content),
            "local_path": str(dest_path),
            "status": "ready",
            "page_count": page_count,
            "chunk_count": chunk_count,
        }
        workspace.save_doc(record)
        return DocIngestResult(
            doc_id=doc_id,
            doc_name=filename,
            file_type=doc_type,
            page_count=page_count,
            chunk_count=chunk_count,
            status="ready",
        )
    except Exception as exc:
        workspace.save_doc(
            {
                "id": doc_id,
                "name": filename,
                "filename": filename,
                "file_type": doc_type,
                "file_size": len(content),
                "local_path": str(dest_path),
                "status": "error",
                "error": str(exc),
            }
        )
        raise


def get_repo(repo_id: str) -> dict | None:
    return workspace.get_repo(repo_id)


def list_repos() -> list[dict]:
    return workspace.list_repos()


def delete_repo(repo_id: str) -> bool:
    return workspace.delete_repo(repo_id)


def get_doc(doc_id: str) -> dict | None:
    return workspace.get_doc(doc_id)


def list_docs() -> list[dict]:
    return workspace.list_docs()


def delete_doc(doc_id: str) -> bool:
    return workspace.delete_doc(doc_id)
