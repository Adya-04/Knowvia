import json
from pathlib import Path
from pypdf import PdfReader

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.chat import citations_from_hits, retrieve, stream_answer
from app.config import DOCS_DIR, REPOS_DIR
from app.github import GitHubUrlError
from app.ingest import (
    delete_doc,
    delete_repo,
    get_doc,
    get_repo,
    ingest_document,
    ingest_repo,
    list_docs,
    list_repos,
)
from app.graph import build_knowledge_graph
from app.store import get_total_chunks
from app.workspace import get_workspace_summary

app = FastAPI(title="Knowvia Knowledge Graph API", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class IngestRequest(BaseModel):
    repo_url: str = Field(..., min_length=2)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    scope: str = "all"  # "all", "repo", "document"
    target_id: str | None = None
    repo_id: str | None = None  # backwards compatibility


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/workspace")
def workspace_summary():
    return get_workspace_summary()


from app.impact import analyze_impact
from app.traceability import build_traceability_matrix

@app.get("/api/graph")
def get_graph():
    return build_knowledge_graph()


@app.get("/api/audit")
def get_audit():
    graph_data = build_knowledge_graph()
    return graph_data.get("audit", {})


@app.get("/api/impact")
def get_impact(query: str = Query(...)):
    return analyze_impact(query)


@app.get("/api/traceability")
def get_traceability():
    return {"matrix": build_traceability_matrix()}


# ---------------- Repositories Endpoints ----------------


@app.get("/api/repos")
def get_all_repos():
    return {"repos": list_repos()}


@app.post("/api/repos/ingest")
@app.post("/api/ingest")
def ingest(body: IngestRequest):
    try:
        result = ingest_repo(body.repo_url)
    except GitHubUrlError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        "repo_id": result.repo_id,
        "repo_name": result.repo_name,
        "file_count": result.file_count,
        "chunk_count": result.chunk_count,
        "capped": result.capped,
        "status": result.status,
    }


@app.get("/api/repos/{repo_id}")
def repo_status(repo_id: str):
    record = get_repo(repo_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Repo is not indexed.")
    return record


@app.delete("/api/repos/{repo_id}")
def remove_repo(repo_id: str):
    success = delete_repo(repo_id)
    if not success:
        raise HTTPException(status_code=404, detail="Repo not found.")
    return {"ok": True, "repo_id": repo_id}


# ---------------- Documents Endpoints ----------------


@app.get("/api/docs")
def get_all_docs():
    return {"docs": list_docs()}


@app.post("/api/docs/upload")
async def upload_doc(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing file name.")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    try:
        result = ingest_document(filename=file.filename, content=content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to process document: {exc}") from exc
    return {
        "doc_id": result.doc_id,
        "doc_name": result.doc_name,
        "file_type": result.file_type,
        "page_count": result.page_count,
        "chunk_count": result.chunk_count,
        "status": result.status,
    }


@app.get("/api/docs/{doc_id}")
def doc_status(doc_id: str):
    record = get_doc(doc_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return record


@app.get("/api/docs/{doc_id}/content")
def read_doc_content(doc_id: str):
    record = get_doc(doc_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    path_str = record.get("local_path")
    if not path_str:
        raise HTTPException(status_code=404, detail="File path not found.")
    target = Path(path_str)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Document file missing on disk.")

    doc_type = record.get("file_type", "")
    try:
        if doc_type == "pdf":
            reader = PdfReader(str(target))
            pages_text = []
            for i, p in enumerate(reader.pages, start=1):
                txt = p.extract_text() or ""
                pages_text.append(f"--- [Page {i}] ---\n{txt}")
            content = "\n\n".join(pages_text)
        else:
            content = target.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not read document: {exc}") from exc

    return {
        "doc_id": doc_id,
        "name": record.get("name", target.name),
        "file_type": doc_type,
        "content": content,
        "page_count": record.get("page_count", 1),
    }


@app.delete("/api/docs/{doc_id}")
def remove_doc(doc_id: str):
    success = delete_doc(doc_id)
    if not success:
        raise HTTPException(status_code=404, detail="Document not found.")
    return {"ok": True, "doc_id": doc_id}


# ---------------- Files & Code Viewer Endpoints ----------------


@app.get("/api/files")
def read_file(repo_id: str = Query(...), path: str = Query(...)):
    record = get_repo(repo_id)
    if record and record.get("local_path"):
        root = Path(record["local_path"]).resolve()
    else:
        root = (REPOS_DIR / repo_id).resolve()

    if not root.is_dir():
        raise HTTPException(status_code=404, detail="Repo directory not found.")
    target = (root / path).resolve()
    if not str(target).startswith(str(root)) or not target.is_file():
        raise HTTPException(status_code=400, detail="Invalid file path.")
    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        "repo_id": repo_id,
        "path": path,
        "content": content,
        "line_count": content.count("\n") + (0 if content.endswith("\n") or not content else 1),
    }


# ---------------- Chat Endpoint ----------------


@app.post("/api/chat")
def chat(body: ChatRequest):
    total_chunks = get_total_chunks()
    if total_chunks == 0:
        raise HTTPException(
            status_code=400,
            detail="Knowledge base is empty. Please index at least one repository or document first.",
        )

    target_id = body.target_id or body.repo_id
    source_type = None
    if body.scope == "repo":
        source_type = "repo"
    elif body.scope in {"doc", "document"}:
        source_type = "document"

    messages = [m.model_dump() for m in body.messages]
    context, hits = retrieve(messages, target_id=target_id, source_type=source_type, k=10)
    citations = citations_from_hits(hits)

    def event_stream():
        try:
            for token in stream_answer(messages, context):
                yield f"data: {json.dumps({'type': 'token', 'text': token})}\n\n"
            yield f"data: {json.dumps({'type': 'citations', 'citations': citations})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'detail': str(exc)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
