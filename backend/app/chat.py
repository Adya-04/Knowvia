from collections.abc import Iterator
from openai import OpenAI

from app.config import settings
from app.store import query_chunks

SYSTEM_PROMPT = """You are Knowvia, an Enterprise Multi-Repo Knowledge & Architecture Assistant.
You help engineers, tech leads, and business analysts understand how repos, microservices, and documentation connect across an organization.

Rules:
1. Answer strictly and factually based on the retrieved excerpts.
2. Clearly distinguish sources in your explanation:
   - For repository code: mention the repository name and file path (e.g., in repository `web-app` at `src/services/api.ts:25-50`).
   - For documentation / PDFs: cite the document title and page/line (e.g., in `Payment_Spec.pdf` on Page 4).
3. Always cite evidence in the text using exact references.
4. When explaining flows, cross-repo communication, architecture, or data schemas:
   - Include exactly one Mermaid diagram in a ```mermaid fenced block.
   - For service-to-service, client-to-server, or cross-repo interactions, use `flowchart TD`, `flowchart LR`, or `sequenceDiagram`.
   - For data models, schemas, and entity relationships, use `classDiagram`, `erDiagram`, or `flowchart TD` displaying the entities, their fields, and connections.
   - Keep node IDs alphanumeric without spaces or special characters.
5. If the excerpts reveal a contract/schema mismatch or naming discrepancy (for example, frontend calling with camelCase `userId` while backend expects snake_case `user_id`), explicitly flag it to help the developer!
6. If the excerpts are insufficient to answer the question, clearly state what information is missing from the indexed repositories and documents.
7. For impact questions ("what breaks if I change X?"):
   - Explicitly list all downstream repositories, files, and lines that must be updated.
   - Include a Mermaid flowchart showing the Blast Radius and cascading dependencies.
   - Outline step-by-step remediation instructions.
8. Do not wrap the whole response in JSON.
"""


def _format_context(hits: list[dict]) -> str:
    parts = []
    for i, hit in enumerate(hits, start=1):
        if hit.get("source_type") == "document":
            header = f"[Doc Excerpt {i}] {hit['source_name']} (Page {hit.get('page', 1)})"
        else:
            header = f"[Code Excerpt {i}] [{hit.get('source_name', 'repo')}] {hit['path']}:{hit['start_line']}-{hit['end_line']}"
        parts.append(f"{header}\n{hit['text']}")
    return "\n\n".join(parts)


def _client() -> OpenAI:
    api_key = settings.effective_api_key
    if not api_key:
        raise RuntimeError(
            "API key is missing! Set OPENAI_API_KEY (or CHATANYWHERE_API_KEY) in .env in the project root."
        )
    return OpenAI(api_key=api_key, base_url=settings.effective_base_url)


def citations_from_hits(hits: list[dict]) -> list[dict]:
    seen: set[tuple[str, str, int, int]] = set()
    citations = []
    for hit in hits:
        source_id = hit.get("source_id", "")
        path = hit.get("path", "")
        start_line = int(hit.get("start_line", 1))
        end_line = int(hit.get("end_line", 1))
        page = int(hit.get("page", 1))
        source_type = hit.get("source_type", "repo")
        source_name = hit.get("source_name", source_id)

        key = (source_id, path, start_line, end_line)
        if key in seen:
            continue
        seen.add(key)

        if source_type == "document":
            label = f"{source_name} (Page {page})"
        else:
            label = f"{source_name}: {path}:{start_line}-{end_line}"

        citations.append(
            {
                "source_id": source_id,
                "source_type": source_type,
                "source_name": source_name,
                "path": path,
                "page": page,
                "start_line": start_line,
                "end_line": end_line,
                "label": label,
            }
        )
    return citations


def retrieve(
    messages: list[dict],
    target_id: str | None = None,
    source_type: str | None = None,
    k: int = 10,
) -> tuple[str, list[dict]]:
    question = next(
        (m["content"] for m in reversed(messages) if m.get("role") == "user"),
        "",
    )
    hits = query_chunks(question=question, target_id=target_id, source_type=source_type, k=k)
    context = _format_context(hits) if hits else "(no matching chunks found in indexed knowledge base)"

    # Live Graph-RAG Impact Augmentation
    q_lower = question.lower()
    impact_triggers = {"break", "breaks", "impact", "affect", "affects", "change", "modify", "rename", "refactor"}
    if any(trig in q_lower for trig in impact_triggers):
        candidate_words = [
            w.strip("`'\",.?")
            for w in question.split()
            if "/" in w or "_" in w or (len(w) > 3 and any(c.isupper() for c in w[1:]))
        ]
        target_candidate = candidate_words[0] if candidate_words else question
        try:
            from app.impact import analyze_impact

            rep = analyze_impact(target_candidate)
            if rep.affected_items:
                graph_impact_text = (
                    f"\n\n[Live Knowledge Graph Impact Analysis for '{rep.query}']\n"
                    f"Risk Level: {rep.risk_level}\n"
                    f"Summary: {rep.summary}\n"
                    f"Affected Repos: {', '.join(rep.affected_repos)}\n"
                    f"Affected Code Locations:\n"
                )
                for it in rep.affected_items:
                    graph_impact_text += (
                        f"- {it['repo_name']}: {it['file_path']}:{it['line_number']} "
                        f"[{it['impact_nature']}] {it['description']}\n"
                    )
                context += graph_impact_text
        except Exception:
            pass

    return context, hits


def stream_answer(messages: list[dict], context: str) -> Iterator[str]:
    history = [
        {"role": m["role"], "content": m["content"]}
        for m in messages
        if m.get("role") in {"user", "assistant"} and m.get("content")
    ]
    client = _client()
    stream = client.chat.completions.create(
        model=settings.effective_model,
        temperature=0.2,
        stream=True,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "system",
                "content": f"Retrieved knowledge base excerpts across organization repositories and documents:\n\n{context}",
            },
            *history,
        ],
    )
    for event in stream:
        if not getattr(event, "choices", None):
            continue
        delta = event.choices[0].delta
        if delta and getattr(delta, "content", None):
            yield delta.content
