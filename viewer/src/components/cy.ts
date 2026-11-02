import cytoscape from "cytoscape";
import elk from "cytoscape-elk";

// Register layouts once for every graph component.
cytoscape.use(elk);

export { cytoscape };
