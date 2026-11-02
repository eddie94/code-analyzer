import { describe, expect, it } from "vitest";
import type { Graph } from "../types/graph";
import { flowChildren, reachingEntrypoints, shortName } from "./flow";
import { buildIndex } from "./graphIndex";

const graph: Graph = {
  meta: { schema_version: 1, root: "/r", source_roots: ["."] },
  nodes: [
    { id: "mod:app", kind: "module", name: "app", qualname: "app" },
    { id: "fn:app.find_books", kind: "function", name: "find_books", qualname: "app.find_books", parent: "mod:app" },
    { id: "fn:app.loop", kind: "function", name: "loop", qualname: "app.loop", parent: "mod:app" },
    { id: "cls:app.Engine", kind: "class", name: "Engine", qualname: "app.Engine", parent: "mod:app" },
    {
      id: "meth:app.Engine.run", kind: "method", name: "run", qualname: "app.Engine.run",
      parent: "cls:app.Engine", unresolved_calls: ["self.client.fetch_all"],
    },
    { id: "stdlib:asyncio", kind: "stdlib", name: "asyncio", qualname: "asyncio" },
  ],
  edges: [
    { source: "fn:app.find_books", target: "stdlib:asyncio", kind: "calls", line: 3, names: ["asyncio.gather"] },
    { source: "fn:app.find_books", target: "meth:app.Engine.run", kind: "calls", line: 5, confidence: "inferred" },
    { source: "fn:app.find_books", target: "fn:app.loop", kind: "calls", line: 2 },
    { source: "fn:app.loop", target: "fn:app.loop", kind: "calls", line: 9 },
    { source: "fn:app.find_books", target: "mod:app", kind: "imports" },
  ],
  issues: [],
  entrypoints: [{ kind: "route", label: "GET /books", target: "fn:app.find_books" }],
};
const index = buildIndex(graph);

describe("flowChildren", () => {
  it("lists calls in source order with libraries folded", () => {
    const children = flowChildren(index, "fn:app.find_books", [], { showLibraries: true });
    expect(children.map((c) => (c.kind === "call" ? c.edge.target : c.kind))).toEqual([
      "fn:app.loop",
      "meth:app.Engine.run",
      "libraries",
    ]);
    expect(children[2]).toEqual({ kind: "libraries", names: ["asyncio.gather"] });
    expect(flowChildren(index, "fn:app.find_books", [], { showLibraries: false })).toHaveLength(2);
  });

  it("marks recursion and keeps unresolved calls", () => {
    const [loop] = flowChildren(index, "fn:app.loop", ["fn:app.find_books"], { showLibraries: true });
    expect(loop).toMatchObject({ kind: "call", recursive: true });
    expect(flowChildren(index, "meth:app.Engine.run", [], { showLibraries: true })).toEqual([
      { kind: "unresolved", texts: ["self.client.fetch_all"] },
    ]);
  });
});

describe("reachingEntrypoints", () => {
  it("walks callers back to entry points", () => {
    expect(reachingEntrypoints(index, "meth:app.Engine.run").map((e) => e.label)).toEqual(["GET /books"]);
    expect(reachingEntrypoints(index, "fn:app.find_books").map((e) => e.label)).toEqual(["GET /books"]);
  });
});

describe("shortName", () => {
  it("drops the module and marks classes", () => {
    expect(shortName(index, "meth:app.Engine.run")).toBe("Engine.run");
    expect(shortName(index, "cls:app.Engine")).toBe("Engine()");
  });
});
