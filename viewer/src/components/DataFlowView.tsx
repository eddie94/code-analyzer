import { createContext, useContext, useMemo, useState } from "react";
import { buildDataFlow, receiverClass, type CallRow, type DataRow } from "../model/dataflow";
import { shortName } from "../model/flow";
import type { GraphIndex } from "../model/graphIndex";
import { contextLabel, StepFlow } from "../model/stepflow";
import { useStore } from "../store";
import type { FlowContext } from "../types/graph";
import { SourceLink, StartupPanel } from "./StepFlowView";

const MAX_DEPTH = 6;

/** The variable under the pointer (or pinned by a click), lit up wherever it appears. */
const Focus = createContext<{ name: string | null; hover: (n: string | null) => void; pin: (n: string) => void }>({
  name: null,
  hover: () => {},
  pin: () => {},
});

/** Values flowing through calls, for a function and (on demand) the functions it calls. */
export function DataFlowView({ root }: { root: string }) {
  const index = useStore((s) => s.index)!;
  const steps = useMemo(() => new StepFlow(index), [index]);
  const [hovered, setHovered] = useState<string | null>(null);
  const [pinned, setPinned] = useState<string | null>(null);
  const focus = useMemo(
    () => ({
      name: hovered ?? pinned,
      hover: setHovered,
      pin: (n: string) => setPinned((p) => (p === n ? null : n)),
    }),
    [hovered, pinned],
  );
  return (
    <Focus.Provider value={focus}>
      <div className="stepflow">
        <StartupPanel index={index} functionId={root} />
        <FunctionData index={index} steps={steps} id={root} path={[]} />
      </div>
    </Focus.Provider>
  );
}

interface Props {
  index: GraphIndex;
  steps: StepFlow;
  id: string;
  path: string[];
}

function FunctionData({ index, steps, id, path }: Props) {
  const data = useMemo(() => buildDataFlow(index, steps, id), [index, steps, id]);
  if (!data) return <p className="muted small">이 함수 안에서 따라갈 호출이 없습니다.</p>;
  const inner = { index, steps, id, path: [...path, id] };
  return (
    <div className="df">
      {data.params.length > 0 && (
        <div className="df-params">
          <span className="df-label">입력</span>
          {data.params.map((p) => (
            <Value key={p} name={p} />
          ))}
        </div>
      )}
      {data.rows.map((row, i) => (
        <RowView key={i} {...inner} row={row} />
      ))}
      {data.rows.length === 0 && <p className="muted small">값을 남기거나 바깥을 부르는 호출이 없습니다.</p>}
      {data.hidden > 0 && <p className="muted small">결과를 쓰지 않는 보조 호출 {data.hidden}개는 생략</p>}
    </div>
  );
}

function RowView(props: Props & { row: DataRow }) {
  const { row } = props;
  switch (row.type) {
    case "section":
      return <div className="ff-section">{row.title}</div>;
    case "parallel":
      return (
        <div className="df-parallel">
          <div className="ff-block-head">
            동시 실행 <Conditions conditions={row.conditions} />
          </div>
          {row.lanes.map((lane, i) => (
            <CallView key={i} {...props} row={lane} inLane />
          ))}
        </div>
      );
    case "exit":
      return (
        <div className="df-row">
          <div className="df-in">
            {row.when.map((n) => (
              <Value key={n} name={n} dashed />
            ))}
          </div>
          <span className="df-arrow">{row.when.length ? "⇢" : ""}</span>
          <div className={`df-exit ${row.exit.kind}`}>
            <Conditions conditions={row.conditions} />
            <div className="df-exit-main">
              {row.exit.kind === "return" ? "↩ 반환" : "⚠ 예외"}
              {row.exit.value && <code>{row.exit.value}</code>}
              <span className="spacer" />
              <SourceLink caller={props.id} line={row.exit.line} />
            </div>
          </div>
        </div>
      );
    case "call":
      return <CallView {...props} row={row} />;
  }
}

