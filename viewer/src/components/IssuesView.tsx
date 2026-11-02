import { useMemo, useState } from "react";
import type { GraphIndex } from "../model/graphIndex";
import { useStore } from "../store";
import type { Issue } from "../types/graph";

type Category = "cycle" | "init_cycle" | "deferred_cycle" | "unresolved_import" | "parse_error";

const CATEGORIES: Array<[Category, string, string]> = [
  ["cycle", "순환 의존", "import 시점에 서로를 불러오는 모듈들입니다. 불러오는 순서에 따라 ImportError가 날 수 있습니다."],
  [
    "init_cycle",
    "__init__를 거치는 순환",
    "하위 모듈이 자기 패키지를 import하고, 패키지 __init__이 그 하위 모듈을 다시 불러오는 경우입니다. 흔한 패턴이지만 결합이 강하다는 신호입니다.",
  ],
  [
    "deferred_cycle",
    "타입·지연 import 순환",
    "TYPE_CHECKING 블록이나 함수 안 import로만 닫히는 순환입니다. 로딩은 깨지지 않지만 구조적으로는 서로 의존합니다.",
  ],
  ["unresolved_import", "해석 안 된 import", "리포지토리 안에서 찾지 못한 import입니다."],
  ["parse_error", "파싱 오류", "Python 문법으로 읽지 못한 파일입니다."],
];
const SEVERITY = { error: 0, warning: 1, info: 2 } as const;

export function categoryOf(issue: Issue): Category {
  if (issue.kind !== "cycle") return issue.kind;
  if (issue.through_init) return "init_cycle";
  return issue.runtime ? "cycle" : "deferred_cycle";
}

export function IssuesView() {
  const index = useStore((s) => s.index)!;
  const hideTests = useStore((s) => s.hideTests);
  const [query, setQuery] = useState("");
  const [hidden, setHidden] = useState<Set<Category>>(new Set());

  const issues = useMemo(() => {
    const visible = index.graph.issues.filter(
      (i) => !hideTests || !i.nodes.every((id) => index.isTest(id)),
    );
    return visible.sort(
      (a, b) => SEVERITY[a.severity] - SEVERITY[b.severity] || b.nodes.length - a.nodes.length,
    );
  }, [index, hideTests]);
  const counts = useMemo(() => {
    const result = new Map<Category, number>();
    for (const issue of issues) result.set(categoryOf(issue), (result.get(categoryOf(issue)) ?? 0) + 1);
    return result;
  }, [issues]);

  const q = query.trim().toLowerCase();
  const shown = issues.filter(
    (issue) =>
      !hidden.has(categoryOf(issue)) &&
      (!q ||
        issue.message.toLowerCase().includes(q) ||
        issue.nodes.some((id) => index.nodes.get(id)?.qualname.toLowerCase().includes(q))),
  );

  const toggle = (category: Category) => {
    const next = new Set(hidden);
    if (next.has(category)) next.delete(category);
    else next.add(category);
    setHidden(next);
  };

  return (
    <div className="issues-view">
      <div className="overview-bar">
        {CATEGORIES.filter(([c]) => counts.get(c)).map(([category, label, help]) => (
          <button
            key={category}
            className={`chip ${hidden.has(category) ? "" : "on"}`}
            title={help}
            onClick={() => toggle(category)}
          >
            {label} <b>{counts.get(category)}</b>
          </button>
        ))}
        <span className="spacer" />
        <input type="search" placeholder="모듈·메시지로 거르기" value={query} onChange={(e) => setQuery(e.target.value)} />
      </div>
      <div className="issue-list">
        {shown.length === 0 && <p className="empty">{issues.length ? "조건에 맞는 이슈가 없습니다." : "이슈가 없습니다."}</p>}
        {shown.map((issue, i) => (
          <IssueRow key={`${issue.kind}:${issue.nodes[0]}:${issue.line}:${i}`} index={index} issue={issue} />
        ))}
      </div>
    </div>
  );
}

function IssueRow({ index, issue }: { index: GraphIndex; issue: Issue }) {
  const { select, reveal, showPath, openSource } = useStore.getState();
  const [showAll, setShowAll] = useState(false);
  const category = categoryOf(issue);
  const help = CATEGORIES.find(([c]) => c === category)![2];
  const name = (id: string) => index.nodes.get(id)?.qualname ?? id;

  if (issue.kind !== "cycle") {
    const module = issue.nodes[0];
    return (
      <div className={`issue-row ${issue.severity}`}>
        <div className="issue-title">
          <span className={`sev ${issue.severity}`}>{issue.severity}</span>
          {issue.message}
        </div>
        <button
          className="link mono"
          onClick={() => {
            select(module);
            openSource(issue.line ?? null);
          }}
        >
          {name(module)}
          {issue.line ? `:${issue.line}` : ""}
        </button>
      </div>
    );
  }

  const modules = [...issue.nodes].sort((a, b) => name(a).localeCompare(name(b)));
  return (
    <div className={`issue-row ${issue.severity}`}>
      <div className="issue-title">
        <span className={`sev ${issue.severity}`}>{issue.severity}</span>
        {issue.message}
      </div>
      <p className="muted small">{help}</p>
      {(issue.examples ?? []).length > 0 && (
        <>
          <div className="small muted">가장 짧은 순환 예시</div>
          {issue.examples!.map((cycle) => (
            <div key={cycle.join(">")} className="cycle-path">
              {[...cycle, cycle[0]].map((id, i) => (
                <span key={i}>
                  {i > 0 && <span className="arrow">→</span>}
                  <button className="link mono" onClick={() => reveal(id)}>
                    {name(id)}
                  </button>
                </span>
              ))}
              <button className="small-button" onClick={() => showPath(cycle)}>
                그래프에서 보기
              </button>
            </div>
          ))}
        </>
      )}
      <details onToggle={(e) => setShowAll((e.target as HTMLDetailsElement).open)}>
        <summary className="small muted">관련 모듈 {modules.length}개</summary>
        {showAll && (
          <div className="module-chips">
            {modules.map((id) => (
              <button key={id} className="link mono" onClick={() => reveal(id)}>
                {name(id)}
              </button>
            ))}
          </div>
        )}
      </details>
    </div>
  );
}
