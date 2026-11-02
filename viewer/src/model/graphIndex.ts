import type { Edge, Graph, Node } from "../types/graph";

const PALETTE = [
  "#7aa2f7", "#9ece6a", "#e0af68", "#bb9af7", "#7dcfff",
  "#ff9e64", "#73daca", "#c3a6ff", "#f2c97d", "#5fd7c8",
];
export const LIBRARY_COLOR = "#59627a";

/** Lookups over a graph.json that the views need repeatedly. */
export interface GraphIndex {
  graph: Graph;
  nodes: Map<string, Node>;
  children: Map<string, Node[]>;
  modules: Node[];
  imports: Edge[];
  extends: Edge[];
  /** Call edges by caller, in source order. */
  callsFrom: Map<string, Edge[]>;
  /** Call edges by callee. */
  callsTo: Map<string, Edge[]>;
  parseErrors: Set<string>;
  /** `source\u0000target` module pairs that break the configured layers. */
  layerViolations: Set<string>;
  /** Package ancestors of a node, outermost first. */
  ancestors(id: string): string[];
  /** True if `id` is `pkg` or lives somewhere below it. */
  isInside(id: string, pkg: string): boolean;
  moduleCount(pkg: string): number;
  /** Test modules, and packages holding nothing but tests. */
  isTest(id: string): boolean;
  /** The module that contains a symbol (or the node itself for modules). */
  moduleOf(id: string): string | null;
  color(node: Node): string;
}

const isTestPart = (part: string) =>
  part === "tests" || part === "test" || part === "conftest" || part.startsWith("test_") || part.endsWith("_test");

export function isLibrary(node: Node): boolean {
  return node.kind === "stdlib" || node.kind === "external";
}

export function buildIndex(graph: Graph): GraphIndex {
  const nodes = new Map(graph.nodes.map((n) => [n.id, n]));
  const children = new Map<string, Node[]>();
  for (const node of graph.nodes) {
    if (!node.parent) continue;
    const list = children.get(node.parent);
    if (list) list.push(node);
    else children.set(node.parent, [node]);
  }

  const ancestorCache = new Map<string, string[]>();
  const ancestors = (id: string): string[] => {
    let cached = ancestorCache.get(id);
    if (!cached) {
      const parent = nodes.get(id)?.parent;
      cached = parent ? [...ancestors(parent), parent] : [];
      ancestorCache.set(id, cached);
    }
    return cached;
  };
  // Symbols have module/class parents; only package ancestors matter for folding.
  const packageAncestors = (id: string) => ancestors(id).filter((a) => nodes.get(a)?.kind === "package");

  const modules = graph.nodes.filter((n) => n.kind === "module");
  const calls = graph.edges
    .filter((e) => e.kind === "calls")
    .sort((a, b) => (a.line ?? 0) - (b.line ?? 0) || a.target.localeCompare(b.target));
  const counts = new Map<string, number>();
  const testCounts = new Map<string, number>();
  const testModules = new Set(modules.filter((m) => m.qualname.split(".").some(isTestPart)).map((m) => m.id));
  for (const m of modules) {
    for (const a of packageAncestors(m.id)) {
      counts.set(a, (counts.get(a) ?? 0) + 1);
      if (testModules.has(m.id)) testCounts.set(a, (testCounts.get(a) ?? 0) + 1);
    }
  }

  const tops = new Set(modules.map((m) => m.qualname.split(".")[0]));
  const depth = tops.size === 1 ? 2 : 1;
  const groupOf = (qualname: string) => qualname.split(".").slice(0, depth).join(".");
  const groups = [...new Set(modules.map((m) => groupOf(m.qualname)))].sort();

  return {
    graph,
    nodes,
    children,
    modules,
    imports: graph.edges.filter((e) => e.kind === "imports"),
    extends: graph.edges.filter((e) => e.kind === "extends"),
    callsFrom: groupBy(calls, (e) => e.source),
    callsTo: groupBy(calls, (e) => e.target),
    parseErrors: new Set(graph.issues.filter((i) => i.kind === "parse_error").flatMap((i) => i.nodes)),
    layerViolations: new Set(
      graph.issues.filter((i) => i.kind === "layer_violation").map((i) => `${i.nodes[0]}\u0000${i.nodes[1]}`),
    ),
    ancestors: packageAncestors,
    isInside: (id, pkg) => id === pkg || ancestors(id).includes(pkg),
    moduleCount: (pkg) => counts.get(pkg) ?? 0,
    isTest: (id) => testModules.has(id) || (counts.has(id) && testCounts.get(id) === counts.get(id)),
    moduleOf: (id) => {
      const node = nodes.get(id);
      if (!node) return null;
      if (node.kind === "module") return id;
      return ancestors(id).find((a) => nodes.get(a)?.kind === "module") ?? null;
    },
    color: (node) => {
      if (isLibrary(node)) return LIBRARY_COLOR;
      const index = groups.indexOf(groupOf(node.qualname));
      return PALETTE[Math.max(0, index) % PALETTE.length];
    },
  };
}

function groupBy<T>(items: T[], key: (item: T) => string): Map<string, T[]> {
  const map = new Map<string, T[]>();
  for (const item of items) {
    const list = map.get(key(item));
    if (list) list.push(item);
    else map.set(key(item), [item]);
  }
  return map;
}
