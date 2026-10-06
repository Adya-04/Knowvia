# Knowvia

**Knowvia** turns scattered organizational knowledge into an intelligent, searchable Knowledge Graph with AI chat, architecture visualization, cross-repo contract verification, and document-to-code traceability.

---

## 🚀 Features (Phase 1)

- **Multi-Repo Knowledge Graph:** Index multiple public GitHub repositories and local service codebases into a single connected knowledge graph.
- **Documentation & Spec Ingestion:** Upload and index `.pdf`, `.md`, `.txt`, and `.yaml` files (PRDs, architecture specs, user stories, API designs).
- **Cross-Source Hybrid RAG:** Query across the entire organization (all repos and documents) or filter down to specific services.
- **Rich Citations with 1-Click Inspection:**
  - Code citations jump directly to the exact file and highlight the line range.
  - Document citations open the PDF/Markdown reader with page and section excerpts.
- **Dynamic Architecture & Flow Diagrams:** Automatically renders Mermaid sequence and flow diagrams for system flows, microservice communications, and frontend-to-backend request lifecycles.
- **Local Embeddings:** Embeddings run locally via ChromaDB (no external embedding API needed).

---

## 📋 Requirements

- **Python 3.11+**
- **Node.js 18+**
- **Git**
- An OpenAI-compatible API key for chat (`OPENAI_API_KEY`)

---

## 🏃 Quick Start (Windows PowerShell)

### 1. Configure Environment
In the project root (`Knowvia` folder):
```powershell
copy .env.example .env
# Edit .env and set your OPENAI_API_KEY
```

### 2. Start Backend
```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### 3. Start Frontend
In a second terminal:
```powershell
cd frontend
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173).

---

## 💡 Example Workflows to Try

1. **Index Multiple Repositories:**
   - Index `https://github.com/pallets/flask`
   - Index another service or library
2. **Upload Business Docs / PRDs:**
   - Click **+ Upload** to ingest a PDF or Markdown specification.
3. **Ask Architecture & Cross-Source Questions:**
   - *"What is the request/response lifecycle from client to backend?"*
   - *"Where is routing or authentication handled?"*
   - *"Does our codebase implement the requirements in our uploaded specification document?"*
