import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  deleteDoc,
  deleteRepo,
  fetchDocContent,
  fetchFile,
  fetchGraph,
  fetchImpact,
  fetchTraceability,
  fetchWorkspace,
  ingestRepo,
  streamChat,
  uploadDoc,
  type AuditReport,
  type ChatMessage,
  type Citation,
  type DocItem,
  type GraphData,
  type ImpactReport,
  type TraceabilityItem,
  type WorkspaceSummary,
} from "./api";
import { extractMermaid, MermaidBlock, stripMermaid } from "./mermaid";

type OpenCodeFile = {
  repoId: string;
  repoName: string;
  path: string;
  content: string;
  highlight?: { start: number; end: number };
};

type OpenDocFile = {
  docId: string;
  name: string;
  fileType: string;
  content: string;
};

export default function App() {
  const [workspace, setWorkspace] = useState<WorkspaceSummary | null>(null);
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [auditReport, setAuditReport] = useState<AuditReport | null>(null);
  const [loadingAudit, setLoadingAudit] = useState(false);
  const [auditFilter, setAuditFilter] = useState<string>("all");

  // Impact & Traceability state
  const [impactQuery, setImpactQuery] = useState("");
  const [impactReport, setImpactReport] = useState<ImpactReport | null>(null);
  const [loadingImpact, setLoadingImpact] = useState(false);
  const [traceabilityList, setTraceabilityList] = useState<TraceabilityItem[]>([]);
  const [loadingTrace, setLoadingTrace] = useState(false);

  const [repoUrl, setRepoUrl] = useState("https://github.com/pallets/flask");
  const [statusMessage, setStatusMessage] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Chat state
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [scope, setScope] = useState<"all" | "repo" | "document">("all");
  const [targetId, setTargetId] = useState<string>("");

  // Inspect panels
  const [activeTab, setActiveTab] = useState<
    "diagram" | "audit" | "impact" | "trace" | "graph" | "code" | "doc"
  >("diagram");
  const [openCode, setOpenCode] = useState<OpenCodeFile | null>(null);
  const [openDoc, setOpenDoc] = useState<OpenDocFile | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);

  // Load workspace & graph on mount
  useEffect(() => {
    refreshWorkspace();
  }, []);

  async function refreshWorkspace() {
    try {
      const summary = await fetchWorkspace();
      setWorkspace(summary);
      if (summary.repos.length > 0) {
        refreshGraphAndAudit();
      }
    } catch (err) {
      console.error("Failed to load workspace:", err);
    }
  }

  async function refreshGraphAndAudit() {
    setLoadingAudit(true);
    try {
      const g = await fetchGraph();
      setGraphData(g);
      setAuditReport(g.audit);
    } catch (err) {
      console.error("Failed to load graph/audit:", err);
    } finally {
      setLoadingAudit(false);
    }
  }

  async function runImpact(symbol?: string) {
    const q = (symbol || impactQuery).trim();
    if (!q) return;
    setImpactQuery(q);
    setLoadingImpact(true);
    setError(null);
    try {
      const rep = await fetchImpact(q);
      setImpactReport(rep);
      setActiveTab("impact");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Impact analysis failed");
    } finally {
      setLoadingImpact(false);
    }
  }

  async function loadTraceability() {
    setLoadingTrace(true);
    setError(null);
    try {
      const list = await fetchTraceability();
      setTraceabilityList(list);
      setActiveTab("trace");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load traceability");
    } finally {
      setLoadingTrace(false);
    }
  }

  const latestDiagram = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      const msg = messages[i];
      if (msg.role === "assistant") {
        const chart = extractMermaid(msg.content);
        if (chart) return chart;
      }
    }
    return null;
  }, [messages]);

  async function onIngestRepo(event: FormEvent) {
    event.preventDefault();
    if (!repoUrl.trim() || busy) return;
    setBusy(true);
    setError(null);
    setStatusMessage("Cloning & building Knowledge Graph chunks… please wait.");
    try {
      const result = await ingestRepo(repoUrl.trim());
      setStatusMessage(
        `Indexed repo '${result.name}': ${result.file_count} files → ${result.chunk_count} chunks`
      );
      await refreshWorkspace();
      setRepoUrl("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Repo indexing failed");
      setStatusMessage("");
    } finally {
      setBusy(false);
    }
  }

  async function onDeleteRepo(repoId: string, repoName: string) {
    if (!confirm(`Remove repository '${repoName}' from Knowledge Graph?`)) return;
    try {
      await deleteRepo(repoId);
      if (openCode?.repoId === repoId) setOpenCode(null);
      await refreshWorkspace();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete repo");
    }
  }

  async function onUploadDocument(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file || busy) return;
    setBusy(true);
    setError(null);
    setStatusMessage(`Parsing & indexing document '${file.name}'…`);
    try {
      const doc = await uploadDoc(file);
      setStatusMessage(`Indexed document '${doc.name}': ${doc.chunk_count} chunks ready.`);
      await refreshWorkspace();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Document upload failed");
      setStatusMessage("");
    } finally {
      setBusy(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  async function onDeleteDoc(docId: string, docName: string) {
    if (!confirm(`Remove document '${docName}' from Knowledge Graph?`)) return;
    try {
      await deleteDoc(docId);
      if (openDoc?.docId === docId) setOpenDoc(null);
      await refreshWorkspace();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete doc");
    }
  }

  async function onSelectDoc(doc: DocItem) {
    try {
      setError(null);
      const res = await fetchDocContent(doc.id);
      setOpenDoc({
        docId: doc.id,
        name: res.name,
        fileType: res.file_type,
        content: res.content,
      });
      setActiveTab("doc");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not open document");
    }
  }

  async function onAsk(event?: FormEvent) {
    if (event) event.preventDefault();
    const query = input.trim();
    if (!query || busy) return;
    if (!workspace || workspace.total_chunks === 0) {
      setError("Please index at least one repository or document first.");
      return;
    }

    const nextMessages: ChatMessage[] = [...messages, { role: "user", content: query }];
    setMessages(nextMessages);
    setInput("");
    setBusy(true);
    setError(null);
    setMessages([...nextMessages, { role: "assistant", content: "" }]);

    try {
      await streamChat(
        nextMessages,
        {
          scope,
          targetId: targetId || undefined,
        },
        (text) => {
          setMessages((prev) => {
            const copy = [...prev];
            const last = copy[copy.length - 1];
            copy[copy.length - 1] = { ...last, content: last.content + text };
            return copy;
          });
        },
        (citations) => {
          setMessages((prev) => {
            const copy = [...prev];
            const last = copy[copy.length - 1];
            copy[copy.length - 1] = { ...last, citations };
            return copy;
          });
        }
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Chat request failed");
    } finally {
      setBusy(false);
    }
  }

  async function openCitation(c: Citation) {
    setError(null);
    if (c.source_type === "document") {
      try {
        const res = await fetchDocContent(c.source_id);
        setOpenDoc({
          docId: c.source_id,
          name: c.source_name,
          fileType: res.file_type,
          content: res.content,
        });
        setActiveTab("doc");
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not open document citation");
      }
    } else {
      try {
        const content = await fetchFile(c.source_id, c.path);
        setOpenCode({
          repoId: c.source_id,
          repoName: c.source_name,
          path: c.path,
          content,
          highlight: { start: c.start_line, end: c.end_line },
        });
        setActiveTab("code");
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not open code citation");
      }
    }
  }

  async function openIssueFile(repoName: string, filePath: string, line: number) {
    const repo = workspace?.repos.find((r) => r.name === repoName);
    if (!repo) return;
    try {
      setError(null);
      const content = await fetchFile(repo.id, filePath);
      setOpenCode({
        repoId: repo.id,
        repoName: repo.name,
        path: filePath,
        content,
        highlight: { start: line, end: line },
      });
      setActiveTab("code");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not open file");
    }
  }

  const filteredIssues = useMemo(() => {
    if (!auditReport?.issues) return [];
    if (auditFilter === "all") return auditReport.issues;
    if (auditFilter === "casing") return auditReport.issues.filter((i) => i.issue_type === "CASING_MISMATCH");
    if (auditFilter === "typo") return auditReport.issues.filter((i) => i.issue_type === "POTENTIAL_TYPO");
    if (auditFilter === "missing") return auditReport.issues.filter((i) => i.issue_type === "MISSING_FIELD");
    if (auditFilter === "unmapped") return auditReport.issues.filter((i) => i.issue_type === "UNMAPPED_ROUTE");
    return auditReport.issues;
  }, [auditReport, auditFilter]);

  const hasSources = (workspace?.repos.length ?? 0) > 0 || (workspace?.docs.length ?? 0) > 0;
  const issueCount = auditReport?.issues_found ?? 0;

  return (
    <div className="app-container">
      {/* Top Header */}
      <header className="main-header">
        <div className="brand-section">
          <div className="brand-badge">KNOWVIA GRAPH-RAG • PHASE 3</div>
          <h1>Cross-Repo & Architecture Knowledge Graph</h1>
          <p className="subtitle">
            Impact analysis, contract verification, and BA spec-to-code traceability across repositories.
          </p>
        </div>

        <div className="stats-bar">
          <div className="stat-pill">
            <span className="stat-num">{workspace?.repo_count ?? 0}</span> Repos
          </div>
          <div className="stat-pill">
            <span className="stat-num">{workspace?.doc_count ?? 0}</span> Docs
          </div>
          <div className="stat-pill accent">
            <span className="stat-num">{workspace?.total_chunks ?? 0}</span> Graph Chunks
          </div>
          {issueCount > 0 ? (
            <div
              className="stat-pill warning clickable"
              onClick={() => setActiveTab("audit")}
              title="Click to view contract discrepancies"
            >
              ⚠️ <span className="stat-num">{issueCount}</span> Contract Issues
            </div>
          ) : (
            <div className="stat-pill success">
              ✅ Contracts Clean
            </div>
          )}
        </div>
      </header>

      {/* Global Status / Error Alerts */}
      {statusMessage && <div className="alert-box info">{statusMessage}</div>}
      {error && <div className="alert-box error">{error}</div>}

      {/* Main Layout Grid */}
      <div className="three-pane-layout">
        {/* Left Sidebar: Knowledge Sources */}
        <aside className="source-sidebar">
          {/* Add Repository Box */}
          <section className="source-card">
            <h3>Repositories</h3>
            <p className="card-hint">Add public GitHub URL or local path</p>
            <form onSubmit={onIngestRepo} className="add-source-form">
              <input
                type="text"
                placeholder="https://github.com/owner/repo or path"
                value={repoUrl}
                onChange={(e) => setRepoUrl(e.target.value)}
                disabled={busy}
              />
              <button type="submit" disabled={busy || !repoUrl.trim()}>
                {busy ? "..." : "+ Index Repo"}
              </button>
            </form>

            <div className="source-list">
              {workspace?.repos.length === 0 ? (
                <div className="empty-hint">No repositories indexed yet.</div>
              ) : (
                workspace?.repos.map((r) => (
                  <div key={r.id} className="source-item">
                    <div className="source-meta">
                      <div className="source-title" title={r.url}>
                        📁 {r.name}
                      </div>
                      <div className="source-sub">
                        {r.file_count} files • {r.chunk_count} chunks
                      </div>
                    </div>
                    <button
                      type="button"
                      className="del-btn"
                      title="Delete repo"
                      onClick={() => onDeleteRepo(r.id, r.name)}
                    >
                      ×
                    </button>
                  </div>
                ))
              )}
            </div>
          </section>

          {/* Add Documentation Box */}
          <section className="source-card">
            <div className="card-header-flex">
              <h3>Docs & Specs</h3>
              <button
                type="button"
                className="upload-trigger-btn"
                onClick={() => fileInputRef.current?.click()}
                disabled={busy}
              >
                + Upload
              </button>
              <input
                type="file"
                ref={fileInputRef}
                onChange={onUploadDocument}
                accept=".pdf,.md,.markdown,.txt,.json,.yaml,.yml"
                style={{ display: "none" }}
              />
            </div>
            <p className="card-hint">PDFs, PRDs, Markdown specs, API docs</p>

            <div className="source-list">
              {workspace?.docs.length === 0 ? (
                <div className="empty-hint">No documentation uploaded yet.</div>
              ) : (
                workspace?.docs.map((d) => (
                  <div
                    key={d.id}
                    className="source-item clickable"
                    onClick={() => onSelectDoc(d)}
                  >
                    <div className="source-meta">
                      <div className="source-title">
                        {d.file_type === "pdf" ? "📕" : "📝"} {d.name}
                      </div>
                      <div className="source-sub">
                        {d.file_type.toUpperCase()}{" "}
                        {d.page_count > 1 ? `• ${d.page_count} pages` : ""} •{" "}
                        {d.chunk_count} chunks
                      </div>
                    </div>
                    <button
                      type="button"
                      className="del-btn"
                      title="Delete document"
                      onClick={(e) => {
                        e.stopPropagation();
                        onDeleteDoc(d.id, d.name);
                      }}
                    >
                      ×
                    </button>
                  </div>
                ))
              )}
            </div>
          </section>
        </aside>

        {/* Center Pane: Conversational Graph Agent */}
        <main className="chat-center">
          {/* Scope Selector Bar */}
          <div className="scope-toolbar">
            <span className="scope-label">Query Scope:</span>
            <select
              value={scope === "all" ? "all" : `${scope}:${targetId}`}
              onChange={(e) => {
                const val = e.target.value;
                if (val === "all") {
                  setScope("all");
                  setTargetId("");
                } else {
                  const [sc, id] = val.split(":");
                  setScope(sc as any);
                  setTargetId(id);
                }
              }}
            >
              <option value="all">🌐 All Sources (Org Knowledge Graph)</option>
              {workspace?.repos.map((r) => (
                <option key={r.id} value={`repo:${r.id}`}>
                  📁 Repo: {r.name}
                </option>
              ))}
              {workspace?.docs.map((d) => (
                <option key={d.id} value={`document:${d.id}`}>
                  📄 Doc: {d.name}
                </option>
              ))}
            </select>
          </div>

          {/* Messages Container */}
          <div className="chat-messages">
            {messages.length === 0 ? (
              <div className="empty-chat-hero">
                <div className="hero-icon">🧠</div>
                <h2>Explore your Multi-Repo Knowledge Graph</h2>
                <p>
                  Ask about cross-repo architecture, data schemas, impact analysis, or compare PRD
                  documentation against real code.
                </p>

                {hasSources && (
                  <div className="sample-prompts">
                    <button
                      type="button"
                      onClick={() => {
                        setInput("What breaks across repositories if I modify the request schema or route?");
                      }}
                    >
                      💥 What breaks across repositories if I change a model or endpoint?
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setInput("Show a schema diagram or class diagram of the data models and schemas.");
                      }}
                    >
                      📊 Show a schema diagram or class diagram of the data models
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setInput("Are there any schema mismatches, naming typos, or contract drifts between frontend and backend?");
                      }}
                    >
                      🔍 Check API schemas and contract naming between frontend & backend
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setInput("Where is authentication or authorization handled across repositories?");
                      }}
                    >
                      💡 Where is authentication or authorization handled across repos?
                    </button>
                  </div>
                )}
              </div>
            ) : (
              messages.map((msg, idx) => (
                <div key={idx} className={`chat-bubble ${msg.role}`}>
                  <div className="bubble-header">
                    <span className="author-tag">
                      {msg.role === "user" ? "👤 You" : "⚡ Knowvia Assistant"}
                    </span>
                  </div>
                  <div className="bubble-body">
                    {msg.role === "assistant" ? stripMermaid(msg.content) : msg.content}
                  </div>

                  {msg.citations && msg.citations.length > 0 && (
                    <div className="citation-group">
                      <div className="cite-heading">Citations:</div>
                      <div className="cite-pills">
                        {msg.citations.map((c, i) => (
                          <button
                            key={i}
                            type="button"
                            className={`cite-btn ${c.source_type}`}
                            onClick={() => openCitation(c)}
                            title={`Click to view ${c.path}`}
                          >
                            {c.source_type === "document" ? "📄" : "📁"} {c.label}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ))
            )}
          </div>

          {/* Ask Input Box */}
          <form className="ask-form" onSubmit={onAsk}>
            <textarea
              rows={2}
              placeholder={
                hasSources
                  ? "Ask anything about cross-repo flows, endpoints, schemas, or specs..."
                  : "Add a repo or upload a document to get started..."
              }
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  onAsk();
                }
              }}
              disabled={busy || !hasSources}
            />
            <button type="submit" disabled={busy || !input.trim() || !hasSources}>
              Send
            </button>
          </form>
        </main>

        {/* Right Pane: Multi-Inspector */}
        <section className="inspector-panel">
          <div className="tab-strip">
            <button
              className={`tab-btn ${activeTab === "diagram" ? "active" : ""}`}
              onClick={() => setActiveTab("diagram")}
            >
              📊 Flow
            </button>
            <button
              className={`tab-btn ${activeTab === "audit" ? "active" : ""}`}
              onClick={() => {
                setActiveTab("audit");
                if (!auditReport) refreshGraphAndAudit();
              }}
            >
              🔍 Auditor {issueCount > 0 ? `(${issueCount})` : ""}
            </button>
            <button
              className={`tab-btn ${activeTab === "impact" ? "active" : ""}`}
              onClick={() => setActiveTab("impact")}
            >
              💥 Impact
            </button>
            <button
              className={`tab-btn ${activeTab === "trace" ? "active" : ""}`}
              onClick={loadTraceability}
            >
              📋 BA Trace
            </button>
            <button
              className={`tab-btn ${activeTab === "graph" ? "active" : ""}`}
              onClick={() => {
                setActiveTab("graph");
                if (!graphData) refreshGraphAndAudit();
              }}
            >
              🌐 Graph
            </button>
            <button
              className={`tab-btn ${activeTab === "code" ? "active" : ""}`}
              onClick={() => setActiveTab("code")}
            >
              💻 Code {openCode ? `(${openCode.path.split("/").pop()})` : ""}
            </button>
            <button
              className={`tab-btn ${activeTab === "doc" ? "active" : ""}`}
              onClick={() => setActiveTab("doc")}
            >
              📄 Doc {openDoc ? `(${openDoc.name})` : ""}
            </button>
          </div>

          <div className="tab-content">
            {/* Flow Diagram Tab */}
            {activeTab === "diagram" && (
              <div className="diagram-view">
                {latestDiagram ? (
                  <div className="mermaid-box">
                    <MermaidBlock chart={latestDiagram} />
                  </div>
                ) : (
                  <div className="tab-empty">
                    <p>No architecture flow diagram generated yet.</p>
                    <p className="subtext">
                      Ask a question like <em>"What is the request flow?"</em> or <em>"Show a schema diagram"</em> to dynamically generate
                      Mermaid sequence or flowchart diagrams.
                    </p>
                  </div>
                )}
              </div>
            )}

            {/* Contract Auditor Tab */}
            {activeTab === "audit" && (
              <div className="audit-view">
                <div className="audit-header-bar">
                  <div className="audit-metrics">
                    <div className="metric-box">
                      <span className="metric-val">{auditReport?.total_endpoints ?? 0}</span>
                      <span className="metric-lbl">Endpoints</span>
                    </div>
                    <div className="metric-box">
                      <span className="metric-val">{auditReport?.total_schemas ?? 0}</span>
                      <span className="metric-lbl">Schemas</span>
                    </div>
                    <div className="metric-box">
                      <span className="metric-val">{auditReport?.total_frontend_calls ?? 0}</span>
                      <span className="metric-lbl">Client Calls</span>
                    </div>
                    <div className={`metric-box ${issueCount > 0 ? "highlight-error" : "highlight-ok"}`}>
                      <span className="metric-val">{issueCount}</span>
                      <span className="metric-lbl">Discrepancies</span>
                    </div>
                  </div>
                  <button
                    type="button"
                    className="refresh-btn"
                    onClick={refreshGraphAndAudit}
                    disabled={loadingAudit}
                  >
                    {loadingAudit ? "Scanning..." : "🔄 Rescan"}
                  </button>
                </div>

                {/* Filter Pills */}
                <div className="audit-filters">
                  <button
                    type="button"
                    className={`filter-pill ${auditFilter === "all" ? "active" : ""}`}
                    onClick={() => setAuditFilter("all")}
                  >
                    All ({auditReport?.issues.length ?? 0})
                  </button>
                  <button
                    type="button"
                    className={`filter-pill ${auditFilter === "casing" ? "active" : ""}`}
                    onClick={() => setAuditFilter("casing")}
                  >
                    Casing Mismatches
                  </button>
                  <button
                    type="button"
                    className={`filter-pill ${auditFilter === "typo" ? "active" : ""}`}
                    onClick={() => setAuditFilter("typo")}
                  >
                    Typos
                  </button>
                  <button
                    type="button"
                    className={`filter-pill ${auditFilter === "missing" ? "active" : ""}`}
                    onClick={() => setAuditFilter("missing")}
                  >
                    Missing Fields
                  </button>
                  <button
                    type="button"
                    className={`filter-pill ${auditFilter === "unmapped" ? "active" : ""}`}
                    onClick={() => setAuditFilter("unmapped")}
                  >
                    Unmapped Routes
                  </button>
                </div>

                {/* Issue Cards Scrollable List */}
                <div className="audit-list">
                  {filteredIssues.length === 0 ? (
                    <div className="tab-empty">
                      <p>✅ No contract issues or typos detected!</p>
                      <p className="subtext">
                        Frontend client calls and backend API models appear aligned or no calls were found in the selected filter.
                      </p>
                    </div>
                  ) : (
                    filteredIssues.map((issue, idx) => (
                      <div key={idx} className={`issue-card severity-${issue.severity}`}>
                        <div className="issue-card-top">
                          <span className={`issue-badge ${issue.issue_type.toLowerCase()}`}>
                            {issue.issue_type.replace("_", " ")}
                          </span>
                          <span className="issue-endpoint">{issue.endpoint_path}</span>
                          <button
                            type="button"
                            className="impact-jump-btn"
                            onClick={() => runImpact(issue.endpoint_path)}
                            title="Analyze Blast Radius if this is modified"
                          >
                            💥 Check Impact
                          </button>
                        </div>
                        <p className="issue-desc">{issue.description}</p>

                        <div className="issue-locations">
                          <button
                            type="button"
                            className="loc-btn fe"
                            onClick={() =>
                              openIssueFile(issue.frontend_repo, issue.frontend_file, issue.frontend_line)
                            }
                            title="Jump to frontend call in code viewer"
                          >
                            🌐 [FE] {issue.frontend_repo}: {issue.frontend_file}:{issue.frontend_line}
                          </button>
                          {issue.backend_repo && issue.backend_file && (
                            <button
                              type="button"
                              className="loc-btn be"
                              onClick={() =>
                                openIssueFile(issue.backend_repo!, issue.backend_file!, issue.backend_line || 1)
                              }
                              title="Jump to backend schema in code viewer"
                            >
                              📦 [BE] {issue.backend_repo}: {issue.backend_file}:{issue.backend_line}
                            </button>
                          )}
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </div>
            )}

            {/* Impact Analysis Tab */}
            {activeTab === "impact" && (
              <div className="impact-view">
                <div className="impact-search-bar">
                  <input
                    type="text"
                    placeholder="Enter endpoint (e.g. /api/users) or symbol/field (e.g. user_id)"
                    value={impactQuery}
                    onChange={(e) => setImpactQuery(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") runImpact();
                    }}
                  />
                  <button type="button" onClick={() => runImpact()} disabled={loadingImpact || !impactQuery.trim()}>
                    {loadingImpact ? "Analyzing..." : "💥 Analyze Impact"}
                  </button>
                </div>

                {impactReport ? (
                  <div className="impact-results-scroll">
                    <div className="impact-summary-card">
                      <div className="impact-top-meta">
                        <span className={`risk-badge ${impactReport.risk_level.toLowerCase()}`}>
                          Risk: {impactReport.risk_level}
                        </span>
                        <span className="target-badge">Target: {impactReport.query}</span>
                      </div>
                      <p className="impact-summary-text">{impactReport.summary}</p>
                      <div className="affected-repos-tags">
                        <span className="tag-label">Affected Repos:</span>
                        {impactReport.affected_repos.length === 0 ? (
                          <span className="tag-item">None</span>
                        ) : (
                          impactReport.affected_repos.map((r) => (
                            <span key={r} className="tag-item">
                              📁 {r}
                            </span>
                          ))
                        )}
                      </div>
                    </div>

                    {/* Blast Radius Visual Diagram */}
                    {impactReport.mermaid && (
                      <div className="blast-radius-box">
                        <div className="box-title">Blast Radius Cascade:</div>
                        <MermaidBlock chart={impactReport.mermaid} />
                      </div>
                    )}

                    {/* Affected Code Locations */}
                    <div className="affected-items-section">
                      <div className="box-title">Cascading Locations ({impactReport.affected_items.length}):</div>
                      <div className="affected-items-list">
                        {impactReport.affected_items.map((item, idx) => (
                          <div key={idx} className="affected-item-row">
                            <div className="item-meta">
                              <span className={`nature-badge ${item.impact_nature.toLowerCase()}`}>
                                {item.impact_nature.replace("_", " ")}
                              </span>
                              <span className="item-desc">{item.description}</span>
                            </div>
                            <button
                              type="button"
                              className="jump-code-btn"
                              onClick={() => openIssueFile(item.repo_name, item.file_path, item.line_number)}
                            >
                              Jump to {item.file_path}:{item.line_number}
                            </button>
                          </div>
                        ))}
                      </div>
                    </div>

                    {/* Remediation Steps */}
                    {impactReport.remediation_steps.length > 0 && (
                      <div className="remediation-box">
                        <div className="box-title">Recommended Remediation Steps:</div>
                        <ul>
                          {impactReport.remediation_steps.map((step, i) => (
                            <li key={i}>{step}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="tab-empty">
                    <p>💥 Cross-Repo Impact Analysis</p>
                    <p className="subtext">
                      Type an endpoint, model name, or payload field to trace downstream callers and breaking
                      changes across repositories before modifying code.
                    </p>
                  </div>
                )}
              </div>
            )}

            {/* BA Spec Traceability Tab */}
            {activeTab === "trace" && (
              <div className="trace-view">
                <div className="trace-header-bar">
                  <span className="trace-caption">Document Requirement ↔ Code Matrix:</span>
                  <button type="button" className="refresh-btn" onClick={loadTraceability} disabled={loadingTrace}>
                    {loadingTrace ? "Matching..." : "🔄 Refresh Matrix"}
                  </button>
                </div>

                <div className="trace-list-scroll">
                  {traceabilityList.length === 0 ? (
                    <div className="tab-empty">
                      <p>No document requirements matched yet.</p>
                      <p className="subtext">Upload a PRD, specification, or PDF to map business requirements to code.</p>
                    </div>
                  ) : (
                    traceabilityList.map((item, idx) => (
                      <div key={idx} className="trace-item-card">
                        <div className="trace-card-top">
                          <span className={`status-pill ${item.status.toLowerCase()}`}>{item.status}</span>
                          <span className="trace-doc-name">
                            📄 {item.doc_name} (Page {item.page})
                          </span>
                        </div>
                        <h4 className="req-title">{item.requirement_title}</h4>
                        <p className="req-excerpt">"{item.requirement_excerpt}"</p>

                        <div className="matched-code-box">
                          <div className="matched-header">Mapped Code Endpoints & Models:</div>
                          {item.matched_code_locations.length === 0 ? (
                            <div className="unmapped-hint">⚠️ No code implementation detected for this requirement.</div>
                          ) : (
                            <div className="matched-links">
                              {item.matched_code_locations.map((loc, li) => (
                                <button
                                  key={li}
                                  type="button"
                                  className="loc-btn be"
                                  onClick={() => openIssueFile(loc.repo, loc.file, loc.line)}
                                >
                                  📁 {loc.repo}: {loc.label} ({loc.file}:{loc.line})
                                </button>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </div>
            )}

            {/* Schema Graph Tab */}
            {activeTab === "graph" && (
              <div className="graph-view">
                <div className="graph-toolbar">
                  <span className="graph-caption">Cross-Repo Topology & Schemas:</span>
                  <button
                    type="button"
                    className="refresh-btn"
                    onClick={refreshGraphAndAudit}
                    disabled={loadingAudit}
                  >
                    {loadingAudit ? "Loading..." : "🔄 Refresh Graph"}
                  </button>
                </div>
                {graphData?.mermaid ? (
                  <div className="mermaid-box">
                    <MermaidBlock chart={graphData.mermaid} />
                  </div>
                ) : (
                  <div className="tab-empty">
                    <p>No knowledge graph data available.</p>
                    <p className="subtext">Index repositories to generate cross-repo topology.</p>
                  </div>
                )}
              </div>
            )}

            {/* Code Viewer Tab */}
            {activeTab === "code" && (
              <div className="code-view">
                {openCode ? (
                  <>
                    <div className="file-header">
                      <span className="file-repo">📁 {openCode.repoName}</span>
                      <span className="file-path">{openCode.path}</span>
                    </div>
                    <pre className="code-scroll">
                      {openCode.content.split("\n").map((line, idx) => {
                        const lineNum = idx + 1;
                        const isHighlighted =
                          openCode.highlight &&
                          lineNum >= openCode.highlight.start &&
                          lineNum <= openCode.highlight.end;
                        return (
                          <div
                            key={lineNum}
                            className={`code-row ${isHighlighted ? "highlighted" : ""}`}
                          >
                            <span className="line-num">{lineNum}</span>
                            <span className="line-text">{line}</span>
                          </div>
                        );
                      })}
                    </pre>
                  </>
                ) : (
                  <div className="tab-empty">
                    <p>No file selected.</p>
                    <p className="subtext">
                      Click any citation, audit issue, or impact location to inspect the file.
                    </p>
                  </div>
                )}
              </div>
            )}

            {/* Doc Reader Tab */}
            {activeTab === "doc" && (
              <div className="doc-view">
                {openDoc ? (
                  <>
                    <div className="file-header">
                      <span className="file-repo">
                        {openDoc.fileType === "pdf" ? "📕 PDF Spec" : "📝 Documentation"}
                      </span>
                      <span className="file-path">{openDoc.name}</span>
                    </div>
                    <div className="doc-text-scroll">
                      <pre>{openDoc.content}</pre>
                    </div>
                  </>
                ) : (
                  <div className="tab-empty">
                    <p>No document selected.</p>
                    <p className="subtext">
                      Click any document in the sidebar or a document citation in chat to read its text.
                    </p>
                  </div>
                )}
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
