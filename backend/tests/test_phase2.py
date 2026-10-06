import pytest
from fastapi.testclient import TestClient

from app.auditor import audit_contracts, camel_to_snake, levenshtein_distance
from app.graph import build_knowledge_graph, generate_graph_mermaid, GraphEdge, GraphNode
from app.main import app
from app.parser import (
    extract_payload_fields,
    parse_python_file,
    parse_ts_js_file,
    ParsedEndpoint,
    ParsedFrontendCall,
    ParsedSchema,
)


def test_levenshtein_and_camel_to_snake():
    assert camel_to_snake("userId") == "user_id"
    assert camel_to_snake("userName") == "user_name"
    assert camel_to_snake("orderIdList") == "order_id_list"

    assert levenshtein_distance("username", "user_name") == 1
    assert levenshtein_distance("prodct", "product") == 1
    assert levenshtein_distance("exact", "exact") == 0


def test_python_ast_extractor():
    sample_code = """
from pydantic import BaseModel
from fastapi import FastAPI

app = FastAPI()

class UserCreate(BaseModel):
    user_id: str
    user_name: str
    email: str

@app.post("/api/v1/users", response_model=UserCreate)
def create_user(body: UserCreate):
    return body

@app.get("/api/v1/users/{id}")
def get_user(id: str):
    return {"id": id}
"""
    endpoints, schemas = parse_python_file(sample_code, "be_repo", "backend-svc", "routes/users.py")

    assert len(endpoints) == 2
    post_ep = next(ep for ep in endpoints if ep.method == "POST")
    assert post_ep.path == "/api/v1/users"
    assert post_ep.handler_name == "create_user"
    assert post_ep.request_schema == "UserCreate"

    assert len(schemas) >= 1
    user_schema = next(s for s in schemas if s.name == "UserCreate")
    field_names = [f["name"] for f in user_schema.fields]
    assert "user_id" in field_names
    assert "user_name" in field_names


def test_ts_js_extractor():
    sample_ts = """
export interface UserPayload {
    userId: string;
    userName?: string;
}

export async function submitUser() {
    return axios.post('/api/v1/users', { userId, userName });
}

export async function fetchUser(id: string) {
    return fetch(`/api/v1/users/${id}`, { method: 'GET' });
}
"""
    calls, schemas = parse_ts_js_file(sample_ts, "fe_repo", "frontend-web", "src/api.ts")

    assert len(schemas) == 1
    assert schemas[0].name == "UserPayload"

    assert len(calls) >= 1
    post_call = next(c for c in calls if c.method == "POST")
    assert post_call.path == "/api/v1/users"
    assert "userId" in post_call.payload_fields
    assert "userName" in post_call.payload_fields


def test_contract_auditor_detects_casing_and_typos():
    endpoints = [
        ParsedEndpoint(
            id="ep1",
            repo_id="be",
            repo_name="backend",
            method="POST",
            path="/api/v1/users",
            handler_name="create_user",
            file_path="routes/user.py",
            start_line=20,
            end_line=30,
            request_schema="UserCreate",
        )
    ]
    schemas = [
        ParsedSchema(
            id="sc1",
            repo_id="be",
            repo_name="backend",
            name="UserCreate",
            fields=[
                {"name": "user_id", "type": "str", "required": True},
                {"name": "user_name", "type": "str", "required": True},
                {"name": "email", "type": "str", "required": True},
            ],
            file_path="models/user.py",
            start_line=10,
            end_line=15,
        )
    ]
    # Frontend sends camelCase 'userId' and typo 'emial'
    calls = [
        ParsedFrontendCall(
            id="call1",
            repo_id="fe",
            repo_name="frontend",
            method="POST",
            path="/api/v1/users",
            payload_fields=["userId", "emial"],
            file_path="src/api.ts",
            start_line=45,
            end_line=50,
        )
    ]

    report = audit_contracts(endpoints, schemas, calls)
    assert report.total_endpoints == 1
    assert report.matched_contracts == 1
    assert report.issues_found >= 2

    issue_types = [iss["issue_type"] for iss in report.issues]
    assert "CASING_MISMATCH" in issue_types
    assert "POTENTIAL_TYPO" in issue_types


def test_graph_mermaid_generation():
    nodes = [
        GraphNode(id="r1", label="Repo 1", node_type="repo", repo_name="Repo 1"),
        GraphNode(id="ep1", label="POST /api/test", node_type="endpoint", repo_name="Repo 1"),
    ]
    edges = [GraphEdge(source="r1", target="ep1", relationship="CONTAINS")]
    chart = generate_graph_mermaid(nodes, edges)
    assert "flowchart LR" in chart
    assert "Repo 1" in chart


def test_fastapi_graph_and_audit_endpoints():
    client = TestClient(app)
    res_graph = client.get("/api/graph")
    assert res_graph.status_code == 200
    data = res_graph.json()
    assert "nodes" in data
    assert "edges" in data
    assert "audit" in data
    assert "mermaid" in data

    res_audit = client.get("/api/audit")
    assert res_audit.status_code == 200
    audit_data = res_audit.json()
    assert "total_endpoints" in audit_data
    assert "issues" in audit_data

