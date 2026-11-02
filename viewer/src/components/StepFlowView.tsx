import { useMemo, useState } from "react";
import { hasSourceApi } from "../api";
import { shortName } from "../model/flow";
import type { GraphIndex } from "../model/graphIndex";
import { appById, appChain, launchesOf, startupOf } from "../model/startup";
import { contextLabel, StepFlow, type FlowNode } from "../model/stepflow";
import { useStore } from "../store";
import type { FlowStep, Launch } from "../types/graph";

const MAX_DEPTH = 6;

/** The step diagram for a function, with the service start-up above it for routes. */
export function StepFlowView({ root }: { root: string }) {
  const index = useStore((s) => s.index)!;
  const flow = useMemo(() => new StepFlow(index), [index]);
  return (
    <div className="stepflow">
      <StartupPanel index={index} functionId={root} />
      <FunctionFlow index={index} flow={flow} id={root} path={[]} depth={0} />
    </div>
  );
}

function FunctionFlow(props: { index: GraphIndex; flow: StepFlow; id: string; path: string[]; depth: number }) {
  const { index, flow, id, path, depth } = props;
  const nodes = useMemo(() => flow.build(id), [flow, id]);
  if (!index.nodes.get(id)?.flow) return <p className="muted small">이 함수 안에서 따라갈 호출이 없습니다.</p>;
  if (!nodes.length) return <p className="muted small">보조 호출만 있습니다.</p>;
  return (
    <div className="ff">
      {nodes.map((node, i) => (
        <NodeView key={i} {...props} node={node} path={[...path, id]} depth={depth} caller={id} />
      ))}
    </div>
  );
}

interface NodeProps {
  index: GraphIndex;
  flow: StepFlow;
  node: FlowNode;
  path: string[];
  depth: number;
  caller: string;
}

function NodeView(props: NodeProps) {
  const { node } = props;
  switch (node.type) {
    case "section":
      return <div className="ff-section">{node.title}</div>;
    case "exit":
      return (
        <div className={`ff-exit ${node.exit.kind}`}>
          {node.exit.kind === "return" ? "↩ 반환" : "⚠ 예외 발생"}
          {node.exit.value && <code>{node.exit.value}</code>}
          <SourceLink caller={props.caller} line={node.exit.line} />
        </div>
      );
    case "block":
      return (
        <div className={`ff-block ${node.context.kind}`}>
          <div className="ff-block-head">{contextLabel(node.context)}</div>
          {node.children.map((child, i) => (
            <NodeView key={i} {...props} node={child} />
          ))}
        </div>
      );
    case "parallel":
      return (
        <div className="ff-parallel">
          <div className="ff-block-head">동시 실행</div>
          <div className="ff-lanes">
            {node.lanes.map((lane, i) => (
              <div key={i} className="ff-lane">
                <NodeView {...props} node={lane} />
              </div>
            ))}
          </div>
        </div>
      );
    case "folded":
      return <Folded {...props} steps={node.steps} />;
    case "step":
      return <StepCard {...props} step={node.step} expandable={node.expandable} decides={node.decides} />;
  }
}

