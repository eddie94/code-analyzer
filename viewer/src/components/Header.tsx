import { useMemo, useState } from "react";
import { useStore } from "../store";

const SEARCHABLE = new Set(["module", "package", "class", "function"]);

export function Header() {
  const index = useStore((s) => s.index)!;
  const { showExternal, showWeak, showCycles, setOption, reveal, reset } = useStore();
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
    if (id) {
      reveal(id);
      setQuery("");
    }
  };

  return (
    <header>
      <div className="brand">
        code<span>map</span>
      </div>
      <div className="repo" title={index.graph.meta.root}>
        {index.graph.meta.root}
      </div>
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
      <Toggle label="외부 라이브러리" checked={showExternal} onChange={(v) => setOption("showExternal", v)} />
      <Toggle label="타입·지연 import" checked={showWeak} onChange={(v) => setOption("showWeak", v)} />
      <Toggle label="순환 강조" checked={showCycles} onChange={(v) => setOption("showCycles", v)} />
      <button onClick={reset}>초기화</button>
    </header>
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
