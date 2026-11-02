import type { App, EntryPoint, Launch, SharedState } from "../types/graph";
import type { GraphIndex } from "./graphIndex";

/** How the service behind an entry point is started and wired up. */
export interface Startup {
  apps: App[]; // the app the entry hangs off, then the apps that mount it
  launches: Launch[];
  hooks: EntryPoint[];
  /** Shared state set by a startup hook (or __main__) and read somewhere in this request. */
  state: SharedState[];
}

export function appById(index: GraphIndex, id: string | null | undefined): App | undefined {
  return (index.graph.apps ?? []).find((a) => a.id === id);
}

/** The app plus every app that mounts it (include_router / register_blueprint), innermost first. */
export function appChain(index: GraphIndex, appId: string): App[] {
  const chain: App[] = [];
  const seen = new Set<string>();
  let frontier = [appId];
  while (frontier.length) {
    const next: string[] = [];
    for (const id of frontier) {
      const app = appById(index, id);
      if (!app || seen.has(id)) continue;
      seen.add(id);
      chain.push(app);
      next.push(...(index.graph.apps ?? []).filter((a) => a.includes?.includes(id)).map((a) => a.id));
    }
    frontier = next;
  }
  return chain;
}

/** Launches that start any of `appIds`, directly or through a `__main__` that does. */
export function launchesOf(index: GraphIndex, appIds: Set<string>): Launch[] {
  const launches = index.graph.launches ?? [];
  const direct = launches.filter((l) => l.target && appIds.has(l.target));
  const mains = new Set(direct.filter((l) => l.kind === "code" && l.source).map((l) => l.source!));
  const viaMain = launches.filter((l) => l.target && mains.has(l.target));
  return [...new Set([...direct, ...viaMain])];
}

/** Functions reachable from `id` through calls (a bounded search). */
export function reachable(index: GraphIndex, id: string, limit = 400): Set<string> {
  const seen = new Set([id]);
  const queue = [id];
  while (queue.length && seen.size < limit) {
    for (const edge of index.callsFrom.get(queue.shift()!) ?? []) {
      if (!seen.has(edge.target) && !edge.target.startsWith("stdlib:") && !edge.target.startsWith("external:")) {
        seen.add(edge.target);
        queue.push(edge.target);
      }
    }
  }
  return seen;
}

export function startupOf(index: GraphIndex, functionId: string): Startup | null {
  const entry = (index.graph.entrypoints ?? []).find((e) => e.target === functionId && e.app);
  if (!entry?.app) return null;
  const apps = appChain(index, entry.app);
  const appIds = new Set(apps.map((a) => a.id));
  const hooks = (index.graph.entrypoints ?? []).filter(
    (e) => e.kind === "startup" && e.label === "on startup" && e.app && appIds.has(e.app),
  );
  const launches = launchesOf(index, appIds);
  const setters = new Set([...hooks.map((h) => h.target), ...launches.flatMap((l) => (l.source ? [l.source] : []))]);
  const used = reachable(index, functionId);
  const state = (index.graph.state ?? []).filter(
    (s) => s.writers.some((w) => setters.has(w)) && s.readers.some((r) => used.has(r)),
  );
  return { apps, launches, hooks, state };
}
