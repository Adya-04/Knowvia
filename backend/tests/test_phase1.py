import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from app.chunking import chunk_text, extract_text_doc_chunks, CodeChunk, DocChunk
from app.workspace import (
    load_workspace,
    save_repo,
    save_doc,
    list_repos,
    list_docs,
    delete_repo,
    delete_doc,
    get_workspace_summary,
)
from app.store import (
    upsert_code_chunks,
    upsert_doc_chunks,
    query_chunks,
    get_total_chunks,
    delete_source_chunks,
)
from app.main import app


def test_chunk_text_function():
    code = "def hello():\n    print('world')\n"
    chunks = chunk_text("test.py", code)
    assert len(chunks) == 1
    assert chunks[0].path == "test.py"
    assert chunks[0].start_line == 1
    assert "hello()" in chunks[0].text


def test_markdown_doc_chunking(tmp_path):
    md_file = tmp_path / "spec.md"
    md_file.write_text("# API Spec\n\nEndpoint: `/api/v1/users`\nMethod: POST\nPayload: `user_id`\n")
    chunks = extract_text_doc_chunks(md_file, "doc_spec_1", "spec.md")
    assert len(chunks) >= 1
    assert chunks[0].doc_id == "doc_spec_1"
    assert "API Spec" in chunks[0].text
    assert chunks[0].page == 1


def test_store_and_query():
    code_chunk = CodeChunk(
        path="routes/auth.py",
        start_line=1,
        end_line=10,
        text="def login(user_id: str):\n    return create_jwt(user_id)",
        repo_id="test_repo_auth",
        repo_name="auth-service",
    )
    upsert_code_chunks("test_repo_auth", "auth-service", [code_chunk])

    doc_chunk = DocChunk(
        doc_id="test_doc_auth_prd",
        doc_name="Auth_PRD.pdf",
        path="Auth_PRD.pdf",
        page=2,
        start_line=1,
        end_line=5,
        text="The authentication service requires JWT token creation with user_id parameter.",
    )
    upsert_doc_chunks("test_doc_auth_prd", "Auth_PRD.pdf", [doc_chunk])

    # Query without filter (across both repo and doc)
    hits = query_chunks("JWT token authentication", k=5)
    assert len(hits) >= 1

    # Check hit fields
    for h in hits:
        assert "source_id" in h
        assert "source_type" in h
        assert "path" in h

    # Cleanup
    delete_source_chunks("test_repo_auth")
    delete_source_chunks("test_doc_auth_prd")


def test_workspace_crud():
    repo_data = {
        "id": "sample_repo_1",
        "name": "sample-repo",
        "url": "https://github.com/example/sample-repo",
        "status": "ready",
        "file_count": 10,
        "chunk_count": 50,
        "capped": False,
    }
    save_repo(repo_data)
    repos = list_repos()
    assert any(r["id"] == "sample_repo_1" for r in repos)

    doc_data = {
        "id": "sample_doc_1",
        "name": "PRD.pdf",
        "filename": "PRD.pdf",
        "file_type": "pdf",
        "file_size": 1024,
        "page_count": 5,
        "chunk_count": 15,
        "status": "ready",
    }
    save_doc(doc_data)
    docs = list_docs()
    assert any(d["id"] == "sample_doc_1" for d in docs)

    # Cleanup
    assert delete_repo("sample_repo_1") is True
    assert delete_doc("sample_doc_1") is True


def test_fastapi_endpoints():
    client = TestClient(app)

    # Health check
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"ok": True}

    # Workspace summary
    res = client.get("/api/workspace")
    assert res.status_code == 200
    data = res.json()
    assert "repo_count" in data
    assert "doc_count" in data
    assert "total_chunks" in data

    # Docs upload
    test_content = b"# PRD Document\n\nFeature: Multi-repo knowledge graph."
    res = client.post(
        "/api/docs/upload",
        files={"file": ("feature_prd.md", test_content, "text/markdown")},
    )
    assert res.status_code == 200
    doc_res = res.json()
    assert doc_res["doc_name"] == "feature_prd.md"
    assert doc_res["status"] == "ready"

    # Get doc content
    doc_id = doc_res["doc_id"]
    res = client.get(f"/api/docs/{doc_id}/content")
    assert res.status_code == 200
    assert "Multi-repo knowledge graph" in res.json()["content"]

    # Delete doc
    res = client.delete(f"/api/docs/{doc_id}")
    assert res.status_code == 200

