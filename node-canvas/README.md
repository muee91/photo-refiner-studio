# Photo Refiner Node Canvas alpha

Standalone local UI for `feat/node-canvas-v3`. It does not depend on MCP Widget mounting.

Run from the repository:

```bash
python3 node-canvas/serve_node_canvas.py
```

Open:

```text
http://127.0.0.1:8765/node-canvas/
```

Current alpha supports:

- six high-level Photo Refiner nodes;
- draggable node positions with live SVG connections;
- Starryear catalog loaded from the existing bundled v2.3 catalog;
- Look A `direction-only` vs `look-master` semantics;
- direct-effect vs original-assembly;
- automatic normal / creative-safe / disabled recovery policy;
- source-count validation;
- import of current settings JSON;
- graph validation, execution-plan preview, and `graph.json` export.

The browser plan is an interaction preview only. `skill/scripts/validate_graph.py` and `compile_graph_plan.py` are authoritative.
