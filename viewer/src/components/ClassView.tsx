import type { Core, ElementDefinition, LayoutOptions, NodeSingular, StylesheetJson } from "cytoscape";
import { useEffect, useMemo, useRef, useState } from "react";
import { classCounts, classLabel, classView, MAX_CLASSES, scopeFor, type ClassViewModel } from "../model/classes";
import type { GraphIndex } from "../model/graphIndex";
import { useStore } from "../store";
import { cytoscape } from "./cy";

const STYLE: StylesheetJson = [
  {
    selector: "node.class",
    style: {
      shape: "round-rectangle",
      label: "data(label)",
      "text-wrap": "wrap",
      "text-valign": "center",
      "text-halign": "center",
      "text-justification": "left",
      "font-family": "Menlo, Consolas, monospace",
      "font-size": 10,
      "line-height": 1.35,
      color: "#e4e7ef",
      width: "data(w)",
      height: "data(h)",
      "background-color": "#1b2130",
      "border-width": 1.5,
      "border-color": "data(color)",
    },
  },
  { selector: "node.outside", style: { "border-style": "dashed", opacity: 0.55 } },
  {
    selector: "node.module",
    style: {
      shape: "round-rectangle",
      label: "data(label)",
      "text-valign": "top",
      "text-margin-y": -4,
      "font-size": 11,
      color: "#8a92a6",
      "background-color": "data(color)",
      "background-opacity": 0.05,
      "border-width": 1,
      "border-color": "data(color)",
      "border-opacity": 0.4,
      padding: "12px",
    },
  },
  {
    selector: "edge",
    style: {
      "curve-style": "bezier",
      width: 1.5,
      "line-color": "#6b7590",
      "target-arrow-color": "#6b7590",
      "target-arrow-shape": "triangle",
      "target-arrow-fill": "hollow",
      "arrow-scale": 1.3,
    },
  },
  { selector: "node:selected", style: { "border-width": 3, "border-color": "#ffffff" } },
];

// Modules are packed into a compact rectangle; classes inside each module are
// layered with bases above their subclasses, as in UML.
const MODULE_LAYOUT = {
  "elk.algorithm": "layered",
  "elk.direction": "UP",
  "elk.layered.spacing.nodeNodeBetweenLayers": 40,
  "elk.spacing.nodeNode": 16,
  "elk.padding": "[top=30,left=12,bottom=12,right=12]",
};

function layout(aspectRatio: number) {
  return {
    name: "elk",
    padding: 40,
    fit: true,
    nodeDimensionsIncludeLabels: true,
    elk: {
      algorithm: "rectpacking",
      "elk.hierarchyHandling": "SEPARATE_CHILDREN",
      "elk.aspectRatio": aspectRatio,
      "elk.spacing.nodeNode": 28,
    },
    nodeLayoutOptions: (node: NodeSingular) => (node.hasClass("module") ? MODULE_LAYOUT : undefined),
  } as LayoutOptions;
}