function StepCard(props: NodeProps & { step: FlowStep; expandable: boolean; decides: boolean }) {
  const { index, flow, step, path, depth, caller } = props;
  const target = step.targets?.[0];
  const recursive = target !== undefined && path.includes(target);
  const canOpen = props.expandable && !recursive && depth < MAX_DEPTH;
  const [open, setOpen] = useState(false);
  const select = useStore((s) => s.select);
  const showFlow = useStore((s) => s.showFlow);
  const selected = useStore((s) => s.selected !== null && s.selected === target);

  const unresolved = !step.targets?.length && !step.library;
  const external = step.library !== undefined && step.library !== null && flow.isExternal(step.library);
  const name = step.targets?.length
    ? step.targets.map((t) => shortName(index, t)).join(" | ")
    : (step.library ?? step.text);

  return (
    <div className={`ff-step${step.background ? " background" : ""}${selected ? " selected" : ""}`}>
      <div className="ff-step-row">
        <button className="twisty" disabled={!canOpen} onClick={() => setOpen(!open)}>
          {canOpen ? (open ? "▾" : "▸") : "·"}
        </button>
        <span
          className={`flow-name${unresolved ? " unresolved" : ""}${external ? " external" : ""}`}
          onClick={() => target && select(target)}
          onDoubleClick={() => target && showFlow(target)}
          title={target ? index.nodes.get(target)?.qualname : step.text}
        >
          {name}
        </span>
        {(step.assigns?.length ?? 0) > 0 && <span className="muted mono small">→ {step.assigns!.join(", ")}</span>}
        {props.decides && (
          <span className="badge decide" title="결과가 아래 분기 조건에 쓰임">
            분기 기준
          </span>
        )}
        {step.background && <span className="badge warn">백그라운드</span>}
        {step.awaited && <span className="badge">await</span>}
        {step.confidence === "inferred" && <span className="badge soft">추론</span>}
        {step.confidence === "candidates" && <span className="badge warn">후보</span>}
        {external && <span className="badge ext">외부 호출</span>}
        {unresolved && <span className="badge warn" title="타입을 몰라 따라가지 못한 호출">추적 불가</span>}
        {recursive && <span className="badge">↺</span>}
        <span className="spacer" />
        <SourceLink caller={caller} line={step.line} />
      </div>
      {open && (
        <div className="ff-nested">
          <FunctionFlow index={index} flow={flow} id={target!} path={path} depth={depth + 1} />
        </div>
      )}
    </div>
  );
}

