from dataclasses import dataclass
from pathlib import Path
from pypdf import PdfReader

SKIP_DIRS = {
    "node_modules",
    "dist",
    "build",
    "out",
    "coverage",
    "__pycache__",
    ".next",
    ".turbo",
    "target",
    "vendor",
    "bin",
    "obj",
}

SKIP_FILES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "bun.lock",
    "bun.lockb",
    "poetry.lock",
    "cargo.lock",
    "go.sum",
    "composer.lock",
}

SKIP_SUFFIXES = {
    ".env",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".svg",
    ".zip",
    ".gz",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".mp4",
    ".bin",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".class",
    ".pyc",
    ".wasm",
}

INDEX_EXTS = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".go",
    ".java",
    ".rs",
    ".md",
    ".json",
    ".yml",
    ".yaml",
    ".toml",
    ".css",
    ".html",
    ".sql",
    ".kt",
    ".swift",
    ".rb",
    ".php",
    ".cs",
    ".c",
    ".h",
    ".cpp",
    ".hpp",
    ".proto",
    ".graphql",
    ".gql",
}

MAX_FILE_BYTES = 200 * 1024
MAX_FILES = 500
CHUNK_CHARS = 3500
OVERLAP_LINES = 12


@dataclass
class CodeChunk:
    path: str
    start_line: int
    end_line: int
    text: str
    repo_id: str = ""
    repo_name: str = ""
    source_type: str = "repo"


@dataclass
class DocChunk:
    doc_id: str
    doc_name: str
    path: str
    page: int
    start_line: int
    end_line: int
    text: str
    source_type: str = "document"


def _should_index_file(path: Path) -> bool:
    name = path.name
    if name in SKIP_FILES or name.startswith(".env"):
        return False
    suffix = path.suffix.lower()
    if suffix in SKIP_SUFFIXES:
        return False
    if name.upper().startswith("README"):
        return True
    return suffix in INDEX_EXTS


def iter_source_files(repo_dir: Path) -> list[Path]:
    files: list[Path] = []
    for path in repo_dir.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if not _should_index_file(path):
            continue
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        files.append(path)
        if len(files) >= MAX_FILES:
            break
    return files


def chunk_text(rel_path: str, text: str) -> list[CodeChunk]:
    lines = text.splitlines(keepends=True)
    if not lines:
        return []
    chunks: list[CodeChunk] = []
    i = 0
    n = len(lines)
    while i < n:
        start = i
        size = 0
        while i < n and (size == 0 or size + len(lines[i]) <= CHUNK_CHARS):
            size += len(lines[i])
            i += 1
        body = "".join(lines[start:i]).strip("\n")
        if body.strip():
            chunks.append(
                CodeChunk(
                    path=rel_path,
                    start_line=start + 1,
                    end_line=i,
                    text=body,
                )
            )
        if i >= n:
            break
        i = max(start + 1, i - OVERLAP_LINES)
    return chunks


def collect_chunks(repo_dir: Path, repo_id: str = "", repo_name: str = "") -> tuple[list[CodeChunk], int, bool]:
    files = iter_source_files(repo_dir)
    capped = len(files) >= MAX_FILES
    chunks: list[CodeChunk] = []
    for path in files:
        rel = path.relative_to(repo_dir).as_posix()
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "\x00" in text:
            continue
        for chunk in chunk_text(rel, text):
            chunk.repo_id = repo_id
            chunk.repo_name = repo_name or repo_id
            chunks.append(chunk)
    return chunks, len(files), capped


def extract_pdf_chunks(pdf_path: Path, doc_id: str, doc_name: str) -> tuple[list[DocChunk], int]:
    chunks: list[DocChunk] = []
    reader = PdfReader(str(pdf_path))
    num_pages = len(reader.pages)
    for page_idx, page in enumerate(reader.pages, start=1):
        page_text = page.extract_text() or ""
        page_text = page_text.strip()
        if not page_text:
            continue
        lines = page_text.splitlines(keepends=True)
        i = 0
        n = len(lines)
        while i < n:
            start = i
            size = 0
            while i < n and (size == 0 or size + len(lines[i]) <= CHUNK_CHARS):
                size += len(lines[i])
                i += 1
            body = "".join(lines[start:i]).strip()
            if body:
                chunks.append(
                    DocChunk(
                        doc_id=doc_id,
                        doc_name=doc_name,
                        path=pdf_path.name,
                        page=page_idx,
                        start_line=start + 1,
                        end_line=i,
                        text=f"[{doc_name} | Page {page_idx}]\n{body}",
                    )
                )
            if i >= n:
                break
            i = max(start + 1, i - OVERLAP_LINES)
    return chunks, num_pages


def extract_text_doc_chunks(doc_path: Path, doc_id: str, doc_name: str) -> list[DocChunk]:
    try:
        text = doc_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    lines = text.splitlines(keepends=True)
    chunks: list[DocChunk] = []
    i = 0
    n = len(lines)
    while i < n:
        start = i
        size = 0
        while i < n and (size == 0 or size + len(lines[i]) <= CHUNK_CHARS):
            size += len(lines[i])
            i += 1
        body = "".join(lines[start:i]).strip()
        if body:
            chunks.append(
                DocChunk(
                    doc_id=doc_id,
                    doc_name=doc_name,
                    path=doc_path.name,
                    page=1,
                    start_line=start + 1,
                    end_line=i,
                    text=f"[{doc_name} | Lines {start + 1}-{i}]\n{body}",
                )
            )
        if i >= n:
            break
        i = max(start + 1, i - OVERLAP_LINES)
    return chunks
