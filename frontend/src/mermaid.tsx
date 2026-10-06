import { useEffect, useRef } from "react";
import mermaid from "mermaid";

mermaid.initialize({
  startOnLoad: false,
  theme: "dark",
  securityLevel: "strict",
  fontFamily: "IBM Plex Sans, Segoe UI, sans-serif",
});

let diagramCount = 0;

export function MermaidBlock({ chart }: { chart: string }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const id = `knowvia-diagram-${++diagramCount}`;
    mermaid
      .render(id, chart)
      .then(({ svg }) => {
        node.innerHTML = svg;
      })
      .catch(() => {
        node.textContent = "Could not render this diagram.";
      });
    return () => {
      node.innerHTML = "";
    };
  }, [chart]);

  return <div className="mermaid-wrap" ref={ref} />;
}

export function extractMermaid(markdown: string): string | null {
  const match = markdown.match(/```mermaid\s+([\s\S]*?)```/i);
  return match ? match[1].trim() : null;
}

export function stripMermaid(markdown: string): string {
  return markdown.replace(/```mermaid\s+[\s\S]*?```/gi, "").trim();
}
