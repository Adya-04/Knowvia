from dataclasses import asdict, dataclass
import re

from app.graph import build_knowledge_graph
from app.store import query_chunks
from app.workspace import list_docs


@dataclass
class TraceabilityItem:
    doc_id: str
    doc_name: str
    page: int
    requirement_title: str
    requirement_excerpt: str
    status: str  # "IMPLEMENTED" | "PARTIAL" | "UNMAPPED"
    confidence_score: float
    matched_code_locations: list[dict]  # [{"repo": "...", "file": "...", "line": 1, "label": "..."}]


def build_traceability_matrix() -> list[dict]:
    docs = list_docs()
    if not docs:
        return []

    graph_data = build_knowledge_graph()
    nodes = graph_data.get("nodes", [])

    endpoints = [n for n in nodes if n["node_type"] == "endpoint"]
    schemas = [n for n in nodes if n["node_type"] == "schema"]

    items: list[TraceabilityItem] = []

    for d in docs:
        doc_id = d["id"]
        doc_name = d["name"]

        # Fetch chunks from Chroma for this document
        doc_hits = query_chunks(
            question="specification requirement feature endpoint schema API flow",
            target_id=doc_id,
            source_type="document",
            k=8,
        )

        for hit in doc_hits:
            text = hit.get("text", "")
            page = hit.get("page", 1)

            # Extract header or first sentence as title
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            if not lines:
                continue

            title = lines[0]
            if title.startswith("#"):
                title = title.lstrip("#").strip()
            elif len(lines) > 1 and lines[0].startswith("["):
                title = lines[1] if len(lines) > 1 else lines[0]

            excerpt = " ".join(lines[1:4]) if len(lines) > 1 else lines[0]
            excerpt = excerpt[:220]

            # Search matching code in Knowledge Graph
            matched_locations: list[dict] = []
            score = 0.0

            # 1. Look for explicit endpoints or paths mentioned in doc text (e.g. /api/...)
            route_matches = re.findall(r"/api/[A-Za-z0-9_/{}]+", text)
            for rm in route_matches:
                for ep in endpoints:
                    if rm in ep["label"]:
                        matched_locations.append(
                            {
                                "repo": ep["repo_name"],
                                "file": ep["file_path"],
                                "line": ep["line_number"],
                                "label": f"Endpoint {ep['label']}",
                            }
                        )
                        score += 0.5

            # 2. Look for schema name matches
            for sc in schemas:
                sc_name = sc["label"].replace("📦 ", "").strip()
                if sc_name.lower() in text.lower():
                    matched_locations.append(
                        {
                            "repo": sc["repo_name"],
                            "file": sc["file_path"],
                            "line": sc["line_number"],
                            "label": f"Schema {sc_name}",
                        }
                    )
                    score += 0.4

            # 3. Fallback: Semantic search across code chunks using requirement excerpt
            if not matched_locations:
                code_hits = query_chunks(question=f"{title} {excerpt}", source_type="repo", k=2)
                for ch in code_hits:
                    if ch.get("distance", 1.0) < 0.8:
                        matched_locations.append(
                            {
                                "repo": ch.get("source_name", "repo"),
                                "file": ch.get("path", ""),
                                "line": ch.get("start_line", 1),
                                "label": f"Code implementation at {ch.get('path', '')}:{ch.get('start_line', 1)}",
                            }
                        )
                        score += 0.3

            # Determine implementation status
            if score >= 0.7 or len(matched_locations) >= 2:
                status = "IMPLEMENTED"
            elif len(matched_locations) >= 1:
                status = "PARTIAL"
            else:
                status = "UNMAPPED"

            items.append(
                TraceabilityItem(
                    doc_id=doc_id,
                    doc_name=doc_name,
                    page=page,
                    requirement_title=title[:80],
                    requirement_excerpt=excerpt,
                    status=status,
                    confidence_score=min(round(score, 2), 1.0),
                    matched_code_locations=matched_locations,
                )
            )

    return [asdict(i) for i in items]

