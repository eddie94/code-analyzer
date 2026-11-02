import { useEffect, useRef, useState } from "react";
import { fetchSource } from "../api";
import { highlightPython } from "../highlight";
import { useStore } from "../store";

type Loaded = { key: string; html: string } | { key: string; error: string };

export function SourceDrawer() {
  const index = useStore((s) => s.index)!;
  const selected = useStore((s) => s.selected);
  const open = useStore((s) => s.sourceOpen);
  const setSourceOpen = useStore((s) => s.setSourceOpen);
  const node = selected ? index.nodes.get(selected) : undefined;
  const path = node?.path ?? null;
  const range = node && node.kind !== "module" ? (node.range ?? null) : null;
  const key = `${path}:${range?.join("-")}`;
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const body = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open || !path) return;
    let cancelled = false;
    fetchSource(path)
      .then((text) => highlightPython(text, range))
      .then((html) => !cancelled && setLoaded({ key, html }))
      .catch((err: Error) => !cancelled && setLoaded({ key, error: err.message }));
    return () => {
      cancelled = true;
    };
    // `key` covers path and range.
  }, [open, key]);

  useEffect(() => {
    body.current?.querySelector(".line.hl")?.scrollIntoView({ block: "start" });
  }, [loaded]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setSourceOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, setSourceOpen]);

  if (!open || !node || !path) return null;
  const line = range?.[0] ?? 1;
  const editorUrl = `vscode://file${index.graph.meta.root}/${path}:${line}`;
  const current = loaded?.key === key ? loaded : null;

  return (
    <section className="drawer">
      <div className="drawer-head">
        <div>
          <div className="drawer-title">{node.qualname}</div>
          <div className="path">
            {path}
            {range ? `:${range[0]}-${range[1]}` : ""}
          </div>
        </div>
        <a className="button" href={editorUrl}>
          VS Code에서 열기
        </a>
        <button onClick={() => setSourceOpen(false)} aria-label="닫기">
          ✕
        </button>
      </div>
      <div className="drawer-body" ref={body}>
        {!current && <p className="muted">불러오는 중…</p>}
        {current && "error" in current && <p className="error-text">불러오기 실패: {current.error}</p>}
        {current && "html" in current && <div className="code" dangerouslySetInnerHTML={{ __html: current.html }} />}
      </div>
    </section>
  );
}
