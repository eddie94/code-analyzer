import type { ReactNode } from "react";
import { hasSourceApi } from "../api";
import { reachingEntrypoints, shortName } from "../model/flow";
import { isLibrary, type GraphIndex } from "../model/graphIndex";
import { useStore } from "../store";
import type { Edge, Issue, Node } from "../types/graph";

const LIST_LIMIT = 40;

export function SidePanel() {
  const index = useStore((s) => s.index)!;
  const selected = useStore((s) => s.selected);
  const node = selected ? index.nodes.get(selected) : undefined;
  return <aside>{node ? <Details index={index} node={node} /> : <Overview index={index} />}</aside>;
}

function Overview({ index }: { index: GraphIndex }) {
  const setTab = useStore((s) => s.setTab);
  const { graph, modules } = index;
  const loc = modules.reduce((sum, m) => sum + (m.metrics?.loc ?? 0), 0);
  const count = (kind: Node["kind"]) => graph.nodes.filter((n) => n.kind === kind).length;
  const severity = { error: 0, warning: 1, info: 2 };
  const issues = [...graph.issues].sort((a, b) => severity[a.severity] - severity[b.severity]);
  return (
    <>
      <span className="kind">repository</span>
      <h2>{graph.meta.root.split("/").pop()}</h2>
      <div className="stats">
        <Stat value={modules.length} name="모듈" />
        <Stat value={count("package")} name="패키지" />
        <Stat value={loc.toLocaleString()} name="코드 줄 수" />
        <Stat value={count("class")} name="클래스" />
      </div>
      <h3>이슈 ({issues.length})</h3>
      {issues.length ? (
        issues.slice(0, 5).map((issue, i) => <IssueCard key={i} index={index} issue={issue} />)
      ) : (
        <p className="muted">없음</p>
      )}
      {issues.length > 5 && (
        <button className="link" onClick={() => setTab("issues")}>
          이슈 {issues.length}개 모두 보기 →
        </button>
      )}
      <h3>사용법</h3>
      <p className="muted">
        노드를 클릭하면 상세 정보, 더블클릭하면 패키지를 펼치거나 접습니다. 마우스를 올리면 연결된 의존만 강조됩니다.
      </p>
    </>
  );
}

function IssueCard({ index, issue }: { index: GraphIndex; issue: Issue }) {
  const reveal = useStore((s) => s.reveal);
  const names = issue.nodes.map((id) => index.nodes.get(id)?.qualname ?? id);
  const where =
    names.length > 1
      ? `${names.length}개 모듈: ${names.slice(0, 3).join(", ")}${names.length > 3 ? " …" : ""}`
      : `${names[0]}${issue.line ? `:${issue.line}` : ""}`;
  return (
    <div className={`issue ${issue.severity}`} onClick={() => reveal(issue.nodes[0])}>
      {issue.message}
      <small>{where}</small>
    </div>
  );
}

function Details({ index, node }: { index: GraphIndex; node: Node }) {
  const toggle = useStore((s) => s.toggle);
  const openSource = useStore((s) => s.openSource);
  const expanded = useStore((s) => s.expanded.has(node.id));
  const isPackage = node.kind === "package";
  const hasSource = hasSourceApi && Boolean(node.path) && !isPackage;

  return (
    <>
      <Breadcrumb index={index} node={node} />
      <span className="kind">{kindLabel(node)}</span>
      {node.layer && <span className="kind layer">레이어: {node.layer}</span>}
      <h2>{node.qualname}</h2>
      {node.path && <div className="path">{node.path}{node.range && node.kind !== "module" ? `:${node.range[0]}` : ""}</div>}
      {node.doc && <div className="doc">{node.doc}</div>}
      {node.decorators?.length ? (
        <div className="decorators">{node.decorators.map((d) => <code key={d}>@{d}</code>)}</div>
      ) : null}
      <div className="actions">
        {isPackage && <button onClick={() => toggle(node.id)}>{expanded ? "접기" : "펼치기"}</button>}
        {hasSource && <button onClick={() => openSource()}>소스 보기</button>}
      </div>
      {node.kind === "package" || node.kind === "module" ? <ContainerDetails index={index} node={node} /> : null}
      {node.kind === "class" ? <ClassDetails index={index} node={node} /> : null}
      {node.kind === "function" || node.kind === "method" ? <FunctionDetails index={index} node={node} /> : null}
      {isLibrary(node) ? <Dependencies title="이 라이브러리를 쓰는 곳" entries={incoming(index, node.id)} index={index} /> : null}
    </>
  );
}

