import type { FlowContext, FlowExit, FlowStep } from "../types/graph";
import type { GraphIndex } from "./graphIndex";
import { STRUCTURAL, type StepFlow } from "./stepflow";

/**
 * A function body as values flowing through calls: each row is one call with the
 * variables it reads on the left and the variables it assigns on the right. Exits
 * show the variables their condition tests. Everything comes from the syntax alone:
 * parameters, assignments, call arguments, `return`/`raise` and their `if`s.
 */
export interface CallRow {
  type: "call";
  step: FlowStep;
  inputs: string[];
  outputs: string[];
  receiver: string | null;
  conditions: FlowContext[];
  expandable: boolean;
}

export type DataRow =
  | CallRow
  | { type: "parallel"; line: number; lanes: CallRow[]; conditions: FlowContext[] }
  | { type: "exit"; exit: FlowExit; when: string[]; conditions: FlowContext[] }
  | { type: "section"; line: number; title: string };

export interface DataFlow {
  params: string[];
  rows: DataRow[];
  /** Calls left out: their result is not kept and nothing outside is reached. */
  hidden: number;
}

const BRANCHES = new Set(["if", "else", "case"]);

export function buildDataFlow(index: GraphIndex, steps: StepFlow, id: string): DataFlow | null {
  const flow = index.nodes.get(id)?.flow;
  if (!flow) return null;
  const all = flow.steps ?? [];
  const variables = new Set([
    ...(flow.params ?? []),
    ...all.flatMap((s) => [...(s.assigns ?? []), ...(s.inputs ?? []), ...(s.receiver ? [s.receiver] : [])]),
    ...(flow.exits ?? []).flatMap((e) => e.inputs ?? []),
  ]);
  variables.delete("_");

  // `a, b = await gather(f(), g())`: a comes from f, b from g.
  const laneOutputs = new Map<FlowStep, string[]>();
  for (const outer of all) {
    if (!outer.library || !STRUCTURAL.has(outer.library) || !outer.assigns?.length) continue;
    const lanes = all.filter((s) => s.group === outer.line);
    if (lanes.length === outer.assigns.length) lanes.forEach((s, i) => laneOutputs.set(s, [outer.assigns![i]]));
  }

  let hidden = 0;
  type Item = { line: number; col: number; row: DataRow; group?: number };
  const items: Item[] = [];
  for (const step of all) {
    if (step.nested) continue; // its result feeds the call it is an argument of
    if (step.library && STRUCTURAL.has(step.library)) continue; // drawn as the lanes it runs
    const outputs = (laneOutputs.get(step) ?? step.assigns ?? []).filter((n) => n !== "_");
    const keep = outputs.length > 0 || step.group != null || step.background || steps.stepSignificant(step);
    if (!keep) {
      hidden++;
      continue;
    }
    const target = step.targets?.[0];
    const row: CallRow = {
      type: "call",
      step,
      inputs: (step.inputs ?? []).filter((n) => n !== step.receiver),
      outputs,
      receiver: step.receiver ?? null,
      conditions: step.context ?? [],
      expandable: target !== undefined && index.nodes.get(target)?.flow != null,
    };
    items.push({ line: step.line, col: step.col ?? 0, row, group: step.group ?? undefined });
  }
  for (const exit of flow.exits ?? []) {
    const conditions = exit.context ?? [];
    const tested = conditions.filter((c) => BRANCHES.has(c.kind)).map((c) => c.text);
    items.push({
      line: exit.line,
      col: 0,
      row: { type: "exit", exit, when: namesIn(tested.join(" "), variables), conditions },
    });
  }
  for (const s of flow.sections ?? []) {
    items.push({ line: s.line, col: -1, row: { type: "section", line: s.line, title: s.title } });
  }
  items.sort((a, b) => a.line - b.line || a.col - b.col);

  const rows: DataRow[] = [];
  const parallel = new Map<number, CallRow[]>();
  for (const item of items) {
    if (item.group === undefined || item.row.type !== "call") {
      rows.push(item.row);
      continue;
    }
    let lanes = parallel.get(item.group);
    if (!lanes) {
      lanes = [];
      parallel.set(item.group, lanes);
      rows.push({ type: "parallel", line: item.group, lanes, conditions: item.row.conditions });
    }
    lanes.push(item.row);
  }
  return { params: flow.params ?? [], rows, hidden };
}

/** Variables (from `known`) a piece of source text mentions, in order. */
export function namesIn(text: string, known: Set<string>): string[] {
  const found: string[] = [];
  for (const match of text.matchAll(/\b(self\.\w+|[A-Za-z_]\w*)/g)) {
    const name = match[1];
    if (known.has(name) && !found.includes(name)) found.push(name);
  }
  return found;
}

/** The class a receiver variable holds, from the method the call resolved to. */
export function receiverClass(index: GraphIndex, step: FlowStep): string | null {
  const target = step.targets?.[0];
  const parent = target ? index.nodes.get(target)?.parent : undefined;
  const node = parent ? index.nodes.get(parent) : undefined;
  return node?.kind === "class" ? node.name : null;
}
