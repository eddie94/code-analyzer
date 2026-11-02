import type { Node } from "../types/graph";
import type { GraphIndex } from "./graphIndex";

export const MAX_CLASSES = 250;

export interface ClassViewModel {
  /** Classes inside the scope. */
  classes: Node[];
  /** Bases and subclasses outside the scope, shown for context. */
  outside: Node[];
  /** [subclass, base] pairs among the shown classes. */
  edges: Array<[string, string]>;
  /** Classes in scope before `onlyLinked` filtering. */
  total: number;
}

/** The narrowest package or module that makes sense as a class-diagram scope for `id`. */
export function scopeFor(index: GraphIndex, id: string | null): string | null {
  let current = id ? index.nodes.get(id) : undefined;
  while (current && current.kind !== "package" && current.kind !== "module") {
    current = current.parent ? index.nodes.get(current.parent) : undefined;
  }
  return current?.id ?? null;
}

export function classView(
  index: GraphIndex,
  scope: string | null,
  options: { onlyLinked: boolean; hideTests: boolean },
): ClassViewModel {
  const inScope = (n: Node) =>
    n.kind === "class" &&
    (scope === null || index.isInside(n.id, scope)) &&
    !(options.hideTests && index.isTest(index.moduleOf(n.id) ?? n.id));
  const all = index.graph.nodes.filter(inScope);
  const ids = new Set(all.map((n) => n.id));

  const relevant = index.extends.filter((e) => ids.has(e.source) || ids.has(e.target));
  const linked = new Set(relevant.flatMap((e) => [e.source, e.target]));
  const classes = options.onlyLinked ? all.filter((n) => linked.has(n.id)) : all;

  const outside = [...linked]
    .filter((id) => !ids.has(id))
    .map((id) => index.nodes.get(id)!)
    .sort((a, b) => a.qualname.localeCompare(b.qualname));
  return {
    classes,
    outside,
    edges: relevant.map((e) => [e.source, e.target] as [string, string]),
    total: all.length,
  };
}

/** UML-style label: class name, then up to `limit` member names. */
export function classLabel(index: GraphIndex, node: Node, limit = 6): string {
  const members = (index.children.get(node.id) ?? []).filter((m) => m.kind === "method" || m.kind === "class");
  const lines = members.slice(0, limit).map((m) => (m.kind === "method" ? `${m.name}()` : `class ${m.name}`));
  if (members.length > limit) lines.push(`… +${members.length - limit}`);
  return lines.length ? `${node.name}\n${lines.join("\n")}` : node.name;
}

/** Number of classes inside each package and module (one pass over all classes). */
export function classCounts(index: GraphIndex, hideTests: boolean): Map<string, number> {
  const counts = new Map<string, number>();
  for (const node of index.graph.nodes) {
    if (node.kind !== "class") continue;
    const module = index.moduleOf(node.id);
    if (!module || (hideTests && index.isTest(module))) continue;
    for (const owner of [module, ...index.ancestors(module)]) counts.set(owner, (counts.get(owner) ?? 0) + 1);
  }
  return counts;
}
