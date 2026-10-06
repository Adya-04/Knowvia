export type Citation = {
  source_type: "repo" | "document";
  source_id: string;
  source_name: string;
  path: string;
  page: number;
  start_line: number;
  end_line: number;
  label: string;
};

export type ChatMessage = {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
};

export type RepoItem = {
  id: string;
  name: string;
  url: string;
  local_path?: string;
  is_local?: boolean;
  file_count: number;
  chunk_count: number;
  capped: boolean;
  status: string;
  created_at?: string;
  updated_at?: string;
};

export type DocItem = {
  id: string;
  name: string;
  filename: string;
  file_type: "pdf" | "markdown" | "text";
  file_size: number;
  page_count: number;
  chunk_count: number;
  status: string;
  created_at?: string;
  updated_at?: string;
};

export type ContractIssue = {
  issue_type: "CASING_MISMATCH" | "POTENTIAL_TYPO" | "MISSING_FIELD" | "UNMAPPED_ROUTE";
  severity: "error" | "warning" | "info";
  description: string;
  frontend_repo: string;
  frontend_file: string;
  frontend_line: number;
  frontend_field?: string;
  backend_repo?: string;
  backend_file?: string;
  backend_line?: number;
  backend_field?: string;
  endpoint_path: string;
};

export type AuditReport = {
  total_endpoints: number;
  total_schemas: number;
  total_frontend_calls: number;
  matched_contracts: number;
  issues_found: number;
  issues: ContractIssue[];
};

export type GraphNodeData = {
  id: string;
  label: string;
  node_type: "repo" | "endpoint" | "schema" | "client_call" | "document";
  repo_name: string;
  file_path: string;
  line_number: number;
  details?: any;
};

export type GraphEdgeData = {
  source: string;
  target: string;
  relationship: string;
  label: string;
};

export type GraphData = {
  nodes: GraphNodeData[];
  edges: GraphEdgeData[];
  audit: AuditReport;
  mermaid: string;
};

export type AffectedItem = {
  repo_name: string;
  file_path: string;
  line_number: number;
  item_type: "frontend_caller" | "endpoint_handler" | "data_schema" | "spec_document";
  description: string;
  impact_nature: "BREAKING_CHANGE" | "PAYLOAD_MISMATCH" | "SPEC_DRIFT" | "DEPENDENT";
};

export type ImpactReport = {
  query: string;
  target_type: string;
  risk_level: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW";
  summary: string;
  affected_repos: string[];
  affected_items: AffectedItem[];
  remediation_steps: string[];
  mermaid: string;
};

export type TraceabilityItem = {
  doc_id: string;
  doc_name: string;
  page: number;
  requirement_title: string;
  requirement_excerpt: string;
  status: "IMPLEMENTED" | "PARTIAL" | "UNMAPPED";
  confidence_score: number;
  matched_code_locations: Array<{
    repo: string;
    file: string;
    line: number;
    label: string;
  }>;
};

export type WorkspaceSummary = {
  repo_count: number;
  doc_count: number;
  total_chunks: number;
  repos: RepoItem[];
  docs: DocItem[];
};

function formatDetail(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (detail == null) return fallback;
  return JSON.stringify(detail);
}

export async function fetchGraph(): Promise<GraphData> {
  const res = await fetch("/api/graph");
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(formatDetail(data.detail, "Could not load knowledge graph"));
  }
  return data as GraphData;
}

export async function fetchAudit(): Promise<AuditReport> {
  const res = await fetch("/api/audit");
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(formatDetail(data.detail, "Could not load audit report"));
  }
  return data as AuditReport;
}

export async function fetchImpact(query: string): Promise<ImpactReport> {
  const params = new URLSearchParams({ query });
  const res = await fetch(`/api/impact?${params.toString()}`);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(formatDetail(data.detail, "Could not compute impact analysis"));
  }
  return data as ImpactReport;
}

export async function fetchTraceability(): Promise<TraceabilityItem[]> {
  const res = await fetch("/api/traceability");
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(formatDetail(data.detail, "Could not load traceability matrix"));
  }
  return data.matrix as TraceabilityItem[];
}

export async function fetchWorkspace(): Promise<WorkspaceSummary> {
  const res = await fetch("/api/workspace");
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(formatDetail(data.detail, "Could not load workspace"));
  }
  return data as WorkspaceSummary;
}

export async function ingestRepo(repoUrl: string): Promise<RepoItem> {
  const res = await fetch("/api/repos/ingest", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ repo_url: repoUrl }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(formatDetail(data.detail, "Repo ingest failed"));
  }
  return data as RepoItem;
}

export async function deleteRepo(repoId: string): Promise<void> {
  const res = await fetch(`/api/repos/${encodeURIComponent(repoId)}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(formatDetail(data.detail, "Could not delete repo"));
  }
}

export async function uploadDoc(file: File): Promise<DocItem> {
  const formData = new FormData();
  formData.append("file", file);

  const res = await fetch("/api/docs/upload", {
    method: "POST",
    body: formData,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(formatDetail(data.detail, "Doc upload failed"));
  }
  return data as DocItem;
}

export async function deleteDoc(docId: string): Promise<void> {
  const res = await fetch(`/api/docs/${encodeURIComponent(docId)}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(formatDetail(data.detail, "Could not delete document"));
  }
}

export async function fetchDocContent(docId: string): Promise<{ name: string; content: string; file_type: string }> {
  const res = await fetch(`/api/docs/${encodeURIComponent(docId)}/content`);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(formatDetail(data.detail, "Could not read document"));
  }
  return data as { name: string; content: string; file_type: string };
}

export async function fetchFile(repoId: string, path: string): Promise<string> {
  const params = new URLSearchParams({ repo_id: repoId, path });
  const res = await fetch(`/api/files?${params.toString()}`);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(formatDetail(data.detail, "Could not load file"));
  }
  return data.content as string;
}

export async function streamChat(
  messages: { role: string; content: string }[],
  options: {
    scope?: "all" | "repo" | "document";
    targetId?: string;
  },
  onToken: (text: string) => void,
  onCitations: (citations: Citation[]) => void,
): Promise<void> {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      messages,
      scope: options.scope || "all",
      target_id: options.targetId,
    }),
  });
  if (!res.ok || !res.body) {
    const data = await res.json().catch(() => ({}));
    throw new Error(formatDetail(data.detail, "Chat failed"));
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";
    for (const part of parts) {
      const line = part.split("\n").find((l) => l.startsWith("data: "));
      if (!line) continue;
      const payload = JSON.parse(line.slice(6)) as {
        type: string;
        text?: string;
        citations?: Citation[];
        detail?: string;
      };
      if (payload.type === "token" && payload.text) onToken(payload.text);
      if (payload.type === "citations" && payload.citations) onCitations(payload.citations);
      if (payload.type === "error") throw new Error(payload.detail || "Chat error");
    }
  }
}