export function ClassView() {
  const index = useStore((s) => s.index)!;
  const hideTests = useStore((s) => s.hideTests);
  const selected = useStore((s) => s.selected);
  const [scope, setScope] = useState(() => scopeFor(index, useStore.getState().selected));
  const total = useMemo(() => classView(index, scope, { onlyLinked: false, hideTests }).total, [index, scope, hideTests]);
  const [onlyLinked, setOnlyLinked] = useState(total > 30);
  const view = useMemo(
    () => classView(index, scope, { onlyLinked, hideTests }),
    [index, scope, onlyLinked, hideTests],
  );
  const scopes = useMemo(() => {
    const counts = classCounts(index, hideTests);
    return [...counts]
      .map(([id, count]) => ({ node: index.nodes.get(id)!, count }))
      .sort((a, b) => a.node.qualname.localeCompare(b.node.qualname));
  }, [index, hideTests]);
  const tooMany = view.classes.length + view.outside.length > MAX_CLASSES;

  return (
    <div className="classes">
      <div className="overview-bar">
        <span className="muted">범위</span>
        <select value={scope ?? ""} onChange={(e) => setScope(e.target.value || null)}>
          <option value="">전체 저장소</option>
          {scopes.map(({ node, count }) => (
            <option key={node.id} value={node.id}>
              {node.qualname}
              {node.kind === "module" ? " (모듈)" : ""} · {count}
            </option>
          ))}
        </select>
        <label className="toggle">
          <input type="checkbox" checked={onlyLinked} onChange={(e) => setOnlyLinked(e.target.checked)} />
          상속 관계가 있는 클래스만
        </label>
        <span className="spacer" />
        <span className="muted">
          클래스 {view.classes.length}개{view.outside.length ? ` + 범위 밖 ${view.outside.length}개` : ""} · 더블클릭: 소스
        </span>
      </div>
      {tooMany ? (
        <p className="empty">
          클래스가 너무 많습니다({view.classes.length + view.outside.length}개). 범위를 좁히거나 "상속 관계가 있는 클래스만"을
          켜 주세요.
        </p>
      ) : view.classes.length === 0 ? (
        <p className="empty">이 범위에는 {onlyLinked && view.total ? "상속 관계가 있는 " : ""}클래스가 없습니다.</p>
      ) : (
        <ClassGraph index={index} view={view} selected={selected} />
      )}
    </div>
  );
}

function ClassGraph({ index, view, selected }: { index: GraphIndex; view: ClassViewModel; selected: string | null }) {
  const container = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);

  useEffect(() => {
    const cy = cytoscape({ container: container.current, style: STYLE, wheelSensitivity: 0.25, minZoom: 0.05, maxZoom: 3 });
    const { select, openSource } = useStore.getState();
    cy.on("tap", "node.class", (e) => select(e.target.id()));
    cy.on("tap", (e) => {
      if (e.target === cy) select(null);
    });
    cy.on("dbltap", "node.class", (e) => {
      select(e.target.id());
      openSource();
    });
    cyRef.current = cy;
    return () => cy.destroy();
  }, []);

  useEffect(() => {
    const cy = cyRef.current!;
    cy.batch(() => {
      cy.elements().remove();
      cy.add(elements(index, view));
    });
    cy.layout(layout(Math.max(0.5, cy.width() / Math.max(1, cy.height())))).run();
  }, [index, view]);

  useEffect(() => {
    const cy = cyRef.current!;
    cy.$(":selected").unselect();
    if (selected) cy.getElementById(selected).select();
  }, [selected, view]);

  return <div className="class-graph" ref={container} />;
}

function elements(index: GraphIndex, view: ClassViewModel): ElementDefinition[] {
  const result: ElementDefinition[] = [];
  const modules = new Set<string>();
  const classNode = (id: string, outside: boolean) => {
    const node = index.nodes.get(id)!;
    const module = outside ? undefined : (index.moduleOf(id) ?? undefined);
    if (module) modules.add(module);
    const label = outside ? `${node.qualname}` : classLabel(index, node);
    const lines = label.split("\n");
    result.push({
      data: {
        id,
        parent: module,
        label,
        color: index.color(node),
        w: Math.min(320, 24 + Math.max(...lines.map((l) => l.length)) * 6.2),
        h: 14 + lines.length * 14,
      },
      classes: outside ? "class outside" : "class",
    });
  };
  view.classes.forEach((n) => classNode(n.id, false));
  view.outside.forEach((n) => classNode(n.id, true));
  for (const id of modules) {
    const node = index.nodes.get(id)!;
    result.push({ data: { id, label: node.qualname, color: index.color(node) }, classes: "module" });
  }
  const shown = new Set([...view.classes, ...view.outside].map((n) => n.id));
  for (const [source, target] of view.edges) {
    if (shown.has(source) && shown.has(target)) {
      result.push({ data: { id: `x:${source}>${target}`, source, target } });
    }
  }
  return result;
}
