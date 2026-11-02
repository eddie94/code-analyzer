import { describe, expect, it } from "vitest";
import type { FlowStep, Graph } from "../types/graph";
import { buildDataFlow, namesIn, receiverClass, type DataRow } from "./dataflow";
import { buildIndex } from "./graphIndex";
import { StepFlow } from "./stepflow";

const step = (line: number, text: string, extra: Partial<FlowStep> = {}): FlowStep => ({ line, text, ...extra });

const steps = [
  step(2, "parse", { targets: ["fn:app.parse"], inputs: ["query"], assigns: ["words", "lang"] }),
  step(5, "log.debug", { inputs: ["query"] }), // result unused, nothing outside: hidden
  step(6, "normalize", { targets: ["fn:app.normalize"], inputs: ["words"], assigns: ["words"] }),
  step(6, "stem", { targets: ["fn:app.normalize"], inputs: ["lang"], nested: true }),
  step(8, "asyncio.gather", { library: "asyncio.gather", assigns: ["hits", "art"] }),
  step(9, "self.shelf.find", {
    targets: ["meth:app.Shelf.find"], inputs: ["words", "limit"], receiver: "self.shelf", group: 8,
  }),
  step(10, "covers", { targets: ["fn:app.covers"], inputs: ["words"], group: 8 }),
];

const graph: Graph = {
  meta: { schema_version: 1, root: "/r", source_roots: ["."] },
  nodes: [
    { id: "mod:app", kind: "module", name: "app", qualname: "app" },
    { id: "external:httpx", kind: "external", name: "httpx", qualname: "httpx" },
    { id: "cls:app.Shelf", kind: "class", name: "Shelf", qualname: "app.Shelf", parent: "mod:app" },
    {
      id: "fn:app.search", kind: "function", name: "search", qualname: "app.search", parent: "mod:app",
      flow: {
        params: ["query", "limit"],
        sections: [{ line: 1, title: "Step 1" }],
        steps,
        exits: [
          { kind: "return", line: 3, value: "[]", context: [{ kind: "if", text: "lang is None and not self.shelf" }] },
          { kind: "return", line: 12, value: "hits, art", inputs: ["hits", "art"] },
        ],
      },
    },
    { id: "fn:app.parse", kind: "function", name: "parse", qualname: "app.parse", parent: "mod:app" },
    { id: "fn:app.normalize", kind: "function", name: "normalize", qualname: "app.normalize", parent: "mod:app" },
    {
      id: "meth:app.Shelf.find", kind: "method", name: "find", qualname: "app.Shelf.find", parent: "cls:app.Shelf",
      flow: { steps: [step(20, "httpx.get", { library: "httpx.get" })] },
    },
    { id: "fn:app.covers", kind: "function", name: "covers", qualname: "app.covers", parent: "mod:app" },
    {
      id: "fn:app.handler", kind: "function", name: "handler", qualname: "app.handler", parent: "mod:app",
      flow: {
        params: ["q"],
        steps: [step(5, "search", { col: 17, targets: ["fn:app.search"], inputs: ["q"] })],
        exits: [{ kind: "return", line: 5, value: "await search(q)" }],
      },
    },
  ],
  edges: [],
  issues: [],
};
const index = buildIndex(graph);

function outline(rows: DataRow[]): unknown[] {
  return rows.map((r) => {
    switch (r.type) {
      case "section":
        return `# ${r.title}`;
      case "exit":
        return `[${r.when}] ⇢ return ${r.exit.value}`;
      case "call":
        return `[${r.receiver ? `${r.receiver}*,` : ""}${r.inputs}] → ${r.step.text} → [${r.outputs}]`;
      case "parallel":
        return { parallel: outline(r.lanes) };
    }
  });
}

describe("buildDataFlow", () => {
  const data = buildDataFlow(index, new StepFlow(index), "fn:app.search")!;

  it("draws values in and out of each call", () => {
    expect(data.params).toEqual(["query", "limit"]);
    expect(outline(data.rows)).toEqual([
      "# Step 1",
      "[query] → parse → [words,lang]",
      "[lang,self.shelf] ⇢ return []", // the variables the condition tests
      "[words] → normalize → [words]", // the nested `stem(...)` call feeds normalize directly
      {
        // gather's results are handed out to its lanes in order
        parallel: ["[self.shelf*,words,limit] → self.shelf.find → [hits]", "[words] → covers → [art]"],
      },
      "[] ⇢ return hits, art",
    ]);
    expect(data.hidden).toBe(1);
  });

  it("puts a return after the call on its own line", () => {
    const handler = buildDataFlow(index, new StepFlow(index), "fn:app.handler")!;
    expect(outline(handler.rows)).toEqual(["[q] → search → []", "[] ⇢ return await search(q)"]);
  });

  it("names the class behind a receiver", () => {
    expect(receiverClass(index, steps[5])).toBe("Shelf");
  });

  it("finds variables in condition text", () => {
    expect(namesIn("not hits or self.shelf.ok and other", new Set(["hits", "self.shelf"]))).toEqual([
      "hits",
      "self.shelf",
    ]);
  });
});
