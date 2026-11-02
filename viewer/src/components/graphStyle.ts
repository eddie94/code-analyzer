import type { StylesheetJson } from "cytoscape";

export const ACCENT = "#7aa2f7";
export const DANGER = "#ff6b81";
export const WARN = "#e0af68";
export const VIOLATION = "#d670d6";
const EDGE = "#4a536a";

export const GRAPH_STYLE: StylesheetJson = [
  {
    selector: "node",
    style: {
      label: "data(label)",
      color: "#e4e7ef",
      "font-size": 11,
      "text-wrap": "wrap",
      "text-valign": "center",
      "text-halign": "center",
      shape: "round-rectangle",
      width: "data(w)",
      height: "data(h)",
      "background-color": "#1b2130",
      "border-width": 1.5,
      "border-color": "data(color)",
    },
  },
  { selector: "node.module", style: { "font-family": "Menlo, Consolas, monospace" } },
  {
    selector: "node.collapsed",
    style: {
      "background-color": "data(color)",
      "background-opacity": 0.18,
      "border-width": 2,
      "font-weight": 600,
      "font-size": 12,
    },
  },
  { selector: "node.lib", style: { shape: "round-tag", color: "#aab1c3", "border-style": "dotted" } },
  { selector: "node.error", style: { "border-color": DANGER, "border-style": "dashed", "border-width": 2 } },
  {
    selector: "node.compound",
    style: {
      "background-color": "data(color)",
      "background-opacity": 0.04,
      "border-color": "data(color)",
      "border-opacity": 0.45,
      "border-width": 1,
      "text-valign": "top",
      "text-margin-y": -4,
      color: "#8a92a6",
      "font-size": 12,
      "font-weight": 600,
      padding: "14px",
    },
  },
  {
    selector: "edge",
    style: {
      "curve-style": "bezier",
      width: "data(width)",
      "line-color": EDGE,
      "target-arrow-color": EDGE,
      "target-arrow-shape": "triangle",
      "arrow-scale": 0.8,
      opacity: 0.75,
    },
  },
  { selector: "edge.weak", style: { "line-style": "dashed", "line-dash-pattern": [5, 4], opacity: 0.45 } },
  { selector: "edge.cycle", style: { "line-color": DANGER, "target-arrow-color": DANGER, opacity: 0.9 } },
  {
    selector: "edge.violation",
    style: {
      "line-color": VIOLATION,
      "target-arrow-color": VIOLATION,
      "line-style": "dashed",
      "line-dash-pattern": [8, 4],
      width: 2.5,
      opacity: 1,
    },
  },
  { selector: ".faded", style: { opacity: 0.12 } },
  {
    selector: "edge.hl",
    style: { "line-color": ACCENT, "target-arrow-color": ACCENT, opacity: 1, "z-index": 9 },
  },
  { selector: "edge.hl.cycle", style: { "line-color": DANGER, "target-arrow-color": DANGER } },
  { selector: "node:selected", style: { "border-width": 3, "border-color": "#ffffff" } },
  { selector: ".off-path", style: { opacity: 0.12 } },
  { selector: "node.on-path", style: { "border-width": 3, "border-color": WARN } },
  {
    selector: "edge.on-path",
    style: { width: 4, "line-color": WARN, "target-arrow-color": WARN, "line-style": "solid", opacity: 1, "z-index": 10 },
  },
];
