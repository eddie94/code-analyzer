import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import type { Graph } from "../types/graph";
import { buildIndex } from "./graphIndex";
import { buildTree, colorScale, issueCounts, layoutTree, ramp } from "./treemap";

const graph: Graph = JSON.parse(
  readFileSync(new URL("../../../tests/snapshots/shop.json", import.meta.url), "utf8"),
);
const index = buildIndex(graph);

describe("buildTree", () => {
  it("nests packages and modules", () => {
    const tree = buildTree(index, false);
    expect(tree.children!.map((c) => c.id)).toEqual(["pkg:plugins", "pkg:shop", "pkg:tests"]);
    const shop = tree.children!.find((c) => c.id === "pkg:shop")!;
    expect(shop.children!.map((c) => c.id)).toContain("pkg:shop.services");
    expect(shop.children!.map((c) => c.id)).toContain("mod:shop.models");
  });

  it("drops test-only packages when asked", () => {
    const tree = buildTree(index, true);
    expect(tree.children!.map((c) => c.id)).toEqual(["pkg:plugins", "pkg:shop"]);
  });
});

describe("layoutTree", () => {
  it("fits every tile inside the box", () => {
    const root = layoutTree(buildTree(index, false), 800, 600);
    for (const d of root.descendants()) {
      expect(d.x0).toBeGreaterThanOrEqual(0);
      expect(d.y1).toBeLessThanOrEqual(600);
    }
    const models = root.descendants().find((d) => d.data.id === "mod:shop.models")!;
    const empty = root.descendants().find((d) => d.data.id === "mod:shop.services")!;
    // models has more code than the empty services/__init__.py
    expect((models.x1 - models.x0) * (models.y1 - models.y0)).toBeGreaterThan(
      (empty.x1 - empty.x0) * (empty.y1 - empty.y0),
    );
  });
});

describe("colors", () => {
  it("ramps from blue to red", () => {
    expect(ramp(0)).toBe("rgb(40, 75, 110)");
    expect(ramp(1)).toBe("rgb(229, 83, 75)");
    expect(ramp(2)).toBe(ramp(1));
  });

  it("counts issues per module", () => {
    const counts = issueCounts(index);
    expect(counts.get("mod:shop.bad_import")).toBe(3);
    const scale = colorScale(index, "issues", counts);
    expect(scale.max).toBe(3);
    expect(scale.color(index.nodes.get("mod:shop.bad_import")!)).toBe(ramp(1));
  });
});
