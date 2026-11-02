import type { FlowContext, FlowExit, FlowStep } from "../types/graph";
import { isLibrary, type GraphIndex } from "./graphIndex";

/**
 * A function body as a step diagram: calls in source order, nested under the
 * conditions, loops, `except` and `with` blocks that surround them, concurrent
 * calls side by side, and calls into plain helpers folded away.
 */
export type FlowNode =
  | { type: "step"; step: FlowStep; expandable: boolean; decides: boolean }
  | { type: "exit"; exit: FlowExit }
  | { type: "block"; context: FlowContext; children: FlowNode[] }
  | { type: "parallel"; line: number; lanes: FlowNode[] }
  | { type: "section"; title: string; line: number }
  | { type: "folded"; steps: FlowStep[] };

/** asyncio and friends: drawn as structure (parallel, background), not as steps. */
/** Method names that usually reach outside the process: LLMs, HTTP, databases, queues. */
const IO_VERBS = new Set([
  "invoke", "ainvoke", "stream", "astream", "batch", "abatch", "create", "acreate", "generate",
  "agenerate", "predict", "apredict", "complete", "chat", "request", "post", "put", "patch",
  "delete", "send", "fetch", "query", "execute", "publish", "upload", "download",
]);

export const STRUCTURAL = new Set(["asyncio.gather", "asyncio.wait", "asyncio.as_completed", "asyncio.create_task", "asyncio.ensure_future"]);

export class StepFlow {
  private significance = new Map<string, boolean>();

  constructor(private readonly index: GraphIndex) {}

  /**
   * A function is worth showing as a step of its own when something happens in it:
   * a step heading, concurrency, a third-party call, an unresolved call that looks
   * like I/O, or a call into another such function.
   */
  significant(id: string): boolean {
    const known = this.significance.get(id);
    if (known !== undefined) return known;
    this.significance.set(id, false); // recursion: assume plain until shown otherwise
    const flow = this.index.nodes.get(id)?.flow;
    let result = false;
    if (flow) {
      result = (flow.sections?.length ?? 0) > 0 || (flow.steps ?? []).some((s) => this.stepSignificant(s));
    }
    this.significance.set(id, result);
    return result;
  }

  stepSignificant(step: FlowStep): boolean {
    if (step.background || step.group != null) return true;
    if (step.library) return this.isExternal(step.library);
    if (!step.targets?.length) return isIoCall(step.text); // unresolved: maybe an LLM or HTTP call
    return step.targets.some((t) => this.significant(t));
  }

  isExternal(library: string): boolean {
    const node = this.index.nodes.get(`external:${library.split(".")[0]}`);
    return node !== undefined && isLibrary(node);
  }

