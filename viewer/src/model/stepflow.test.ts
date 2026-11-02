import { describe, expect, it } from "vitest";
import type { FlowStep, Graph } from "../types/graph";
import { buildIndex } from "./graphIndex";
import { StepFlow, contextLabel, type FlowNode } from "./stepflow";

const step = (line: number, text: string, extra: Partial<FlowStep> = {}): FlowStep => ({ line, text, ...extra });

const graph: Graph = {
  meta: { schema_version: 1, root: "/r", source_roots: ["."] },
  nodes: [
    { id: "mod:app", kind: "module", name: "app", qualname: "app" },
    { id: "external:httpx", kind: "external", name: "httpx", qualname: "httpx" },
    { id: "stdlib:asyncio", kind: "stdlib", name: "asyncio", qualname: "asyncio" },
    {
      id: "fn:app.search", kind: "function", name: "search", qualname: "app.search", parent: "mod:app",
      flow: {
        sections: [{ line: 2, title: "Step 1. Parse" }],
        steps: [
          step(3, "parse", { targets: ["fn:app.parse"], assigns: ["words"] }),
          step(5, "tidy", { targets: ["fn:app.tidy"] }),
          step(6, "asyncio.gather", { library: "asyncio.gather" }),
          step(7, "lookup", { targets: ["fn:app.lookup"], group: 6 }),
          step(8, "covers", { targets: ["fn:app.covers"], group: 6 }),
          step(10, "audit", { targets: ["fn:app.audit"], background: true }),
          step(12, "note", { targets: ["fn:app.tidy"], context: [{ kind: "if", text: "verbose" }] }),
        ],
        exits: [
          { kind: "return", line: 4, value: "[]", context: [{ kind: "if", text: "not words" }] },
          { kind: "return", line: 13, value: "results" },
        ],
      },
    },
    { id: "fn:app.parse", kind: "function", name: "parse", qualname: "app.parse", parent: "mod:app" },
    { id: "fn:app.tidy", kind: "function", name: "tidy", qualname: "app.tidy", parent: "mod:app" },
    {
      id: "fn:app.lookup", kind: "function", name: "lookup", qualname: "app.lookup", parent: "mod:app",
      flow: { steps: [step(20, "httpx.get", { library: "httpx.get" })] },
    },
    {
      id: "fn:app.covers", kind: "function", name: "covers", qualname: "app.covers", parent: "mod:app",
      flow: { steps: [step(30, "self.client.download")] },
    },
    {
      id: "fn:app.normalize", kind: "function", name: "normalize", qualname: "app.normalize", parent: "mod:app",
      flow: {
        steps: [step(40, "text.casefold")],
        exits: [{ kind: "return", line: 41, value: "''", context: [{ kind: "if", text: "not text" }] }],
      },
    },
    { id: "fn:app.audit", kind: "function", name: "audit", qualname: "app.audit", parent: "mod:app" },
  ],
  edges: [],
  issues: [],
};
const index = buildIndex(graph);

function outline(nodes: FlowNode[]): unknown[] {
  return nodes.map((n) => {
    switch (n.type) {
      case "step":
        return n.step.text + (n.expandable ? "+" : "") + (n.decides ? "?" : "");
      case "exit":
        return `return ${n.exit.value}`;
      case "section":
        return `# ${n.title}`;
      case "folded":
        return `folded(${n.steps.map((s) => s.text).join(",")})`;
      case "block":
        return { [contextLabel(n.context)]: outline(n.children) };
      case "parallel":
        return { parallel: outline(n.lanes) };
    }
  });
}

describe("StepFlow", () => {
  const flow = new StepFlow(index);

  it("decides which functions are worth a step", () => {
    expect(flow.significant("fn:app.lookup")).toBe(true); // third-party call
    expect(flow.significant("fn:app.covers")).toBe(true); // unresolved call
    expect(flow.significant("fn:app.tidy")).toBe(false); // no flow at all
    expect(flow.significant("fn:app.normalize")).toBe(false); // early return and a data call only
    expect(flow.significant("fn:app.search")).toBe(true);
  });

  it("builds the step diagram", () => {
    expect(outline(flow.build("fn:app.search"))).toEqual([
      "# Step 1. Parse",
      "parse?", // its result decides the `if not words` branch below
      { "조건 not words": ["return []"] },
      "folded(tidy)",
      { parallel: ["lookup+", "covers+"] },
      "audit",
      "folded(note)", // a block with only helpers in it folds away
      "return results",
    ]);
  });
});
