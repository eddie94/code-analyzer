import { create } from "zustand";
import { hasSourceApi } from "./api";
import { buildIndex, type GraphIndex } from "./model/graphIndex";
import { autoExpand } from "./model/view";
import type { Graph } from "./types/graph";
import { DEFAULTS, encode, type Tab, type UrlState } from "./urlState";

type Option = "showExternal" | "showWeak" | "showCycles" | "hideTests";

interface State {
  index: GraphIndex | null;
  tab: Tab;
  expanded: Set<string>;
  showExternal: boolean;
  showWeak: boolean;
  showCycles: boolean;
  hideTests: boolean;
  /** Any node id, including classes and functions. */
  selected: string | null;
  /** A cycle (module ids in order) to emphasize in the dependency graph. */
  path: string[] | null;
  sourceOpen: boolean;
  /** Line to show in the source drawer instead of the selection's own range. */
  sourceLine: number | null;
  /** Bumped to ask the canvas to fit the whole view again. */
  fitRequest: number;
  /** Bumped to ask the canvas to center on the selection. */
  focusRequest: number;

  load(graph: Graph, initial?: UrlState): void;
  /** Apply view state from the URL (on load, or when the hash is edited). */
  applyUrl(state: UrlState): void;
  setTab(tab: Tab): void;
  toggle(packageId: string): void;
  select(id: string | null): void;
  /** Select a node and make it visible in the dependency graph. */
  reveal(id: string): void;
  showPath(modules: string[]): void;
  clearPath(): void;
  setOption(key: Option, value: boolean): void;
  openSource(line?: number | null): void;
  closeSource(): void;
  reset(): void;
}

export const useStore = create<State>()((set, get) => ({
  index: null,
  tab: DEFAULTS.tab,
  expanded: new Set(),
  showExternal: DEFAULTS.showExternal,
  showWeak: DEFAULTS.showWeak,
  showCycles: DEFAULTS.showCycles,
  hideTests: DEFAULTS.hideTests,
  selected: null,
  path: null,
  sourceOpen: false,
  sourceLine: null,
  fitRequest: 0,
  focusRequest: 0,

  load(graph, initial = DEFAULTS) {
    set({ index: buildIndex(graph) });
    get().applyUrl(initial);
  },

  applyUrl(state) {
    const { index, fitRequest } = get();
    if (!index) return;
    const { showExternal, showWeak, hideTests } = state;
    const expanded = state.expanded
      ? new Set(state.expanded.filter((id) => index.nodes.get(id)?.kind === "package"))
      : autoExpand(index, { showExternal, showWeak, hideTests });
    const selected = state.selected && index.nodes.has(state.selected) ? state.selected : null;
    set({ ...state, expanded, selected, path: null, sourceOpen: false, fitRequest: fitRequest + 1 });
  },

  setTab(tab) {
    set({ tab, sourceOpen: false });
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
    set({
      selected: id,
      sourceLine: null,
      sourceOpen: sourceOpen && Boolean(node?.path && node.kind !== "package"),
    });
  },

  reveal(id) {
    const { index, expanded, focusRequest } = get();
    if (!index?.nodes.has(id)) return;
    const anchor = index.moduleOf(id) ?? id;
    const next = new Set(expanded);
    for (const a of index.ancestors(anchor)) next.add(a);
    if (anchor === id) next.delete(id);
    set({ tab: "deps", expanded: next, selected: id, focusRequest: focusRequest + 1 });
  },

  showPath(modules) {
    const { index, expanded, fitRequest } = get();
    if (!index) return;
    const next = new Set(expanded);
    for (const m of modules) for (const a of index.ancestors(m)) next.add(a);
    set({ tab: "deps", path: modules, expanded: next, selected: null, sourceOpen: false, fitRequest: fitRequest + 1 });
  },

  clearPath() {
    set({ path: null });
  },

  setOption(key, value) {
    set({ [key]: value } as Pick<State, Option>);
  },

  openSource(line = null) {
    if (hasSourceApi) set({ sourceOpen: true, sourceLine: line });
  },

  closeSource() {
    set({ sourceOpen: false, sourceLine: null });
  },

  reset() {
    const { index, showExternal, showWeak, hideTests, fitRequest } = get();
    if (!index) return;
    set({
      expanded: autoExpand(index, { showExternal, showWeak, hideTests }),
      selected: null,
      path: null,
      sourceOpen: false,
      fitRequest: fitRequest + 1,
    });
  },
}));

/** The part of the state that belongs in the URL. */
export function urlHash(state: State): string {
  return encode({
    tab: state.tab,
    selected: state.selected,
    expanded: [...state.expanded],
    showExternal: state.showExternal,
    showWeak: state.showWeak,
    showCycles: state.showCycles,
    hideTests: state.hideTests,
  });
}