function ContainerDetails({ index, node }: { index: GraphIndex; node: Node }) {
  const metrics = node.metrics ?? {};
  const inside = (id: string) => (node.kind === "package" ? index.isInside(id, node.id) : id === node.id);
  const out = group(index.imports.filter((e) => inside(e.source) && !inside(e.target)), (e) => e.target);
  const inc = group(index.imports.filter((e) => inside(e.target) && !inside(e.source)), (e) => e.source);
  const symbols = (index.children.get(node.id) ?? []).filter((n) => n.kind === "class" || n.kind === "function");
  return (
    <>
      <div className="stats">
        <Stat value={metrics.loc ?? "–"} name="코드 줄 수" />
        {node.kind === "package" ? (
          <Stat value={index.moduleCount(node.id)} name="모듈" />
        ) : (
          <Stat value={metrics.symbols ?? "–"} name="클래스·함수" />
        )}
        <Stat value={inc.size} name="이 대상을 쓰는 모듈" />
        <Stat value={out.size} name="의존하는 대상" />
        <Stat value={metrics.instability?.toFixed(2) ?? "–"} name="불안정성 (0 안정 ~ 1 불안정)" />
        <Stat value={metrics.max_complexity ?? "–"} name="최대 함수 복잡도" />
        {metrics.churn != null && (
          <>
            <Stat value={metrics.churn} name={`최근 ${index.graph.meta.churn_days}일 커밋 수`} />
            <Stat value={metrics.hotspot ?? "–"} name="핫스팟 (커밋 × 복잡도)" />
          </>
        )}
      </div>
      <Dependencies title="의존하는 대상" entries={out} index={index} />
      <Dependencies title="이 대상을 쓰는 곳" entries={inc} index={index} />
      {symbols.length > 0 && (
        <>
          <h3>클래스·함수 ({symbols.length})</h3>
          <SymbolList index={index} symbols={symbols} />
        </>
      )}
    </>
  );
}

function ClassDetails({ index, node }: { index: GraphIndex; node: Node }) {
  const bases = index.extends.filter((e) => e.source === node.id).map((e) => e.target);
  const subclasses = index.extends.filter((e) => e.target === node.id).map((e) => e.source);
  const members = index.children.get(node.id) ?? [];
  return (
    <>
      {bases.length > 0 && <NodeList title="상속하는 클래스" ids={bases} index={index} />}
      {subclasses.length > 0 && <NodeList title="하위 클래스" ids={subclasses} index={index} />}
      {members.length > 0 && (
        <>
          <h3>멤버 ({members.length})</h3>
          <SymbolList index={index} symbols={members} />
        </>
      )}
    </>
  );
}

function FunctionDetails({ index, node }: { index: GraphIndex; node: Node }) {
  const { showFlow, select } = useStore.getState();
  const lines = node.range ? node.range[1] - node.range[0] + 1 : null;
  const callees = (index.callsFrom.get(node.id) ?? []).filter((e) => !isLibrary(index.nodes.get(e.target)!));
  const libraries = [
    ...new Set(
      (index.callsFrom.get(node.id) ?? [])
        .filter((e) => isLibrary(index.nodes.get(e.target)!))
        .flatMap((e) => e.names ?? []),
    ),
  ];
  const callers = index.callsTo.get(node.id) ?? [];
  const entries = reachingEntrypoints(index, node.id);
  return (
    <>
      <div className="stats">
        <Stat value={node.metrics?.complexity ?? "–"} name="순환 복잡도" />
        <Stat value={lines ?? "–"} name="줄 수" />
        <Stat value={callers.length} name="이 함수를 부르는 곳" />
        <Stat value={callees.length} name="호출하는 함수" />
      </div>
      <div className="actions">
        <button onClick={() => showFlow(node.id)}>흐름에서 보기</button>
      </div>
      {entries.length > 0 && (
        <>
          <h3>도달하는 진입점 ({entries.length})</h3>
          <ul className="list">
            {entries.map((e) => (
              <li key={`${e.kind}:${e.label}`} onClick={() => showFlow(e.target)}>
                <span className="name">{e.label}</span>
              </li>
            ))}
          </ul>
        </>
      )}
      <CallList title="호출하는 함수" ids={callees.map((e) => e.target)} index={index} onPick={select} />
      <CallList title="이 함수를 부르는 곳" ids={callers.map((e) => e.source)} index={index} onPick={select} />
      {libraries.length > 0 && (
        <>
          <h3>라이브러리 호출 ({libraries.length})</h3>
          <p className="mono small muted">{libraries.join(", ")}</p>
        </>
      )}
      {(node.unresolved_calls?.length ?? 0) > 0 && (
        <>
          <h3>따라가지 못한 호출 ({node.unresolved_calls!.length})</h3>
          <p className="mono small muted">{node.unresolved_calls!.join(", ")}</p>
        </>
      )}
    </>
  );
}

