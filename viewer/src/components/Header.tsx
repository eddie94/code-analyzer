import { useEffect, useMemo, useRef, useState } from "react";
import { useStore } from "../store";
import type { Tab } from "../urlState";

const SEARCHABLE = new Set(["module", "package", "class", "function"]);
const TAB_LABELS: Record<Tab, string> = { overview: "개요", deps: "의존성", classes: "클래스", issues: "이슈" };

export function Header() {
  const index = useStore((s) => s.index)!;
  const tab = useStore((s) => s.tab);
  const setTab = useStore((s) => s.setTab);
  const reveal = useStore((s) => s.reveal);
  const select = useStore((s) => s.select);
  const issueCount = index.graph.issues.length;
  const [query, setQuery] = useState("");

  const byName = useMemo(
    () => new Map(index.graph.nodes.filter((n) => SEARCHABLE.has(n.kind)).map((n) => [n.qualname, n.id])),
    [index],
  );
  const suggestions = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (q.length < 2) return [];
    return [...byName.keys()].filter((name) => name.toLowerCase().includes(q)).slice(0, 50);
  }, [byName, query]);

  const go = (value: string) => {
    const id = byName.get(value.trim());
    if (!id) return;
    // Classes stay in the class tab; everything else is shown in the dependency graph.
    if (tab === "classes" && index.nodes.get(id)?.kind === "class") select(id);
    else reveal(id);
    setQuery("");
  };

  return (
    <header>
      <div className="brand">
        code<span>map</span>
      </div>
      <nav className="tabs">
        {(Object.keys(TAB_LABELS) as Tab[]).map((t) => (
          <button key={t} className={t === tab ? "active" : ""} onClick={() => setTab(t)}>
            {TAB_LABELS[t]}
            {t === "issues" && issueCount > 0 && <span className="count">{issueCount}</span>}
          </button>
        ))}
      </nav>
      <div className="spacer" />
      <input
        type="search"
        placeholder="모듈·클래스 검색"
        list="search-suggestions"
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          if (byName.has(e.target.value)) go(e.target.value);
        }}
        onKeyDown={(e) => e.key === "Enter" && go(query)}
      />
      <datalist id="search-suggestions">
        {suggestions.map((name) => (
          <option key={name} value={name} />
        ))}
      </datalist>
      <ViewOptions />
    </header>
  );
}

function ViewOptions() {
  const { showExternal, showWeak, showCycles, hideTests, setOption, reset } = useStore();
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  return (
    <div className="menu" ref={root}>
      <button onClick={() => setOpen(!open)} aria-expanded={open}>
        보기 ▾
      </button>
      {open && (
        <div className="menu-panel">
          <Toggle label="외부 라이브러리 표시" checked={showExternal} onChange={(v) => setOption("showExternal", v)} />
          <Toggle label="TYPE_CHECKING·함수 안 import 표시" checked={showWeak} onChange={(v) => setOption("showWeak", v)} />
          <Toggle label="순환 의존 강조" checked={showCycles} onChange={(v) => setOption("showCycles", v)} />
          <Toggle label="테스트 코드 숨기기" checked={hideTests} onChange={(v) => setOption("hideTests", v)} />
          <hr />
          <button
            onClick={() => {
              reset();
              setOpen(false);
            }}
          >
            펼침 상태 초기화
          </button>
        </div>
      )}
    </div>
  );
}

function Toggle(props: { label: string; checked: boolean; onChange(value: boolean): void }) {
  return (
    <label className="toggle">
      <input type="checkbox" checked={props.checked} onChange={(e) => props.onChange(e.target.checked)} />
      {props.label}
    </label>
  );
}
