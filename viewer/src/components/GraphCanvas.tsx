import cytoscape, { type Core, type ElementDefinition, type NodeSingular } from "cytoscape";
import elk from "cytoscape-elk";
import { useEffect, useMemo, useRef } from "react";
import { isLibrary, type GraphIndex } from "../model/graphIndex";
import { computeView, unitOf, type View } from "../model/view";
import { useStore } from "../store";
import { GRAPH_STYLE } from "./graphStyle";

cytoscape.use(elk);

const LAYOUT = {
  name: "elk",
  padding: 40,
  nodeDimensionsIncludeLabels: true,
  elk: {
    algorithm: "layered",
    "elk.direction": "RIGHT",
    "elk.hierarchyHandling": "INCLUDE_CHILDREN",
    "elk.layered.spacing.nodeNodeBetweenLayers": 70,
    "elk.spacing.nodeNode": 18,
    "elk.padding": "[top=34,left=16,bottom=16,right=16]",
  },
};

export function GraphCanvas() {
  const container = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const index = useStore((s) => s.index)!;
  const expanded = useStore((s) => s.expanded);
  const showExternal = useStore((s) => s.showExternal);
  const showWeak = useStore((s) => s.showWeak);
  const showCycles = useStore((s) => s.showCycles);
  const selected = useStore((s) => s.selected);
  const fitRequest = useStore((s) => s.fitRequest);
  const focusRequest = useStore((s) => s.focusRequest);

  const options = useMemo(() => ({ expanded, showExternal, showWeak }), [expanded, showExternal, showWeak]);
  const view = useMemo(() => computeView(index, options), [index, options]);
  // The visible node that represents the selection (a symbol shows as its module).
  const selectedUnit = useMemo(() => {
    const module = selected ? (index.moduleOf(selected) ?? selected) : null;
    return module ? unitOf(index, module, options) : null;
  }, [index, options, selected]);

  const selectedUnitRef = useRef(selectedUnit);
  selectedUnitRef.current = selectedUnit;
  const layoutRunning = useRef(false);
  const lastFit = useRef(-1);
  const lastFocus = useRef(0);

  useEffect(() => {
    const cy = cytoscape({
      container: container.current,
      style: GRAPH_STYLE,
      wheelSensitivity: 0.25,
      minZoom: 0.05,
      maxZoom: 3,
    });
    const { select, toggle } = useStore.getState();
    cy.on("tap", "node", (e) => select(e.target.id()));
    cy.on("tap", (e) => {
      if (e.target === cy) select(null);
    });
    cy.on("dbltap", "node", (e) => toggle(e.target.id()));
    cy.on("mouseover", "node", (e) => highlight(cy, e.target));
    cy.on("mouseout", "node", () => cy.elements().removeClass("faded hl"));
    cyRef.current = cy;
    return () => cy.destroy();
  }, []);

  // Rebuild and lay out whenever the visible structure changes.
  useEffect(() => {
    const cy = cyRef.current!;
    cy.batch(() => {
      cy.elements().remove();
      cy.add(elements(index, view));
    });
    // Keep the viewport on large graphs unless a refit was asked for.
    const fit = lastFit.current !== fitRequest || cy.nodes().length < 60;
    lastFit.current = fitRequest;
    const layout = cy.layout({ ...LAYOUT, fit } as cytoscape.LayoutOptions);
    layoutRunning.current = true;
    layout.one("layoutstop", () => {
      layoutRunning.current = false;
      const focus = useStore.getState().focusRequest;
      syncSelection(cy, selectedUnitRef.current, focus !== lastFocus.current);
      lastFocus.current = focus;
    });
    layout.run();
  }, [index, view, fitRequest]);

  useEffect(() => {
    const edges = cyRef.current!.edges();
    edges.removeClass("cycle");
    if (showCycles) edges.filter("[?cyclic]").addClass("cycle");
  }, [view, showCycles]);

  useEffect(() => {
    if (!layoutRunning.current) syncSelection(cyRef.current!, selectedUnit, false);
  }, [selectedUnit]);

  // A reveal that did not change the view still has to move the camera.
  useEffect(() => {
    if (layoutRunning.current || focusRequest === lastFocus.current) return;
    lastFocus.current = focusRequest;
    syncSelection(cyRef.current!, selectedUnitRef.current, true);
  }, [focusRequest]);

  return <div id="cy" ref={container} />;
}

function elements(index: GraphIndex, view: View): ElementDefinition[] {
  const compounds = new Set(view.compounds);
  const parentOf = (id: string) => {
    const parent = index.nodes.get(id)?.parent;
    return parent && compounds.has(parent) ? parent : undefined;
  };
  const maxCount = Math.max(1, ...view.edges.map((e) => e.count));
  const result: ElementDefinition[] = [];

  for (const id of view.compounds) {
    const node = index.nodes.get(id)!;
    result.push({
      data: { id, parent: parentOf(id), label: node.qualname, color: index.color(node) },
      classes: "compound",
    });
  }
  for (const id of view.units) {
    const node = index.nodes.get(id)!;
    const collapsed = node.kind === "package";
    const label = collapsed
      ? `${node.name}\n${index.moduleCount(id)} modules`
      : node.kind === "module" && parentOf(id)
        ? node.name
        : node.qualname;
    const loc = node.metrics?.loc ?? 0;
    const classes = [collapsed ? "collapsed" : isLibrary(node) ? "lib" : "module"];
    if (index.parseErrors.has(id)) classes.push("error");
    result.push({
      data: {
        id,
        parent: parentOf(id),
        label,
        color: index.color(node),
        w: Math.min(240, 40 + label.split("\n")[0].length * 7.2),
        h: collapsed ? 46 : 28 + Math.min(14, Math.sqrt(loc) / 2),
      },
      classes: classes.join(" "),
    });
  }
  for (const e of view.edges) {
    result.push({
      data: {
        id: `e:${e.source}\u0000${e.target}`,
        source: e.source,
        target: e.target,
        cyclic: e.cyclic,
        width: 1 + 3 * Math.sqrt(e.count / maxCount),
      },
      classes: e.weak ? "weak" : "",
    });
  }
  return result;
}

function highlight(cy: Core, node: NodeSingular) {
  if (node.hasClass("compound")) return;
  const hood = node.closedNeighborhood();
  cy.elements().not(hood).not(hood.ancestors()).addClass("faded");
  node.connectedEdges().addClass("hl");
}

function syncSelection(cy: Core, unit: string | null, center: boolean) {
  cy.$(":selected").unselect();
  if (!unit) return;
  const element = cy.getElementById(unit);
  if (element.empty()) return;
  element.select();
  if (center) cy.animate({ center: { eles: element }, zoom: Math.max(cy.zoom(), 0.9) }, { duration: 300 });
}
