from datetime import datetime, timezone
import json
import shutil
from pathlib import Path

from app.config import DOCS_DIR, REPOS_DIR, WORKSPACE_FILE
from app.store import count_source_chunks, delete_source_chunks, get_total_chunks


def _default_workspace() -> dict:
    return {
        "repos": {},
        "docs": {},
    }


def load_workspace() -> dict:
    if not WORKSPACE_FILE.exists():
        data = _default_workspace()
        save_workspace(data)
        return data
    try:
        content = WORKSPACE_FILE.read_text(encoding="utf-8")
        return json.loads(content)
    except Exception:
        return _default_workspace()


def save_workspace(data: dict) -> None:
    try:
        WORKSPACE_FILE.parent.mkdir(parents=True, exist_ok=True)
        WORKSPACE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as exc:
        print(f"Error saving workspace: {exc}")


def list_repos() -> list[dict]:
    ws = load_workspace()
    return list(ws.get("repos", {}).values())


def get_repo(repo_id: str) -> dict | None:
    ws = load_workspace()
    return ws.get("repos", {}).get(repo_id)


def save_repo(record: dict) -> None:
    ws = load_workspace()
    if "repos" not in ws:
        ws["repos"] = {}
    record["updated_at"] = datetime.now(timezone.utc).isoformat()
    if "created_at" not in record:
        record["created_at"] = record["updated_at"]
    ws["repos"][record["id"]] = record
    save_workspace(ws)


def delete_repo(repo_id: str) -> bool:
    ws = load_workspace()
    repo = ws.get("repos", {}).pop(repo_id, None)
    if repo is None:
        return False
    save_workspace(ws)

    # Delete chunks from Chroma
    delete_source_chunks(repo_id)

    # Remove cloned directory from disk
    local_path = repo.get("local_path")
    if local_path:
        path = Path(local_path)
        if path.exists() and path.is_dir() and str(path).startswith(str(REPOS_DIR)):
            shutil.rmtree(path, ignore_errors=True)
    return True


def list_docs() -> list[dict]:
    ws = load_workspace()
    return list(ws.get("docs", {}).values())


def get_doc(doc_id: str) -> dict | None:
    ws = load_workspace()
    return ws.get("docs", {}).get(doc_id)


def save_doc(record: dict) -> None:
    ws = load_workspace()
    if "docs" not in ws:
        ws["docs"] = {}
    record["updated_at"] = datetime.now(timezone.utc).isoformat()
    if "created_at" not in record:
        record["created_at"] = record["updated_at"]
    ws["docs"][record["id"]] = record
    save_workspace(ws)


def delete_doc(doc_id: str) -> bool:
    ws = load_workspace()
    doc = ws.get("docs", {}).pop(doc_id, None)
    if doc is None:
        return False
    save_workspace(ws)

    # Delete chunks from Chroma
    delete_source_chunks(doc_id)

    # Remove file from disk
    local_path = doc.get("local_path")
    if local_path:
        path = Path(local_path)
        if path.exists() and path.is_file() and str(path).startswith(str(DOCS_DIR)):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
    return True


def get_workspace_summary() -> dict:
    repos = list_repos()
    docs = list_docs()
    total_chunks = get_total_chunks()
    return {
        "repo_count": len(repos),
        "doc_count": len(docs),
        "total_chunks": total_chunks,
        "repos": repos,
        "docs": docs,
    }

