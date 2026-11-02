import type { Tab } from "./urlState";

/**
 * Browser history for moves between views: switching tabs or starting the flow
 * tab from another function adds an entry, so Back (the button, the mouse,
 * ⌘[) returns to where you were. Smaller changes (selection, expanded packages)
 * only rewrite the current entry.
 *
 * Each entry's history.state carries the trail of views before it, so the flow
 * tab can show where you came from without keeping a copy of the history.
 */
export interface Place {
  tab: Tab;
  flowRoot: string | null;
}

export interface NavState {
  trail: Place[];
}

const MAX_TRAIL = 30;

export function samePlace(a: Place, b: Place): boolean {
  return a.tab === b.tab && (a.tab !== "flow" || a.flowRoot === b.flowRoot);
}

/** The trail for a new entry, after leaving `from`. */
export function extendTrail(trail: Place[], from: Place): Place[] {
  return [...trail, from].slice(-MAX_TRAIL);
}

export function trailOf(state: unknown): Place[] {
  const trail = (state as NavState | null)?.trail;
  return Array.isArray(trail) ? trail : [];
}