  /** The diagram for one function. */
  build(id: string): FlowNode[] {
    const flow = this.index.nodes.get(id)?.flow;
    if (!flow) return [];
    // Conditions written after each line, to spot calls whose result decides a branch.
    const conditions = [
      ...(flow.steps ?? []).flatMap((s) => (s.context ?? []).map((c) => ({ line: s.line, c }))),
      ...(flow.exits ?? []).flatMap((e) => (e.context ?? []).map((c) => ({ line: e.line, c }))),
    ].filter(({ c }) => c.kind !== "with" && c.kind !== "except");
    const decides = (step: FlowStep) =>
      (step.assigns ?? []).some((name) => {
        const word = new RegExp(`\\b${name}\\b`);
        return conditions.some(({ line, c }) => line > step.line && word.test(c.text));
      });

    type Item = { line: number; col: number; context: FlowContext[]; node: FlowNode };
    const items: Item[] = [
      ...(flow.steps ?? []).map((step) => ({
        line: step.line,
        col: step.col ?? 0,
        context: step.context ?? [],
        node: { type: "step", step, expandable: this.expandable(step), decides: decides(step) } as FlowNode,
      })),
      ...(flow.exits ?? []).map((exit) => ({
        line: exit.line,
        col: 1e9, // after the calls on its line
        context: exit.context ?? [],
        node: { type: "exit", exit } as FlowNode,
      })),
      ...(flow.sections ?? []).map((s) => ({
        line: s.line,
        col: -1,
        context: [],
        node: { type: "section", title: s.title, line: s.line } as FlowNode,
      })),
    ].sort((a, b) => a.line - b.line || a.col - b.col);

    // Nest items under their contexts, opening and closing blocks as the context changes.
    const root: FlowNode[] = [];
    const stack: { context: FlowContext | null; children: FlowNode[] }[] = [{ context: null, children: root }];
    for (const item of items) {
      let depth = 0;
      while (
        depth < item.context.length &&
        depth + 1 < stack.length &&
        sameContext(stack[depth + 1].context!, item.context[depth])
      ) {
        depth++;
      }
      stack.length = depth + 1;
      for (const context of item.context.slice(depth)) {
        const block: FlowNode = { type: "block", context, children: [] };
        stack[stack.length - 1].children.push(block);
        stack.push({ context, children: block.children });
      }
      stack[stack.length - 1].children.push(item.node);
    }
    return this.tidy(root);
  }

  private expandable(step: FlowStep): boolean {
    return (step.targets ?? []).some((t) => this.significant(t));
  }

  /** Group concurrent steps, fold plain helpers, drop blocks with nothing left to show. */
  private tidy(nodes: FlowNode[]): FlowNode[] {
    const grouped: FlowNode[] = [];
    const lanes = new Map<number, FlowNode[]>();
    for (const node of nodes) {
      if (node.type === "block") {
        grouped.push({ ...node, children: this.tidy(node.children) });
      } else if (node.type === "step" && node.step.group != null) {
        let lane = lanes.get(node.step.group);
        if (!lane) {
          lane = [];
          lanes.set(node.step.group, lane);
          grouped.push({ type: "parallel", line: node.step.group, lanes: lane });
        }
        lane.push(node);
      } else if (node.type === "step" && node.step.library && STRUCTURAL.has(node.step.library) && !node.step.background) {
        continue; // the gather/create_task call itself; its arguments carry the meaning
      } else {
        grouped.push(node);
      }
    }

    const result: FlowNode[] = [];
    for (const node of grouped) {
      const shown = this.shown(node);
      if (!shown) {
        const steps = collectSteps(node);
        const last = result[result.length - 1];
        if (last?.type === "folded") last.steps.push(...steps);
        else if (steps.length) result.push({ type: "folded", steps });
        continue;
      }
      result.push(node);
    }
    return result;
  }

  private shown(node: FlowNode): boolean {
    switch (node.type) {
      case "step":
        return node.decides || this.stepSignificant(node.step);
      case "block":
        return node.children.some((c) => c.type !== "folded");
      default:
        return true;
    }
  }
}

function isIoCall(text: string): boolean {
  return IO_VERBS.has(text.split(".").pop() ?? "");
}

function sameContext(a: FlowContext, b: FlowContext): boolean {
  return a.kind === b.kind && a.text === b.text;
}

function collectSteps(node: FlowNode): FlowStep[] {
  switch (node.type) {
    case "step":
      return [node.step];
    case "block":
      return node.children.flatMap(collectSteps);
    case "folded":
      return node.steps;
    case "parallel":
      return node.lanes.flatMap(collectSteps);
    default:
      return [];
  }
}

/** How a context reads as a block header. */
export function contextLabel(context: FlowContext): string {
  switch (context.kind) {
    case "if":
      return `조건 ${context.text}`;
    case "else":
      return `조건 ${context.text} 이 아니면`;
    case "loop":
      return `반복 ${context.text}`;
    case "except":
      return `예외 처리 ${context.text}`;
    case "with":
      return context.text;
    case "case":
      return `case ${context.text}`;
  }
}