function Folded(props: NodeProps & { steps: FlowStep[] }) {
  const { index, steps } = props;
  const [open, setOpen] = useState(false);
  const select = useStore((s) => s.select);
  const names = [...new Set(steps.map((s) => (s.targets?.length ? shortName(index, s.targets[0]) : (s.library ?? s.text))))];
  return (
    <div className="ff-folded">
      <button className="link small" onClick={() => setOpen(!open)}>
        {open ? "▾" : "▸"} 보조 호출 {names.length}개
      </button>
      {!open && <span className="muted small mono"> {names.slice(0, 4).join(", ")}{names.length > 4 ? " …" : ""}</span>}
      {open && (
        <div className="module-chips">
          {steps.map((s, i) => (
            <button key={i} className="link mono small" onClick={() => s.targets?.[0] && select(s.targets[0])}>
              {s.targets?.length ? shortName(index, s.targets[0]) : (s.library ?? s.text)}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export function SourceLink({ caller, line }: { caller: string; line: number }) {
  if (!hasSourceApi) return <span className="muted mono small">L{line}</span>;
  return (
    <button
      className="link mono small"
      title="이 줄 보기"
      onClick={() => {
        const { select, openSource } = useStore.getState();
        select(caller);
        openSource(line);
      }}
    >
      L{line}
    </button>
  );
}

/** Launch → app → start-up hooks (and what they set up) → this request. */
export function StartupPanel({ index, functionId }: { index: GraphIndex; functionId: string }) {
  const startup = useMemo(() => startupOf(index, functionId), [index, functionId]);
  const showFlow = useStore((s) => s.showFlow);
  if (!startup) return null;
  const entry = (index.graph.entrypoints ?? []).find((e) => e.target === functionId);
  const outer = startup.apps[startup.apps.length - 1];
  return (
    <div className="startup">
      <div className="startup-lane">
        <div className="startup-box">
          <div className="startup-kind">실행</div>
          {startup.launches.length ? (
            startup.launches.map((l, i) => <LaunchLine key={i} launch={l} />)
          ) : (
            <span className="muted small">실행 명령을 찾지 못함</span>
          )}
        </div>
        <span className="startup-arrow">→</span>
        <div className="startup-box clickable" onClick={() => showFlow(outer.id)}>
          <div className="startup-kind">앱</div>
          {startup.apps
            .slice()
            .reverse()
            .map((a) => (
              <div key={a.id} className="mono small">
                {a.name.split(".").pop()} <span className="muted">({a.kind}, {a.module.slice(4)})</span>
              </div>
            ))}
        </div>
        {startup.hooks.length > 0 && (
          <>
            <span className="startup-arrow">→</span>
            <div className="startup-box">
              <div className="startup-kind">시작할 때</div>
              {startup.hooks.map((h) => (
                <div key={h.target}>
                  <button className="link mono small" onClick={() => showFlow(h.target)}>
                    {shortName(index, h.target)}
                  </button>
                  {(index.graph.state ?? [])
                    .filter((s) => s.writers.includes(h.target))
                    .map((s) => (
                      <div key={s.name} className="mono small muted">
                        {s.name.split(".").pop()} ← {(s.types ?? []).map((t) => shortName(index, t)).join(" | ") || "?"}
                      </div>
                    ))}
                </div>
              ))}
            </div>
          </>
        )}
        <span className="startup-arrow">→</span>
        <div className="startup-box current">
          <div className="startup-kind">요청</div>
          <div className="mono small">{entry?.label}</div>
          <div className="mono small muted">{shortName(index, functionId)}</div>
        </div>
      </div>
      {startup.state.length > 0 && (
        <div className="startup-note small">
          이 요청은 시작할 때 만든 공유 객체를 씁니다:{" "}
          {startup.state.map((s) => (
            <code key={s.name}>
              {s.name.split(".").pop()}
              {s.types?.length ? `: ${s.types.map((t) => shortName(index, t)).join(" | ")}` : ""}
            </code>
          ))}
        </div>
      )}
    </div>
  );
}

function LaunchLine({ launch }: { launch: Launch }) {
  const where = launch.file ? `${launch.file}:${launch.line}` : launch.line ? `L${launch.line}` : "";
  return (
    <div className="launch">
      <code>{launch.label}</code>
      {where && <span className="muted small"> {where}</span>}
    </div>
  );
}

/** An app: how it is started, what runs at start-up, and its routes. */
export function AppView({ appId }: { appId: string }) {
  const index = useStore((s) => s.index)!;
  const showFlow = useStore((s) => s.showFlow);
  const app = appById(index, appId);
  if (!app) return <p className="empty">앱을 찾을 수 없습니다.</p>;
  const chain = appChain(index, appId);
  const mounted = new Set([appId, ...collectIncludes(index, appId)]);
  const entries = (index.graph.entrypoints ?? []).filter((e) => e.app && mounted.has(e.app));
  const launches = launchesOf(index, new Set(chain.map((a) => a.id)));
  return (
    <div className="stepflow">
      <h2 className="app-title">
        {app.name} <span className="kind">{app.kind}</span>
      </h2>
      <h3>실행 방법</h3>
      {launches.length ? launches.map((l, i) => <LaunchLine key={i} launch={l} />) : <p className="muted small">찾지 못함</p>}
      {(["startup", "route"] as const).map((kind) => {
        const list = entries.filter((e) => e.kind === kind);
        if (!list.length) return null;
        return (
          <div key={kind}>
            <h3>{kind === "startup" ? "시작·종료 훅" : `라우트 (${list.length})`}</h3>
            <ul className="list">
              {list.map((e) => (
                <li key={`${e.label}:${e.target}`} onClick={() => showFlow(e.target)}>
                  <span className="name">{e.label}</span>
                  <span className="meta">{shortName(index, e.target)}</span>
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </div>
  );
}

function collectIncludes(index: GraphIndex, appId: string, seen = new Set<string>()): string[] {
  for (const child of appById(index, appId)?.includes ?? []) {
    if (!seen.has(child)) {
      seen.add(child);
      collectIncludes(index, child, seen);
    }
  }
  return [...seen];
}
