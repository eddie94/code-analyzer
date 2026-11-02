import type { Edge, EntryPoint } from "../types/graph";
import { isLibrary, type GraphIndex } from "./graphIndex";

export type FlowChild =
  | { kind: "call"; edge: Edge; recursive: boolean }
  | { kind: "libraries"; names: string[] }
  | { kind: "unresolved"; texts: string[] };

/**
 * What `id` calls, in source order. Library calls are folded into one row and
 * calls that could not be followed into another. `path` holds the callers above,
 * so recursion is marked instead of expanded.
 */
export function flowChildren(
  index: GraphIndex,
  id: string,
  path: readonly string[],
  options: { showLibraries: boolean },
): FlowChild[] {
  const children: FlowChild[] = [];
  const libraries: string[] = [];
  for (const edge of index.callsFrom.get(id) ?? []) {
    const target = index.nodes.get(edge.target);
    if (target && isLibrary(target)) {
      libraries.push(...(edge.names?.length ? edge.names : [target.name]));
      continue;
    }
    children.push({ kind: "call", edge, recursive: edge.target === id || path.includes(edge.target) });
  }
  if (options.showLibraries && libraries.length) children.push({ kind: "libraries", names: [...new Set(libraries)] });
  const unresolved = index.nodes.get(id)?.unresolved_calls ?? [];
  if (unresolved.length) children.push({ kind: "unresolved", texts: unresolved });
  return children;
}

/** Entry points whose call tree reaches `id`, nearest first. */
export function reachingEntrypoints(index: GraphIndex, id: string, limit = 20): EntryPoint[] {
  const byTarget = new Map<string, EntryPoint[]>();
  for (const entry of index.graph.entrypoints ?? []) {
    const list = byTarget.get(entry.target);
    if (list) list.push(entry);
    else byTarget.set(entry.target, [entry]);
  }
  const found: EntryPoint[] = [];
  const seen = new Set([id]);
  let frontier = [id];
  while (frontier.length && found.length < limit) {
    const next: string[] = [];
    for (const node of frontier) {
      found.push(...(byTarget.get(node) ?? []));
      for (const edge of index.callsTo.get(node) ?? []) {
        if (!seen.has(edge.source)) {
          seen.add(edge.source);
          next.push(edge.source);
        }
      }
    }
    frontier = next;
  }
  return found.slice(0, limit);
}

/** Short label for a function or class: `Class.method` or `function`. */
export function shortName(index: GraphIndex, id: string): string {
  const node = index.nodes.get(id);
  if (!node) return id;
  const module = index.moduleOf(id);
  const moduleName = module ? index.nodes.get(module)?.qualname : undefined;
  const local = moduleName && node.qualname.startsWith(`${moduleName}.`)
    ? node.qualname.slice(moduleName.length + 1)
    : node.qualname;
  return node.kind === "class" ? `${local}()` : local;
}
