import { useMemo, useState } from "react";
import { hasSourceApi } from "../api";
import { flowChildren, shortName, type FlowChild } from "../model/flow";
import type { GraphIndex } from "../model/graphIndex";
import { useStore } from "../store";
import type { Place } from "../navigation";
import type { Edge, EntryPoint } from "../types/graph";
import { DataFlowView } from "./DataFlowView";
import { TAB_LABELS } from "./Header";
import { AppView, StepFlowView } from "./StepFlowView";

const KIND_LABELS: Record<EntryPoint["kind"], string> = {
  route: "웹 라우트",
  startup: "시작·종료 훅",
  main: "스크립트 (__main__)",
  command: "CLI 명령",
  script: "설치 스크립트",
  task: "태스크",
};
const OPEN_DEPTH = 1;

export function FlowView() {
  const index = useStore((s) => s.index)!;
  const hideTests = useStore((s) => s.hideTests);
  const storedRoot = useStore((s) => s.flowRoot);
  const [filter, setFilter] = useState("");
  const [showLibraries, setShowLibraries] = useState(true);
  const [mode, setMode] = useState<"data" | "steps" | "tree">("data");
  const showFlow = useStore((s) => s.showFlow);
  const apps = index.graph.apps ?? [];

  const entries = useMemo(
    () =>
      (index.graph.entrypoints ?? []).filter(
        (e) => !hideTests || !index.isTest(index.moduleOf(e.target) ?? e.target),
      ),
    [index, hideTests],
  );
  const root = storedRoot ?? entries.find((e) => e.kind === "route")?.target ?? entries[0]?.target ?? null;
  const rootEntry = entries.find((e) => e.target === root);

  const q = filter.trim().toLowerCase();
  const shown = entries.filter(
    (e) => !q || e.label.toLowerCase().includes(q) || e.target.toLowerCase().includes(q),
  );
  const groups = Object.keys(KIND_LABELS)
    .map((kind) => [kind, shown.filter((e) => e.kind === kind)] as const)
    .filter(([, list]) => list.length);

  return (
    <div className="flow">
      <div className="flow-entries">
        <input type="search" placeholder="진입점 거르기" value={filter} onChange={(e) => setFilter(e.target.value)} />
        {apps.length > 0 && !q && (
          <div>
            <h3>앱 ({apps.length})</h3>
            <ul className="list">
              {apps.map((app) => (
                <li key={app.id} className={app.id === root ? "active" : ""} onClick={() => showFlow(app.id)}>
                  <span className="name">{app.name.split(".").pop()}</span>
                  <span className="meta">
                    {app.kind} · {app.module.slice(4)}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
        {entries.length === 0 && <p className="muted small">진입점을 찾지 못했습니다. 함수의 "흐름에서 보기"로 시작할 수 있습니다.</p>}
        {groups.map(([kind, list]) => (
          <div key={kind}>
            <h3>
              {KIND_LABELS[kind as EntryPoint["kind"]]} ({list.length})
            </h3>
            <ul className="list">
              {list.map((entry) => (
                <EntryRow key={`${entry.kind}:${entry.label}:${entry.target}`} index={index} entry={entry} active={entry.target === root} />
              ))}
            </ul>
          </div>
        ))}
      </div>
      <div className="flow-tree">
        {root?.startsWith("app:") ? (
          <>
            <NavBar index={index} />
            <div className="tree">
              <AppView appId={root} />
            </div>
          </>
        ) : root ? (
          <>
            <NavBar index={index} />
            <div className="overview-bar">
              <span className="flow-title">{rootEntry ? rootEntry.label : shortName(index, root)}</span>
              <span className="muted mono small">{index.nodes.get(root)?.qualname}</span>
              <span className="spacer" />
              <div className="segmented">
                <button className={mode === "data" ? "active" : ""} onClick={() => setMode("data")}>
                  데이터 흐름
                </button>
                <button className={mode === "steps" ? "active" : ""} onClick={() => setMode("steps")}>
                  흐름도
                </button>
                <button className={mode === "tree" ? "active" : ""} onClick={() => setMode("tree")}>
                  호출 트리
                </button>
              </div>
              {mode === "tree" && (
                <label className="toggle">
                  <input type="checkbox" checked={showLibraries} onChange={(e) => setShowLibraries(e.target.checked)} />
                  라이브러리
                </label>
              )}
            </div>
            <div className="tree" key={`${root}:${mode}`}>
              {mode === "data" ? (
                <DataFlowView root={root} />
              ) : mode === "steps" ? (
                <StepFlowView root={root} />
              ) : (
                <FlowRow index={index} id={root} path={[]} depth={0} showLibraries={showLibraries} />
              )}
            </div>
            <p className="muted small legend-line">
              {mode === "data"
                ? "왼쪽 값이 들어가 가운데 함수가 오른쪽 값을 만듭니다 · 둥근 칩: 지역 변수, 각진 칩: 객체(메서드를 부르는 대상, self 속성), 점선 칩: 조건에 쓰인 값 · 칩에 마우스를 올리거나 클릭하면 같은 값이 쓰인 곳이 모두 강조됩니다 · ▸ 함수 안쪽 펼치기"
                : mode === "steps"
                ? "▸ 를 누르면 그 단계 안의 흐름이 펼쳐집니다 · 보조 호출: 바깥 호출·분기 없는 함수 · 추적 불가: 타입을 몰라 못 따라간 호출(LLM 체인 등) · 이름 더블클릭: 그 함수에서 다시 시작"
                : "추론: 변수 타입을 추정해 연결한 호출 · 후보: 실제로는 이 중 하나가 불림 · ↺ 재귀 · 이름을 더블클릭하면 그 함수에서 다시 시작합니다."}
            </p>
          </>
        ) : (
          <p className="empty">진입점을 고르세요.</p>
        )}
      </div>
    </div>
  );
}

function EntryRow({ index, entry, active }: { index: GraphIndex; entry: EntryPoint; active: boolean }) {
  const showFlow = useStore((s) => s.showFlow);
  return (
    <li className={active ? "active" : ""} onClick={() => showFlow(entry.target)}>
      <span className="name">{entry.label}</span>
      <span className="meta">{shortName(index, entry.target)}</span>
    </li>
  );
}

interface RowProps {
  index: GraphIndex;
  id: string;
  edge?: Edge;
  caller?: string;
  path: string[];
  depth: number;
  recursive?: boolean;
  showLibraries: boolean;
}

function FlowRow({ index, id, edge, caller, path, depth, recursive, showLibraries }: RowProps) {
  const [open, setOpen] = useState(depth < OPEN_DEPTH && !recursive);
  const selected = useStore((s) => s.selected === id);
  const { select, showFlow, openSource } = useStore.getState();
  const node = index.nodes.get(id);
  const children = useMemo(
    () => (open ? flowChildren(index, id, path, { showLibraries }) : []),
    [index, id, path, open, showLibraries],
  );
  const expandable = !recursive && (index.callsFrom.has(id) || (node?.unresolved_calls?.length ?? 0) > 0);

  return (
    <div className="flow-node">
      <div className={`flow-row${selected ? " selected" : ""}`} style={{ paddingLeft: 8 + depth * 18 }}>
        <button className="twisty" disabled={!expandable} onClick={() => setOpen(!open)} aria-label={open ? "접기" : "펼치기"}>
          {expandable ? (open ? "▾" : "▸") : "·"}
        </button>
        <span
          className={`flow-name kind-${node?.kind}`}
          onClick={() => select(id)}
          onDoubleClick={() => showFlow(id)}
          title={node?.qualname}
        >
          {shortName(index, id)}
        </span>
        {edge?.awaited && <span className="badge">await</span>}
        {edge?.confidence === "inferred" && <span className="badge soft" title="변수 타입을 추정해 연결">추론</span>}
        {edge?.confidence === "candidates" && <span className="badge warn" title="실제로는 이 중 하나가 불림">후보</span>}
        {recursive && <span className="badge">↺</span>}
        <span className="spacer" />
        {edge?.line && caller && hasSourceApi && (
          <button
            className="link mono small"
            title="호출하는 줄 보기"
            onClick={() => {
              select(caller);
              openSource(edge.line ?? null);
            }}
          >
            L{edge.line}
          </button>
        )}
      </div>
      {open &&
        children.map((child, i) => (
          <ChildRow key={i} index={index} child={child} caller={id} path={[...path, id]} depth={depth + 1} showLibraries={showLibraries} />
        ))}
    </div>
  );
}

function ChildRow(props: {
  index: GraphIndex;
  child: FlowChild;
  caller: string;
  path: string[];
  depth: number;
  showLibraries: boolean;
}) {
  const { index, child, caller, path, depth, showLibraries } = props;
  const indent = { paddingLeft: 8 + depth * 18 + 22 };
  if (child.kind === "libraries") {
    return (
      <div className="flow-row aside" style={indent}>
        <span className="badge soft">라이브러리</span>
        <span className="mono small muted">{child.names.join(", ")}</span>
      </div>
    );
  }
  if (child.kind === "unresolved") {
    return (
      <div className="flow-row aside" style={indent} title="타입을 알 수 없어 따라가지 못한 호출">
        <span className="badge warn">추적 불가</span>
        <span className="mono small muted">{child.texts.join(", ")}</span>
      </div>
    );
  }
  return (
    <FlowRow
      index={index}
      id={child.edge.target}
      edge={child.edge}
      caller={caller}
      path={path}
      depth={depth}
      recursive={child.recursive}
      showLibraries={showLibraries}
    />
  );
}

const TRAIL_SHOWN = 5;

/** Back, and the last few views before this one: click one to go back to it. */
function NavBar({ index }: { index: GraphIndex }) {
  const trail = useStore((s) => s.trail);
  const shown = trail.slice(-TRAIL_SHOWN);
  const label = (place: Place) => {
    if (place.tab !== "flow") return TAB_LABELS[place.tab];
    if (!place.flowRoot) return TAB_LABELS.flow;
    const app = (index.graph.apps ?? []).find((a) => a.id === place.flowRoot);
    return app ? app.name.split(".").pop()! : shortName(index, place.flowRoot);
  };
  return (
    <div className="flow-nav">
      <button className="link" disabled={!trail.length} onClick={() => history.back()} title="이전 화면 (브라우저 뒤로 가기, ⌘[)">
        ← 뒤로
      </button>
      {trail.length > TRAIL_SHOWN && <span className="muted">…</span>}
      {shown.map((place, i) => (
        <span key={i} className="flow-crumb">
          <button className="link mono" onClick={() => history.go(i - shown.length)}>
            {label(place)}
          </button>
          {i < shown.length - 1 && <span className="muted">›</span>}
        </span>
      ))}
    </div>
  );
}
