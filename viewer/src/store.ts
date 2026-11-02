import { create } from "zustand";
import { buildIndex, type GraphIndex } from "./model/graphIndex";
import { autoExpand } from "./model/view";
import type { Graph } from "./types/graph";

interface State {
  index: GraphIndex | null;
  expanded: Set<string>;
  showExternal: boolean;
  showWeak: boolean;
  showCycles: boolean;
  /** Any node id, including classes and functions. */
  selected: string | null;
  sourceOpen: boolean;
  /** Bumped to ask the canvas to fit the whole view again. */
  fitRequest: number;
  /** Bumped to ask the canvas to center on the selection. */
  focusRequest: number;

  load(graph: Graph): void;
  toggle(packageId: string): void;
  select(id: string | null): void;
  reveal(id: string): void;
  setOption(key: "showExternal" | "showWeak" | "showCycles", value: boolean): void;
  setSourceOpen(open: boolean): void;
  reset(): void;
}

export const useStore = create<State>()((set, get) => ({
  index: null,
  expanded: new Set(),
  showExternal: false,
  showWeak: true,
  showCycles: true,
  selected: null,
  sourceOpen: false,
  fitRequest: 0,
  focusRequest: 0,

  load(graph) {
    const index = buildIndex(graph);
    const { showExternal, showWeak } = get();
    set({ index, expanded: autoExpand(index, { showExternal, showWeak }), selected: null });
  },

  toggle(packageId) {
    const { index, expanded, fitRequest } = get();
    if (index?.nodes.get(packageId)?.kind !== "package") return;
    const next = new Set(expanded);
    if (next.has(packageId)) {
      for (const p of expanded) if (index.isInside(p, packageId)) next.delete(p);
    } else {
      next.add(packageId);
    }
    set({ expanded: next, selected: packageId, fitRequest: fitRequest + 1 });
  },

  select(id) {
    const { index, sourceOpen } = get();
    const node = id ? index?.nodes.get(id) : null;
    // Keep the source drawer only while the selection still has source to show.
    set({ selected: id, sourceOpen: sourceOpen && Boolean(node?.path && node.kind !== "package") });
  },

  reveal(id) {
    const { index, expanded, focusRequest } = get();
    if (!index?.nodes.has(id)) return;
    const anchor = index.moduleOf(id) ?? id;
    const next = new Set(expanded);
    for (const a of index.ancestors(anchor)) next.add(a);
    if (anchor === id) next.delete(id);
    set({ expanded: next, selected: id, focusRequest: focusRequest + 1 });
  },

  setOption(key, value) {
    set({ [key]: value } as Pick<State, typeof key>);
  },

  setSourceOpen(open) {
    set({ sourceOpen: open });
  },

  reset() {
    const { index, showExternal, showWeak, fitRequest } = get();
    if (!index) return;
    set({
      expanded: autoExpand(index, { showExternal, showWeak }),
      selected: null,
      sourceOpen: false,
      fitRequest: fitRequest + 1,
    });
  },
}));
