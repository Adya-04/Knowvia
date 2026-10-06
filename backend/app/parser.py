import ast
from dataclasses import asdict, dataclass, field
from pathlib import Path
import re


@dataclass
class ParsedEndpoint:
    id: str
    repo_id: str
    repo_name: str
    method: str
    path: str
    handler_name: str
    file_path: str
    start_line: int
    end_line: int
    request_schema: str | None = None
    response_schema: str | None = None


@dataclass
class ParsedSchema:
    id: str
    repo_id: str
    repo_name: str
    name: str
    fields: list[dict] = field(default_factory=list)  # [{"name": "userId", "type": "str", "required": True}]
    file_path: str = ""
    start_line: int = 1
    end_line: int = 1


@dataclass
class ParsedFrontendCall:
    id: str
    repo_id: str
    repo_name: str
    method: str
    path: str
    payload_fields: list[str] = field(default_factory=list)
    file_path: str = ""
    start_line: int = 1
    end_line: int = 1
    caller_name: str = ""


# ---------------- Python AST Extractor ----------------


class PythonCodeVisitor(ast.NodeVisitor):
    def __init__(self, repo_id: str, repo_name: str, file_path: str):
        self.repo_id = repo_id
        self.repo_name = repo_name
        self.file_path = file_path
        self.endpoints: list[ParsedEndpoint] = []
        self.schemas: list[ParsedSchema] = []

    def visit_ClassDef(self, node: ast.ClassDef):
        is_model = any(
            isinstance(base, ast.Name) and base.id in {"BaseModel", "Schema", "Model"}
            for base in node.bases
        ) or any(
            isinstance(dec, ast.Name) and dec.id == "dataclass"
            for dec in node.decorator_list
        )
        # Also parse classes with fields even if subclassing isn't explicit
        fields = []
        for stmt in node.body:
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                field_name = stmt.target.id
                field_type = ast.unparse(stmt.annotation) if hasattr(ast, "unparse") else "Any"
                is_required = stmt.value is None or (
                    isinstance(stmt.value, ast.Constant) and stmt.value.value is not None
                )
                fields.append({"name": field_name, "type": field_type, "required": is_required})

        if fields or is_model:
            schema_id = f"{self.repo_id}_schema_{node.name}_{node.lineno}"
            self.schemas.append(
                ParsedSchema(
                    id=schema_id,
                    repo_id=self.repo_id,
                    repo_name=self.repo_name,
                    name=node.name,
                    fields=fields,
                    file_path=self.file_path,
                    start_line=node.lineno,
                    end_line=getattr(node, "end_lineno", node.lineno),
                )
            )
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._check_route(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self._check_route(node)
        self.generic_visit(node)

    def _check_route(self, node: ast.FunctionDef | ast.AsyncFunctionDef):
        http_methods = {"get", "post", "put", "delete", "patch", "route"}
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
                attr_name = dec.func.attr.lower()
                if attr_name in http_methods:
                    method = "GET" if attr_name == "route" else attr_name.upper()
                    # Check method keyword in route(..., methods=['POST'])
                    for kw in dec.keywords:
                        if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple)):
                            for elt in kw.value.elts:
                                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                    method = elt.value.upper()
                                    break

                    route_path = ""
                    if dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str):
                        route_path = dec.args[0].value

                    if route_path:
                        # Extract schema references
                        req_schema = None
                        for arg in node.args.args:
                            if arg.annotation and isinstance(arg.annotation, ast.Name):
                                if arg.arg not in {"self", "cls", "request", "db", "session"}:
                                    req_schema = arg.annotation.id

                        res_schema = None
                        for kw in dec.keywords:
                            if kw.arg == "response_model" and isinstance(kw.value, ast.Name):
                                res_schema = kw.value.id

                        ep_id = f"{self.repo_id}_ep_{method}_{node.name}_{node.lineno}"
                        self.endpoints.append(
                            ParsedEndpoint(
                                id=ep_id,
                                repo_id=self.repo_id,
                                repo_name=self.repo_name,
                                method=method,
                                path=route_path,
                                handler_name=node.name,
                                file_path=self.file_path,
                                start_line=node.lineno,
                                end_line=getattr(node, "end_lineno", node.lineno),
                                request_schema=req_schema,
                                response_schema=res_schema,
                            )
                        )


def parse_python_file(
    content: str, repo_id: str, repo_name: str, file_path: str
) -> tuple[list[ParsedEndpoint], list[ParsedSchema]]:
    try:
        tree = ast.parse(content)
        visitor = PythonCodeVisitor(repo_id, repo_name, file_path)
        visitor.visit(tree)
        return visitor.endpoints, visitor.schemas
    except Exception:
        return [], []


# ---------------- TypeScript / JavaScript Extractor ----------------


INTERFACE_REGEX = re.compile(
    r"(?:export\s+)?(?:interface|type)\s+([A-Za-z0-9_]+)(?:\s*=\s*\{|\s*(?:extends\s+[^{]+)?\s*\{)([\s\S]*?)\}",
    re.MULTILINE,
)

FIELD_REGEX = re.compile(r"([A-Za-z0-9_]+)(\?)?\s*:\s*([^;,\n]+)")

