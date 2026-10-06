from dataclasses import asdict, dataclass
from pathlib import Path
import re

from app.auditor import audit_contracts, normalize_route_path, routes_match
from app.parser import (
    parse_repo_directory,
    ParsedEndpoint,
    ParsedFrontendCall,
    ParsedSchema,
)
from app.workspace import list_docs, list_repos


@dataclass
class GraphNode:
    id: str
    label: str
    node_type: str  # "repo" | "endpoint" | "schema" | "client_call" | "document"
    repo_name: str
    file_path: str = ""
    line_number: int = 1
    details: dict = None


@dataclass
class GraphEdge:
    source: str
    target: str
    relationship: str  # "CONTAINS" | "USES_SCHEMA" | "CALLS_ENDPOINT" | "CONTRACT_MISMATCH"
    label: str = ""
    severity: str = "normal"  # "normal" | "warning" | "error"


def build_knowledge_graph() -> dict:
    repos = list_repos()
    docs = list_docs()

    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []

    all_endpoints: list[ParsedEndpoint] = []
    all_schemas: list[ParsedSchema] = []
    all_calls: list[ParsedFrontendCall] = []

    # 1. Add Documentation Nodes
    for doc in docs:
        d_id = f"doc_{doc['id']}"
        nodes.append(
            GraphNode(
                id=d_id,
                label=f"📄 {doc['name']}",
                node_type="document",
                repo_name="Docs",
                file_path=doc.get("filename", ""),
                line_number=1,
                details={"file_type": doc.get("file_type"), "page_count": doc.get("page_count", 1)},
            )
        )

    # 2. Parse all Repos
    for r in repos:
        local_path = r.get("local_path")
        if not local_path or not Path(local_path).is_dir():
            continue

        repo_id = r["id"]
        repo_name = r["name"]
        repo_node_id = f"repo_{repo_id}"

        nodes.append(
            GraphNode(
                id=repo_node_id,
                label=f"📁 {repo_name}",
                node_type="repo",
                repo_name=repo_name,
                details={"file_count": r.get("file_count", 0), "chunk_count": r.get("chunk_count", 0)},
            )
        )

        eps, scs, calls = parse_repo_directory(Path(local_path), repo_id, repo_name)
        all_endpoints.extend(eps)
        all_schemas.extend(scs)
        all_calls.extend(calls)

        # Add Endpoint Nodes
        for ep in eps:
            ep_node_id = f"ep_{ep.id}"
            nodes.append(
                GraphNode(
                    id=ep_node_id,
                    label=f"🌐 {ep.method} {ep.path}",
                    node_type="endpoint",
                    repo_name=repo_name,
                    file_path=ep.file_path,
                    line_number=ep.start_line,
                    details={"handler": ep.handler_name, "request_schema": ep.request_schema},
                )
            )
            edges.append(
                GraphEdge(
                    source=repo_node_id,
                    target=ep_node_id,
                    relationship="CONTAINS",
                    label="exposes",
                )
            )

        # Add Schema Nodes
        for sc in scs:
            sc_node_id = f"sc_{sc.id}"
            nodes.append(
                GraphNode(
                    id=sc_node_id,
                    label=f"📦 {sc.name}",
                    node_type="schema",
                    repo_name=repo_name,
                    file_path=sc.file_path,
                    line_number=sc.start_line,
                    details={"fields": sc.fields},
                )
            )
            edges.append(
                GraphEdge(
                    source=repo_node_id,
                    target=sc_node_id,
                    relationship="CONTAINS",
                    label="defines",
                )
            )

        # Add Client Call Nodes
        for call in calls:
            call_node_id = f"call_{call.id}"
            nodes.append(
                GraphNode(
                    id=call_node_id,
                    label=f"⚡ {call.method} {call.path}",
                    node_type="client_call",
                    repo_name=repo_name,
                    file_path=call.file_path,
                    line_number=call.start_line,
                    details={"payload_fields": call.payload_fields},
                )
            )
            edges.append(
                GraphEdge(
                    source=repo_node_id,
                    target=call_node_id,
                    relationship="CONTAINS",
                    label="calls",
                )
            )

    # 3. Connect Endpoints to Schemas
    schema_map = {s.name: s for s in all_schemas}
    for ep in all_endpoints:
        if ep.request_schema and ep.request_schema in schema_map:
            sc = schema_map[ep.request_schema]
            edges.append(
                GraphEdge(
                    source=f"ep_{ep.id}",
                    target=f"sc_{sc.id}",
                    relationship="USES_SCHEMA",
                    label="validates_with",
                )
            )

    # 4. Connect Client Calls to Endpoints
    for call in all_calls:
        for ep in all_endpoints:
            if call.method == ep.method and routes_match(call.path, ep.path):
                edges.append(
                    GraphEdge(
                        source=f"call_{call.id}",
                        target=f"ep_{ep.id}",
                        relationship="CALLS_ENDPOINT",
                        label="requests",
                    )
                )
                break

    # 5. Run Contract Audit
    audit_report = audit_contracts(all_endpoints, all_schemas, all_calls)

    return {
        "nodes": [asdict(n) for n in nodes],
        "edges": [asdict(e) for e in edges],
        "audit": asdict(audit_report),
        "mermaid": generate_graph_mermaid(nodes, edges),
    }


def sanitize_mermaid_id(raw: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", raw)


def generate_graph_mermaid(nodes: list[GraphNode], edges: list[GraphEdge]) -> str:
    if not nodes:
        return "flowchart TD\n  empty[Knowledge Graph is empty]"

    lines = ["flowchart LR"]
    # Group by repository subgraphs
    repo_groups: dict[str, list[GraphNode]] = {}
    for n in nodes:
        repo_groups.setdefault(n.repo_name, []).append(n)

    for rname, rnodes in repo_groups.items():
        clean_rname = sanitize_mermaid_id(rname)
        lines.append(f'  subgraph sub_{clean_rname} ["📁 {rname}"]')
        for n in rnodes:
            clean_nid = sanitize_mermaid_id(n.id)
            clean_lbl = n.label.replace('"', "'")
            lines.append(f'    {clean_nid}["{clean_lbl}"]')
        lines.append("  end")

    # Add edges
    for e in edges:
        # Skip excessive "CONTAINS" edges to keep diagram readable
        if e.relationship == "CONTAINS":
            continue
        s_id = sanitize_mermaid_id(e.source)
        t_id = sanitize_mermaid_id(e.target)
        lbl = f"|{e.label}|" if e.label else ""
        lines.append(f"  {s_id} -->{lbl} {t_id}")

    return "\n".join(lines)

