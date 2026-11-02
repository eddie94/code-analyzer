import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import type { Graph } from "../types/graph";
import { buildIndex } from "./graphIndex";
import { autoExpand, computeView, markCycles, unitOf, type ViewEdge } from "./view";

// The Python test suite keeps this snapshot in sync with the analyzer.
const graph: Graph = JSON.parse(
  readFileSync(new URL("../../../tests/snapshots/shop.json", import.meta.url), "utf8"),
);
const index = buildIndex(graph);
const base = { showExternal: false, showWeak: true };

describe("unitOf", () => {
  it("folds modules into their outermost collapsed package", () => {
    const options = { ...base, expanded: new Set(["pkg:shop"]) };
    expect(unitOf(index, "mod:shop.services.billing", options)).toBe("pkg:shop.services");
    expect(unitOf(index, "mod:shop.models", options)).toBe("mod:shop.models");
    expect(unitOf(index, "mod:plugins.fancy", options)).toBe("pkg:plugins");
  });

  it("hides libraries unless asked", () => {
    const expanded = new Set<string>();
    expect(unitOf(index, "external:requests", { ...base, expanded })).toBeNull();
    expect(unitOf(index, "external:requests", { ...base, expanded, showExternal: true })).toBe("external:requests");
  });
});

describe("computeView", () => {
  it("shows top-level packages when nothing is expanded", () => {
    const view = computeView(index, { ...base, expanded: new Set() });
    expect(view.units).toEqual(["pkg:plugins", "pkg:shop", "pkg:tests"]);
    expect(view.compounds).toEqual([]);
    const pairs = view.edges.map((e) => [e.source, e.target]);
    expect(pairs).toContainEqual(["pkg:plugins", "pkg:shop"]);
    expect(pairs).toContainEqual(["pkg:tests", "pkg:shop"]);
  });

  it("turns expanded packages into compounds and aggregates edges", () => {
    const view = computeView(index, { ...base, expanded: new Set(["pkg:shop"]) });
    expect(view.compounds).toEqual(["pkg:shop"]);
    expect(view.units).toContain("pkg:shop.services");
    expect(view.units).toContain("mod:shop.cycle_a");
    const cycle = view.edges.filter((e) => e.cyclic).map((e) => e.source).sort();
    expect(cycle).toEqual(["mod:shop.cycle_a", "mod:shop.cycle_b"]);
    const typeOnly = view.edges.find((e) => e.source === "mod:shop.models" && e.target === "pkg:shop.services");
    expect(typeOnly?.weak).toBe(true);
  });

  it("can drop type-only and lazy imports", () => {
    const view = computeView(index, { ...base, showWeak: false, expanded: new Set(["pkg:shop", "pkg:shop.services"]) });
    expect(view.edges.some((e) => e.weak)).toBe(false);
  });
});

describe("markCycles", () => {
  const edge = (source: string, target: string, weak = false): ViewEdge =>
    ({ source, target, weak, count: 1, cyclic: false });

  it("ignores weak edges and finds longer cycles", () => {
    const edges = [edge("a", "b"), edge("b", "c"), edge("c", "a"), edge("c", "d"), edge("d", "c", true)];
    markCycles(edges);
    expect(edges.map((e) => e.cyclic)).toEqual([true, true, true, false, false]);
  });
});

describe("autoExpand", () => {
  it("expands while the view stays small", () => {
    expect([...autoExpand(index, base)].sort()).toEqual([
      "pkg:plugins", "pkg:shop", "pkg:shop.services", "pkg:tests",
    ]);
    expect([...autoExpand(index, base, 4)].sort()).toEqual(["pkg:plugins", "pkg:shop", "pkg:tests"]);
  });
});
