import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import type { Graph } from "../types/graph";
import { classCounts, classLabel, classView, scopeFor } from "./classes";
import { buildIndex } from "./graphIndex";

const graph: Graph = JSON.parse(
  readFileSync(new URL("../../../tests/snapshots/shop.json", import.meta.url), "utf8"),
);
const index = buildIndex(graph);
const ids = (nodes: { id: string }[]) => nodes.map((n) => n.id).sort();

describe("scopeFor", () => {
  it("walks up to the nearest module or package", () => {
    expect(scopeFor(index, "meth:shop.services.billing.Invoice.pay")).toBe("mod:shop.services.billing");
    expect(scopeFor(index, "pkg:shop")).toBe("pkg:shop");
    expect(scopeFor(index, null)).toBeNull();
  });
});

describe("classView", () => {
  it("shows every class for the whole repository", () => {
    const view = classView(index, null, { onlyLinked: false, hideTests: false });
    expect(ids(view.classes)).toEqual([
      "cls:plugins.fancy.FancyOrder",
      "cls:shop.models.Base",
      "cls:shop.models.Order",
      "cls:shop.services.billing.Invoice",
    ]);
    expect(view.outside).toEqual([]);
    expect(view.edges).toHaveLength(2);
  });

  it("adds related classes from outside the scope", () => {
    const view = classView(index, "pkg:plugins", { onlyLinked: false, hideTests: false });
    expect(ids(view.classes)).toEqual(["cls:plugins.fancy.FancyOrder"]);
    expect(ids(view.outside)).toEqual(["cls:shop.models.Order"]);
  });

  it("can keep only classes with inheritance links", () => {
    const view = classView(index, "pkg:shop", { onlyLinked: true, hideTests: false });
    expect(ids(view.classes)).toEqual(["cls:shop.models.Base", "cls:shop.models.Order"]);
    expect(view.total).toBe(3);
    expect(ids(view.outside)).toEqual(["cls:plugins.fancy.FancyOrder"]);
  });
});

describe("classLabel", () => {
  it("lists members under the class name", () => {
    expect(classLabel(index, index.nodes.get("cls:shop.services.billing.Invoice")!)).toBe(
      "Invoice\n__init__()\npay()",
    );
    expect(classLabel(index, index.nodes.get("cls:shop.services.billing.Invoice")!, 1)).toBe(
      "Invoice\n__init__()\n… +1",
    );
  });
});

describe("classCounts", () => {
  it("counts classes per module and package", () => {
    const counts = classCounts(index, false);
    expect(counts.get("pkg:shop")).toBe(3);
    expect(counts.get("mod:shop.models")).toBe(2);
    expect(counts.get("pkg:plugins")).toBe(1);
  });
});
