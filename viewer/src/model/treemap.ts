import { hierarchy, treemap, type HierarchyRectangularNode } from "d3-hierarchy";
import type { Node } from "../types/graph";
import type { GraphIndex } from "./graphIndex";

export type ColorMetric = "complexity" | "hotspot" | "churn" | "instability" | "issues" | "group";

export interface TreeDatum {
  id: string;
  children?: TreeDatum[];
  loc: number;
}

export const PACKAGE_HEADER = 18;

/** Package/module tree sized by lines of code; empty packages are dropped. */
export function buildTree(index: GraphIndex, hideTests: boolean): TreeDatum {
  const build = (node: Node): TreeDatum | null => {
    if (hideTests && index.isTest(node.id)) return null;
    if (node.kind === "module") return { id: node.id, loc: Math.max(1, node.metrics?.loc ?? 0) };
    const children = (index.children.get(node.id) ?? [])
      .filter((c) => c.kind === "package" || c.kind === "module")
      .map(build)
      .filter((c): c is TreeDatum => c !== null);
    return children.length ? { id: node.id, children, loc: 0 } : null;
  };
  const tops = index.graph.nodes.filter((n) => !n.parent && (n.kind === "package" || n.kind === "module"));
  return { id: "", loc: 0, children: tops.map(build).filter((c): c is TreeDatum => c !== null) };
}

export function layoutTree(tree: TreeDatum, width: number, height: number): HierarchyRectangularNode<TreeDatum> {
  const root = hierarchy(tree)
    .sum((d) => (d.children ? 0 : d.loc))
    .sort((a, b) => (b.value ?? 0) - (a.value ?? 0));
  return treemap<TreeDatum>()
    .size([width, height])
    .paddingOuter(3)
    .paddingTop((d) => (d.depth === 0 ? 3 : PACKAGE_HEADER))
    .paddingInner(2)
    .round(true)(root);
}

/** Issue count per node, counting each issue once for every module it names. */
export function issueCounts(index: GraphIndex): Map<string, number> {
  const counts = new Map<string, number>();
  for (const issue of index.graph.issues) {
    for (const id of new Set(issue.nodes)) counts.set(id, (counts.get(id) ?? 0) + 1);
  }
  return counts;
}

export interface Scale {
  max: number;
  value(node: Node): number | null;
  color(node: Node): string;
  label: string;
}

const STOPS = [
  [40, 75, 110],
  [201, 162, 39],
  [229, 83, 75],
];

/** 0..1 onto a blue -> amber -> red ramp. */
export function ramp(t: number): string {
  const x = Math.min(1, Math.max(0, t)) * (STOPS.length - 1);
  const i = Math.min(STOPS.length - 2, Math.floor(x));
  const f = x - i;
  const [r, g, b] = STOPS[i].map((c, k) => Math.round(c + (STOPS[i + 1][k] - c) * f));
  return `rgb(${r}, ${g}, ${b})`;
}

export function colorScale(index: GraphIndex, metric: ColorMetric, issues: Map<string, number>): Scale {
  const modules = index.modules;
  if (metric === "group") {
    return { max: 0, label: "패키지별 색", value: () => null, color: (n) => index.color(n) };
  }
  if (metric === "instability") {
    const value = (n: Node) => n.metrics?.instability ?? null;
    return { max: 1, label: "불안정성", value, color: (n) => colorOf(value(n), 1) };
  }
  if (metric === "issues") {
    const value = (n: Node) => issues.get(n.id) ?? 0;
    const max = Math.max(1, ...modules.map(value));
    return { max, label: "이슈 수", value, color: (n) => colorOf(value(n), max) };
  }
  const [label, value, floor]: [string, (n: Node) => number | null, number] =
    metric === "hotspot"
      ? ["핫스팟", (n) => n.metrics?.hotspot ?? null, 1]
      : metric === "churn"
        ? ["커밋 수", (n) => n.metrics?.churn ?? null, 1]
        : ["최대 함수 복잡도", (n) => n.metrics?.max_complexity ?? null, 10];
  // The 95th percentile keeps one outlier from washing out the rest.
  const sorted = modules.map((m) => value(m) ?? 0).sort((a, b) => a - b);
  const max = Math.max(floor, sorted[Math.floor(sorted.length * 0.95)] ?? 0);
  return { max, label, value, color: (n) => colorOf(value(n), max) };
}

function colorOf(value: number | null, max: number): string {
  return value === null ? "#2a3040" : ramp(value / max);
}
