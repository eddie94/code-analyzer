import { isLibrary, type GraphIndex } from "./graphIndex";

export interface ViewOptions {
  expanded: ReadonlySet<string>;
  showExternal: boolean;
  /** Include TYPE_CHECKING and function-level imports. */
  showWeak: boolean;
  hideTests: boolean;
}

export interface ViewEdge {
  source: string;
  target: string;
  count: number;
  /** Every import behind this edge is type-only or lazy. */
  weak: boolean;
  /** Part of a cycle among the solid edges of this view. */
  cyclic: boolean;
  /** At least one import behind this edge breaks the configured layers. */
  violation: boolean;
}

export interface View {
  /** Leaf nodes: collapsed packages, modules and library nodes. */
  units: string[];
  /** Expanded packages, drawn as boxes around their visible contents. */
  compounds: string[];
  edges: ViewEdge[];
}

/** The visible node standing in for `id`: its outermost collapsed package, or itself. */
export function unitOf(index: GraphIndex, id: string, options: ViewOptions): string | null {
  const node = index.nodes.get(id);
  if (!node) return null;
  if (isLibrary(node)) return options.showExternal ? id : null;
  if (options.hideTests && index.isTest(id)) return null;
  for (const ancestor of index.ancestors(id)) {
    if (!options.expanded.has(ancestor)) return ancestor;
  }
  return id;
}

export function computeView(index: GraphIndex, options: ViewOptions): View {
  const units = new Set<string>();
  for (const m of index.modules) {
    const unit = unitOf(index, m.id, options);
    if (unit) units.add(unit);
  }

  const edges = new Map<string, ViewEdge>();
  for (const e of index.imports) {
    const weak = Boolean(e.type_only || e.lazy);
    if (weak && !options.showWeak) continue;
    const source = unitOf(index, e.source, options);
    const target = unitOf(index, e.target, options);
    if (!source || !target || source === target) continue;
    units.add(source).add(target);
    const key = `${source}\u0000${target}`;
    const edge = edges.get(key) ?? { source, target, count: 0, weak: true, cyclic: false, violation: false };
    edge.count += 1;
    edge.weak &&= weak;
    edge.violation ||= index.layerViolations.has(`${e.source}\u0000${e.target}`);
    edges.set(key, edge);
  }

  const compounds = new Set<string>();
  for (const unit of units) {
    for (const a of index.ancestors(unit)) if (options.expanded.has(a)) compounds.add(a);
  }
  for (const c of compounds) units.delete(c);

  const list = [...edges.values()];
  markCycles(list);
  return { units: [...units].sort(), compounds: [...compounds].sort(), edges: list };
}

/** Flag solid edges whose endpoints share a strongly connected component (iterative Tarjan). */
export function markCycles(edges: ViewEdge[]): void {
  const adjacency = new Map<string, string[]>();
  for (const e of edges) {
    if (e.weak) continue;
    const out = adjacency.get(e.source);
    if (out) out.push(e.target);
    else adjacency.set(e.source, [e.target]);
  }

  let counter = 0;
  const index = new Map<string, number>();
  const low = new Map<string, number>();
  const component = new Map<string, number>();
  const stack: string[] = [];
  const onStack = new Set<string>();

  for (const root of adjacency.keys()) {
    if (index.has(root)) continue;
    const work: Array<[string, number]> = [[root, 0]];
    while (work.length) {
      const frame = work[work.length - 1];
      const [v, i] = frame;
      if (i === 0) {
        index.set(v, counter);
        low.set(v, counter);
        counter++;
        stack.push(v);
        onStack.add(v);
      }
      const next = adjacency.get(v) ?? [];
      if (i < next.length) {
        frame[1]++;
        const w = next[i];
        if (!index.has(w)) work.push([w, 0]);
        else if (onStack.has(w)) low.set(v, Math.min(low.get(v)!, index.get(w)!));
        continue;
      }
      work.pop();
      if (work.length) {
        const parent = work[work.length - 1][0];
        low.set(parent, Math.min(low.get(parent)!, low.get(v)!));
      }
      if (low.get(v) === index.get(v)) {
        const members: string[] = [];
        let w: string;
        do {
          w = stack.pop()!;
          onStack.delete(w);
          members.push(w);
        } while (w !== v);
        if (members.length > 1) for (const m of members) component.set(m, index.get(v)!);
      }
    }
  }

  for (const e of edges) {
    e.cyclic = !e.weak && component.has(e.source) && component.get(e.source) === component.get(e.target);
  }
}

/** Expand packages level by level while the view stays small enough to read. */
export function autoExpand(index: GraphIndex, options: Omit<ViewOptions, "expanded">, limit = 28): Set<string> {
  let expanded = new Set<string>();
  const packages = index.graph.nodes.filter((n) => n.kind === "package");
  for (let depth = 0; ; depth++) {
    const level = packages.filter((p) => index.ancestors(p.id).length === depth);
    if (!level.length) break;
    const next = new Set([...expanded, ...level.map((p) => p.id)]);
    const size = computeView(index, { ...options, expanded: next }).units.length;
    if (depth > 0 && size > limit) break;
    expanded = next;
  }
  return expanded;
}