function CallList(props: { title: string; ids: string[]; index: GraphIndex; onPick(id: string): void }) {
  const ids = [...new Set(props.ids)];
  if (!ids.length) return null;
  return (
    <>
      <h3>
        {props.title} ({ids.length})
      </h3>
      <ul className="list">
        {ids.slice(0, LIST_LIMIT).map((id) => (
          <li key={id} onClick={() => props.onPick(id)}>
            <span className="name">{shortName(props.index, id)}</span>
            <span className="meta">{props.index.nodes.get(props.index.moduleOf(id) ?? "")?.qualname}</span>
          </li>
        ))}
      </ul>
    </>
  );
}

function SymbolList({ index, symbols }: { index: GraphIndex; symbols: Node[] }) {
  const select = useStore((s) => s.select);
  return (
    <ul className="list">
      {symbols.map((s) => (
        <li key={s.id} onClick={() => select(s.id)}>
          <span className="name">
            {s.name}
            {s.is_async && <span className="tag">async</span>}
          </span>
          <span className="meta">
            {kindLabel(s)} · L{s.range?.[0]}
            {s.metrics?.complexity ? ` · 복잡도 ${s.metrics.complexity}` : ""}
            {index.children.get(s.id)?.length ? ` · ${index.children.get(s.id)!.length} 멤버` : ""}
          </span>
        </li>
      ))}
    </ul>
  );
}

interface Entry {
  count: number;
  weak: boolean;
  names: Set<string>;
}

function group(edges: Edge[], key: (e: Edge) => string): Map<string, Entry> {
  const map = new Map<string, Entry>();
  for (const e of edges) {
    const entry = map.get(key(e)) ?? { count: 0, weak: true, names: new Set() };
    entry.count += 1;
    entry.weak &&= Boolean(e.type_only || e.lazy);
    e.names?.forEach((n) => entry.names.add(n));
    map.set(key(e), entry);
  }
  return map;
}

function incoming(index: GraphIndex, id: string) {
  return group(index.imports.filter((e) => e.target === id), (e) => e.source);
}

function Dependencies({ title, entries, index }: { title: string; entries: Map<string, Entry>; index: GraphIndex }) {
  const reveal = useStore((s) => s.reveal);
  const select = useStore((s) => s.select);
  if (!entries.size) return null;
  const rows = [...entries].sort((a, b) => b[1].count - a[1].count || a[0].localeCompare(b[0]));
  return (
    <>
      <h3>
        {title} ({entries.size})
      </h3>
      <ul className="list">
        {rows.slice(0, LIST_LIMIT).map(([id, entry]) => {
          const node = index.nodes.get(id)!;
          return (
            <li key={id} onClick={() => (isLibrary(node) ? select(id) : reveal(id))}>
              <span className="name">
                {node.qualname}
                {entry.weak && <span className="tag">지연/타입</span>}
              </span>
              <span className="meta">{[...entry.names].slice(0, 3).join(", ")}</span>
            </li>
          );
        })}
      </ul>
      {rows.length > LIST_LIMIT && <p className="muted">외 {rows.length - LIST_LIMIT}개</p>}
    </>
  );
}

function NodeList({ title, ids, index }: { title: string; ids: string[]; index: GraphIndex }) {
  const reveal = useStore((s) => s.reveal);
  return (
    <>
      <h3>{title}</h3>
      <ul className="list">
        {ids.map((id) => (
          <li key={id} onClick={() => reveal(id)}>
            <span className="name">{index.nodes.get(id)?.qualname ?? id}</span>
          </li>
        ))}
      </ul>
    </>
  );
}

function Breadcrumb({ index, node }: { index: GraphIndex; node: Node }) {
  const select = useStore((s) => s.select);
  const trail: ReactNode[] = [];
  for (let id = node.parent; id; id = index.nodes.get(id)?.parent) {
    const parent = index.nodes.get(id)!;
    trail.unshift(
      <button key={id} className="crumb" onClick={() => select(id)}>
        {parent.kind === "module" && parent.name === "__init__" ? "__init__" : parent.name}
      </button>,
    );
  }
  return (
    <nav className="breadcrumb">
      <button className="crumb" onClick={() => select(null)}>
        repo
      </button>
      {trail}
    </nav>
  );
}

function Stat({ value, name }: { value: ReactNode; name: string }) {
  return (
    <div className="stat">
      <b>{value}</b>
      <span>{name}</span>
    </div>
  );
}

function kindLabel(node: Node): string {
  if (node.kind === "function") return node.is_async ? "async def" : "def";
  if (node.kind === "method") return node.is_async ? "async method" : "method";
  return node.kind;
}
