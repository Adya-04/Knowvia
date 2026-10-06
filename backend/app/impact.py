from dataclasses import asdict, dataclass, field
from pathlib import Path
import re

from app.auditor import camel_to_snake, normalize_route_path, routes_match
from app.graph import build_knowledge_graph
from app.store import query_chunks


@dataclass
class AffectedItem:
    repo_name: str
    file_path: str
    line_number: int
    item_type: str  # "frontend_caller" | "endpoint_handler" | "data_schema" | "spec_document"
    description: str
    impact_nature: str  # "BREAKING_CHANGE" | "PAYLOAD_MISMATCH" | "SPEC_DRIFT" | "DEPENDENT"


@dataclass
class ImpactReport:
    query: str
    target_type: str  # "endpoint" | "schema" | "field" | "general"
    risk_level: str   # "CRITICAL" | "HIGH" | "MEDIUM" | "LOW"
    summary: str
    affected_repos: list[str]
    affected_items: list[dict]
    remediation_steps: list[str]
    mermaid: str


def analyze_impact(query: str) -> ImpactReport:
    raw_query = query.strip()
    if not raw_query:
        return ImpactReport(
            query="",
            target_type="general",
            risk_level="LOW",
            summary="No target symbol specified for impact analysis.",
            affected_repos=[],
            affected_items=[],
            remediation_steps=[],
            mermaid="flowchart TD\n  none[Specify a schema, field, or endpoint to analyze impact]",
        )

    graph_data = build_knowledge_graph()
    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])

    is_route = "/" in raw_query
    q_snake = camel_to_snake(raw_query).lower()

    target_type = "endpoint" if is_route else "field"
    affected_items: list[AffectedItem] = []
    affected_repos: set[str] = set()

    # 1. Endpoint Target Matching
    if is_route:
        norm_q = normalize_route_path(raw_query)
        # Find matching endpoint nodes
        for n in nodes:
            if n["node_type"] == "endpoint":
                ep_path = n["label"].split(" ", 1)[-1]
                if routes_match(ep_path, norm_q):
                    affected_repos.add(n["repo_name"])
                    affected_items.append(
                        AffectedItem(
                            repo_name=n["repo_name"],
                            file_path=n["file_path"],
                            line_number=n["line_number"],
                            item_type="endpoint_handler",
                            description=f"Route Handler '{n['label']}' in {n['repo_name']}",
                            impact_nature="BREAKING_CHANGE",
                        )
                    )

        # Find matching client call nodes
        for n in nodes:
            if n["node_type"] == "client_call":
                call_path = n["label"].split(" ", 1)[-1]
                if routes_match(call_path, norm_q):
                    affected_repos.add(n["repo_name"])
                    affected_items.append(
                        AffectedItem(
                            repo_name=n["repo_name"],
                            file_path=n["file_path"],
                            line_number=n["line_number"],
                            item_type="frontend_caller",
                            description=f"Client call '{n['label']}' will fail if route signature changes",
                            impact_nature="BREAKING_CHANGE",
                        )
                    )

    # 2. Schema / Field Target Matching
    else:
        # Check if query matches a Schema name or a field inside a schema
        for n in nodes:
            if n["node_type"] == "schema":
                details = n.get("details") or {}
                fields = details.get("fields", [])
                schema_name = n["label"].replace("📦 ", "").strip()

                is_schema_match = schema_name.lower() == raw_query.lower()
                matching_fields = [
                    f["name"]
                    for f in fields
                    if f["name"].lower() == q_snake or f["name"].lower() == raw_query.lower()
                ]

                if is_schema_match or matching_fields:
                    target_type = "schema" if is_schema_match else "field"
                    affected_repos.add(n["repo_name"])
                    matched_field_str = f" (contains field '{matching_fields[0]}')" if matching_fields else ""
                    affected_items.append(
                        AffectedItem(
                            repo_name=n["repo_name"],
                            file_path=n["file_path"],
                            line_number=n["line_number"],
                            item_type="data_schema",
                            description=f"Data Model '{schema_name}'{matched_field_str}",
                            impact_nature="BREAKING_CHANGE",
                        )
                    )

                    # Look for endpoints that use this schema
                    for ep_node in nodes:
                        if ep_node["node_type"] == "endpoint":
                            req_schema = (ep_node.get("details") or {}).get("request_schema")
                            if req_schema == schema_name:
                                affected_repos.add(ep_node["repo_name"])
                                affected_items.append(
                                    AffectedItem(
                                        repo_name=ep_node["repo_name"],
                                        file_path=ep_node["file_path"],
                                        line_number=ep_node["line_number"],
                                        item_type="endpoint_handler",
                                        description=f"Endpoint '{ep_node['label']}' depends on model '{schema_name}'",
                                        impact_nature="DEPENDENT",
                                    )
                                )

        # Look for client calls whose payload includes this field
        for n in nodes:
            if n["node_type"] == "client_call":
                payload_fields = (n.get("details") or {}).get("payload_fields", [])
                payload_fields_norm = [camel_to_snake(f).lower() for f in payload_fields]
                if q_snake in payload_fields_norm or raw_query.lower() in [f.lower() for f in payload_fields]:
                    affected_repos.add(n["repo_name"])
                    affected_items.append(
                        AffectedItem(
                            repo_name=n["repo_name"],
                            file_path=n["file_path"],
                            line_number=n["line_number"],
                            item_type="frontend_caller",
                            description=f"Client call '{n['label']}' sends payload property '{raw_query}'",
                            impact_nature="PAYLOAD_MISMATCH",
                        )
                    )

    # 3. Check Documentation references in ChromaDB
    doc_hits = query_chunks(question=f"specification requirement {raw_query}", source_type="document", k=3)
    for hit in doc_hits:
        if hit.get("source_name") and raw_query.lower() in hit.get("text", "").lower():
            affected_items.append(
                AffectedItem(
                    repo_name="Docs",
                    file_path=hit.get("source_name", "Spec.pdf"),
                    line_number=hit.get("page", 1),
                    item_type="spec_document",
                    description=f"Requirement in {hit['source_name']} (Page {hit.get('page', 1)}) mentions '{raw_query}'",
                    impact_nature="SPEC_DRIFT",
                )
            )

    # 4. Compute Risk Level
    num_repos = len(affected_repos)
    num_items = len(affected_items)

    if num_repos >= 2 or any(i.impact_nature == "BREAKING_CHANGE" for i in affected_items):
        risk_level = "CRITICAL"
    elif num_items >= 2:
        risk_level = "HIGH"
    elif num_items == 1:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"

    # 5. Remediation Steps & Summary
    remediation_steps: list[str] = []
    if is_route:
        summary = (
            f"Modifying route '{raw_query}' affects {len(affected_items)} locations across "
            f"{len(affected_repos)} repositories."
        )
        remediation_steps.append(f"1. Update the backend route handler in {list(affected_repos)[:1] or ['backend']}.")
        remediation_steps.append(
            "2. Update all client fetch/axios endpoints in frontend repos to match the new URL pattern."
        )
        remediation_steps.append("3. Verify PRD / OpenAPI documentation matches the updated route.")
    else:
        summary = (
            f"Altering symbol/field '{raw_query}' cascades across {len(affected_items)} locations in "
            f"{len(affected_repos)} repositories."
        )
        remediation_steps.append(f"1. Refactor model/DTO definitions in {list(affected_repos)[:1] or ['backend']}.")
        remediation_steps.append("2. Rename payload properties across all frontend consumer forms and API clients.")
        remediation_steps.append("3. Review business analyst specs and ensure contract verification passes.")

    # 6. Mermaid Blast Radius Diagram
    mermaid_lines = ["flowchart TD"]
    target_clean = re.sub(r"[^A-Za-z0-9_]", "_", raw_query)
    mermaid_lines.append(f'  TARGET["⚠️ MODIFIED: {raw_query}"]:::targetStyle')

    for idx, item in enumerate(affected_items[:8]):
        node_id = f"item_{idx}"
        desc_clean = item.description.replace('"', "'")
        impact_tag = f"[{item.impact_nature}]"
        mermaid_lines.append(f'  {node_id}["{item.repo_name}: {item.file_path}<br/>{impact_tag} {desc_clean}"]')
        mermaid_lines.append(f"  TARGET --> {node_id}")

    mermaid_lines.append("  classDef targetStyle fill:#ef4444,stroke:#991b1b,color:#fff,font-weight:bold;")

    return ImpactReport(
        query=raw_query,
        target_type=target_type,
        risk_level=risk_level,
        summary=summary,
        affected_repos=list(affected_repos),
        affected_items=[asdict(i) for i in affected_items],
        remediation_steps=remediation_steps,
        mermaid="\n".join(mermaid_lines),
    )

