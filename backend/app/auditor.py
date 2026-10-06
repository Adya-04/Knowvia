from dataclasses import asdict, dataclass
import re

from app.parser import ParsedEndpoint, ParsedFrontendCall, ParsedSchema


def levenshtein_distance(s1: str, s2: str) -> int:
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)

    previous_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]


def camel_to_snake(s: str) -> str:
    pattern = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", s)
    pattern = re.sub(r"([a-z\d])([A-Z])", r"\1_\2", pattern)
    return pattern.replace("-", "_").lower()


def normalize_route_path(path: str) -> str:
    # Remove query string
    p = path.split("?")[0].strip()
    # Remove leading domain (e.g. http://localhost:8000/api -> /api)
    p = re.sub(r"^https?://[^/]+", "", p)
    # Replace path parameters :id or {id} with {*}
    p = re.sub(r"/\{[^}]+\}", "/*", p)
    p = re.sub(r"/:[A-Za-z0-9_]+", "/*", p)
    # Strip trailing slash
    p = p.rstrip("/")
    return p or "/"


def routes_match(client_path: str, server_path: str) -> bool:
    norm_client = normalize_route_path(client_path)
    norm_server = normalize_route_path(server_path)
    if norm_client == norm_server:
        return True
    # Check if client path ends with server path or vice versa (e.g. /api/users matching /users)
    if norm_client.endswith(norm_server) or norm_server.endswith(norm_client):
        return True
    return False


@dataclass
class ContractIssue:
    issue_type: str  # "CASING_MISMATCH" | "POTENTIAL_TYPO" | "MISSING_FIELD" | "UNMAPPED_ROUTE"
    severity: str    # "error" | "warning" | "info"
    description: str
    frontend_repo: str
    frontend_file: str
    frontend_line: int
    frontend_field: str | None
    backend_repo: str | None
    backend_file: str | None
    backend_line: int | None
    backend_field: str | None
    endpoint_path: str


@dataclass
class AuditReport:
    total_endpoints: int
    total_schemas: int
    total_frontend_calls: int
    matched_contracts: int
    issues_found: int
    issues: list[dict]


def audit_contracts(
    endpoints: list[ParsedEndpoint],
    schemas: list[ParsedSchema],
    frontend_calls: list[ParsedFrontendCall],
) -> AuditReport:
    issues: list[ContractIssue] = []
    matched_contracts = 0

    # Build schema lookup by name
    schema_by_name: dict[str, ParsedSchema] = {s.name: s for s in schemas}

    # Map endpoints
    for call in frontend_calls:
        # Find matching endpoint
        matching_ep = None
        for ep in endpoints:
            if call.method == ep.method and routes_match(call.path, ep.path):
                matching_ep = ep
                break

        if not matching_ep:
            # Check if route exists under a different method or typo
            issues.append(
                ContractIssue(
                    issue_type="UNMAPPED_ROUTE",
                    severity="warning",
                    description=f"Frontend calls '{call.method} {call.path}', but no matching endpoint was found in backend repos.",
                    frontend_repo=call.repo_name,
                    frontend_file=call.file_path,
                    frontend_line=call.start_line,
                    frontend_field=None,
                    backend_repo=None,
                    backend_file=None,
                    backend_line=None,
                    backend_field=None,
                    endpoint_path=call.path,
                )
            )
            continue

        matched_contracts += 1

        # Check request schema if available
        req_schema_name = matching_ep.request_schema
        if not req_schema_name or req_schema_name not in schema_by_name:
            continue

        target_schema = schema_by_name[req_schema_name]
        backend_fields = {f["name"]: f for f in target_schema.fields}
        backend_field_names = set(backend_fields.keys())

        # Check each field sent by frontend
        for fe_field in call.payload_fields:
            if fe_field in backend_field_names:
                continue

            # 1. Check casing drift (e.g. camelCase userId vs snake_case user_id)
            fe_snake = camel_to_snake(fe_field)
            if fe_snake in backend_field_names:
                issues.append(
                    ContractIssue(
                        issue_type="CASING_MISMATCH",
                        severity="error",
                        description=(
                            f"Casing mismatch: Frontend sends '{fe_field}' (camelCase), "
                            f"but Backend model '{target_schema.name}' expects '{fe_snake}' (snake_case)."
                        ),
                        frontend_repo=call.repo_name,
                        frontend_file=call.file_path,
                        frontend_line=call.start_line,
                        frontend_field=fe_field,
                        backend_repo=matching_ep.repo_name,
                        backend_file=target_schema.file_path,
                        backend_line=target_schema.start_line,
                        backend_field=fe_snake,
                        endpoint_path=matching_ep.path,
                    )
                )
                continue

            # 2. Check for potential typo / near-miss
            closest_match = None
            min_dist = 99
            for be_name in backend_field_names:
                dist = levenshtein_distance(fe_field.lower(), be_name.lower())
                if dist < min_dist and dist <= 2:
                    min_dist = dist
                    closest_match = be_name

            if closest_match:
                issues.append(
                    ContractIssue(
                        issue_type="POTENTIAL_TYPO",
                        severity="error",
                        description=(
                            f"Potential schema typo: Frontend sends '{fe_field}', "
                            f"which closely matches backend field '{closest_match}' in model '{target_schema.name}'."
                        ),
                        frontend_repo=call.repo_name,
                        frontend_file=call.file_path,
                        frontend_line=call.start_line,
                        frontend_field=fe_field,
                        backend_repo=matching_ep.repo_name,
                        backend_file=target_schema.file_path,
                        backend_line=target_schema.start_line,
                        backend_field=closest_match,
                        endpoint_path=matching_ep.path,
                    )
                )

        # Check for missing required backend fields
        sent_fields_normalized = {camel_to_snake(f) for f in call.payload_fields}
        for be_name, be_info in backend_fields.items():
            if be_info.get("required") and be_name not in sent_fields_normalized and be_name not in call.payload_fields:
                if call.payload_fields:  # only flag if frontend is explicitly passing payload
                    issues.append(
                        ContractIssue(
                            issue_type="MISSING_FIELD",
                            severity="warning",
                            description=(
                                f"Missing required field: Backend model '{target_schema.name}' requires '{be_name}', "
                                f"but Frontend payload does not supply it."
                            ),
                            frontend_repo=call.repo_name,
                            frontend_file=call.file_path,
                            frontend_line=call.start_line,
                            frontend_field=None,
                            backend_repo=matching_ep.repo_name,
                            backend_file=target_schema.file_path,
                            backend_line=target_schema.start_line,
                            backend_field=be_name,
                            endpoint_path=matching_ep.path,
                        )
                    )

    return AuditReport(
        total_endpoints=len(endpoints),
        total_schemas=len(schemas),
        total_frontend_calls=len(frontend_calls),
        matched_contracts=matched_contracts,
        issues_found=len(issues),
        issues=[asdict(iss) for iss in issues],
    )

