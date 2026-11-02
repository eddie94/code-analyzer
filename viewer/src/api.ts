import type { Graph } from "./types/graph";

async function getJson<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url}: ${response.status} ${response.statusText}`);
  return response.json() as Promise<T>;
}

export function fetchGraph(): Promise<Graph> {
  return getJson<Graph>("/api/graph");
}

export async function fetchSource(path: string): Promise<string> {
  const body = await getJson<{ text: string }>(`/api/source?path=${encodeURIComponent(path)}`);
  return body.text;
}
