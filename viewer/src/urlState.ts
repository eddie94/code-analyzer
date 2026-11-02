/** View state kept in the URL hash, so a view can be reloaded or shared as a link. */

export const TABS = ["overview", "deps", "classes", "issues"] as const;
export type Tab = (typeof TABS)[number];

export interface UrlState {
  tab: Tab;
  selected: string | null;
  /** Null means "not in the URL": choose a default expansion. */
  expanded: string[] | null;
  showExternal: boolean;
  showWeak: boolean;
  showCycles: boolean;
  hideTests: boolean;
}

export const DEFAULTS: UrlState = {
  tab: "deps",
  selected: null,
  expanded: null,
  showExternal: false,
  showWeak: true,
  showCycles: true,
  hideTests: false,
};

const FLAGS = [
  ["showExternal", "ext"],
  ["showWeak", "weak"],
  ["showCycles", "cyc"],
  ["hideTests", "notests"],
] as const;

export function encode(state: UrlState): string {
  const params = new URLSearchParams();
  if (state.tab !== DEFAULTS.tab) params.set("tab", state.tab);
  if (state.selected) params.set("sel", state.selected);
  if (state.expanded) params.set("exp", [...state.expanded].sort().join(","));
  for (const [key, name] of FLAGS) {
    if (state[key] !== DEFAULTS[key]) params.set(name, state[key] ? "1" : "0");
  }
  // Node ids contain ':' and '.'; keep them readable.
  return params.toString().replace(/%3A/g, ":").replace(/%2C/g, ",");
}

export function decode(hash: string): UrlState {
  const params = new URLSearchParams(hash.replace(/^#/, ""));
  const tab = params.get("tab");
  const exp = params.get("exp");
  const state: UrlState = {
    ...DEFAULTS,
    tab: TABS.includes(tab as Tab) ? (tab as Tab) : DEFAULTS.tab,
    selected: params.get("sel") || null,
    expanded: exp === null ? null : exp.split(",").filter(Boolean),
  };
  for (const [key, name] of FLAGS) {
    const value = params.get(name);
    if (value !== null) state[key] = value === "1";
  }
  return state;
}