AXIOS_REGEX = re.compile(
    r"(?:axios|api|client|http)\s*\.\s*(get|post|put|delete|patch)\s*\(\s*['\"`]([^'\"`]+)['\"`](?:,\s*(\{[\s\S]*?\}|[A-Za-z0-9_]+))?",
    re.MULTILINE | re.IGNORECASE,
)

FETCH_REGEX = re.compile(
    r"fetch\s*\(\s*['\"`]([^'\"`]+)['\"`](?:,\s*\{([\s\S]*?)\})?",
    re.MULTILINE,
)


def extract_payload_fields(payload_str: str) -> list[str]:
    if not payload_str:
        return []
    clean = payload_str.strip()
    if clean.startswith("{") and clean.endswith("}"):
        inner = clean[1:-1]
        keys = re.findall(r"([A-Za-z0-9_]+)(?:\s*:|\s*,|\s*$)", inner)
        return [k for k in keys if k not in {"headers", "params", "body", "method"}]
    # Single variable or identifier
    m = re.match(r"^[A-Za-z0-9_]+$", clean)
    if m:
        return [m.group(0)]
    return []


def parse_ts_js_file(
    content: str, repo_id: str, repo_name: str, file_path: str
) -> tuple[list[ParsedFrontendCall], list[ParsedSchema]]:
    calls: list[ParsedFrontendCall] = []
    schemas: list[ParsedSchema] = []
    lines = content.splitlines()

    def get_line_num(char_index: int) -> int:
        return content[:char_index].count("\n") + 1

    # 1. Extract interfaces & types
    for m in INTERFACE_REGEX.finditer(content):
        name = m.group(1)
        body = m.group(2)
        start_line = get_line_num(m.start())
        end_line = get_line_num(m.end())

        fields = []
        for fm in FIELD_REGEX.finditer(body):
            fname = fm.group(1)
            is_opt = fm.group(2) == "?"
            ftype = fm.group(3).strip()
            fields.append({"name": fname, "type": ftype, "required": not is_opt})

        if fields:
            schemas.append(
                ParsedSchema(
                    id=f"{repo_id}_ts_schema_{name}_{start_line}",
                    repo_id=repo_id,
                    repo_name=repo_name,
                    name=name,
                    fields=fields,
                    file_path=file_path,
                    start_line=start_line,
                    end_line=end_line,
                )
            )

    # 2. Extract Axios / API client calls
    for m in AXIOS_REGEX.finditer(content):
        method = m.group(1).upper()
        path = m.group(2)
        payload_raw = m.group(3) or ""
        start_line = get_line_num(m.start())
        end_line = get_line_num(m.end())
        payload_fields = extract_payload_fields(payload_raw)

        calls.append(
            ParsedFrontendCall(
                id=f"{repo_id}_call_{method}_{start_line}",
                repo_id=repo_id,
                repo_name=repo_name,
                method=method,
                path=path,
                payload_fields=payload_fields,
                file_path=file_path,
                start_line=start_line,
                end_line=end_line,
            )
        )

    # 3. Extract fetch() calls
    for m in FETCH_REGEX.finditer(content):
        path = m.group(1)
        opts = m.group(2) or ""
        start_line = get_line_num(m.start())
        end_line = get_line_num(m.end())

        method = "GET"
        method_match = re.search(r"method\s*:\s*['\"`]([A-Za-z]+)['\"`]", opts, re.IGNORECASE)
        if method_match:
            method = method_match.group(1).upper()

        payload_fields: list[str] = []
        body_match = re.search(r"body\s*:\s*JSON\.stringify\s*\(([^)]+)\)", opts)
        if body_match:
            payload_fields = extract_payload_fields(body_match.group(1))

        calls.append(
            ParsedFrontendCall(
                id=f"{repo_id}_fetch_{method}_{start_line}",
                repo_id=repo_id,
                repo_name=repo_name,
                method=method,
                path=path,
                payload_fields=payload_fields,
                file_path=file_path,
                start_line=start_line,
                end_line=end_line,
            )
        )

    return calls, schemas


def parse_repo_directory(
    repo_dir: Path, repo_id: str, repo_name: str
) -> tuple[list[ParsedEndpoint], list[ParsedSchema], list[ParsedFrontendCall]]:
    all_endpoints: list[ParsedEndpoint] = []
    all_schemas: list[ParsedSchema] = []
    all_calls: list[ParsedFrontendCall] = []

    if not repo_dir.is_dir():
        return [], [], []

    for path in repo_dir.rglob("*"):
        if not path.is_file():
            continue
        # Skip node_modules, .git, venv, etc.
        if any(p in {"node_modules", ".git", "__pycache__", "dist", "build", ".venv"} for p in path.parts):
            continue

        rel_path = path.relative_to(repo_dir).as_posix()
        suffix = path.suffix.lower()

        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        if suffix in {".py"}:
            endpoints, schemas = parse_python_file(content, repo_id, repo_name, rel_path)
            all_endpoints.extend(endpoints)
            all_schemas.extend(schemas)
        elif suffix in {".ts", ".tsx", ".js", ".jsx"}:
            calls, schemas = parse_ts_js_file(content, repo_id, repo_name, rel_path)
            all_calls.extend(calls)
            all_schemas.extend(schemas)

    return all_endpoints, all_schemas, all_calls