function CallView(props: Props & { row: CallRow; inLane?: boolean }) {
  const { index, steps, row, id, path } = props;
  const { step } = row;
  const target = step.targets?.[0];
  const recursive = target !== undefined && path.includes(target);
  const canOpen = row.expandable && !recursive && path.length < MAX_DEPTH;
  const [open, setOpen] = useState(false);
  const select = useStore((s) => s.select);
  const showFlow = useStore((s) => s.showFlow);
  const external = step.library != null && steps.isExternal(step.library);
  const reachesOut = !external && target !== undefined && steps.significant(target);
  // A method of the class being read reads better without the class name.
  const owner = index.nodes.get(id)?.parent;
  const name = step.targets?.length
    ? step.targets
        .map((t) => (index.nodes.get(t)?.parent === owner ? index.nodes.get(t)!.name : shortName(index, t)))
        .join(" | ")
    : (step.library ?? step.text);
  const cls = receiverClass(index, step);

  return (
    <div className="df-call">
      <div className="df-row">
        <div className="df-in">
          {row.receiver && <Value name={row.receiver} type={cls} object />}
          {row.inputs.map((n) => (
            <Value key={n} name={n} />
          ))}
        </div>
        <span className="df-arrow">{row.receiver || row.inputs.length ? "→" : ""}</span>
        <div className={`df-fn${step.background ? " background" : ""}${!step.targets?.length && !step.library ? " unresolved" : ""}`}>
          <Conditions conditions={props.inLane ? [] : row.conditions} />
          <div className="df-fn-main">
            <button className="twisty" disabled={!canOpen} onClick={() => setOpen(!open)}>
              {canOpen ? (open ? "▾" : "▸") : "·"}
            </button>
            <span
              className="flow-name"
              onClick={() => target && select(target)}
              onDoubleClick={() => target && showFlow(target)}
              title={target ? index.nodes.get(target)?.qualname : step.text}
            >
              {breakable(name)}
            </span>
            <SourceLink caller={id} line={step.line} />
          </div>
          <div className="df-tags">
            {step.background && <span className="badge warn">백그라운드</span>}
            {external && <span className="badge ext">외부 패키지 {step.library!.split(".")[0]}</span>}
            {reachesOut && <span className="badge ext" title="안쪽을 따라가면 외부 패키지를 부름">외부 호출 포함</span>}
            {!step.targets?.length && !step.library && (
              <span className="badge warn" title="타입을 몰라 따라가지 못한 호출">추적 불가</span>
            )}
            {recursive && <span className="badge">↺</span>}
          </div>
        </div>
        <span className="df-arrow">{row.outputs.length ? "→" : ""}</span>
        <div className="df-out">
          {row.outputs.map((n) => (
            <Value key={n} name={n} />
          ))}
        </div>
      </div>
      {open && (
        <div className="ff-nested">
          <FunctionData index={index} steps={steps} id={target!} path={path} />
        </div>
      )}
    </div>
  );
}

function Value({ name, type, object, dashed }: { name: string; type?: string | null; object?: boolean; dashed?: boolean }) {
  const focus = useContext(Focus);
  const lit = focus.name === name;
  object = object || name.startsWith("self."); // instance state rather than a local value
  return (
    <span
      className={`df-value${object ? " object" : ""}${dashed ? " dashed" : ""}${lit ? " lit" : ""}`}
      onMouseEnter={() => focus.hover(name)}
      onMouseLeave={() => focus.hover(null)}
      onClick={() => focus.pin(name)}
      title={type ? `${name}: ${type}` : name}
    >
      {name}
      {type && <span className="df-type">: {type}</span>}
    </span>
  );
}

/** Lets a long dotted or snake_case name wrap after `.` and `_` rather than mid-word. */
function breakable(name: string) {
  return name.split(/(?<=[._])/).map((part, i) => (
    <span key={i}>
      {part}
      <wbr />
    </span>
  ));
}

function Conditions({ conditions }: { conditions: FlowContext[] }) {
  const shown = conditions.filter((c) => c.kind !== "with");
  if (!shown.length) return null;
  return <div className="df-cond">{shown.map(contextLabel).join(" › ")}</div>;
}
