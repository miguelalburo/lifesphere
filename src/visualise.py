"""Generate an interactive HTML visualisation of the live LifeSphere KG schema.

Usage: python -m src.visualise [--config-dir PATH] [--out PATH]

Reads ``config/schema/nodes.yaml`` + ``config/schema/edges.yaml`` via the
shared :func:`src.schema.load_schema` loader, builds the node/edge graph,
colours each node by the layer it sits in relative to the backbone
(``Program → Study → Subject → {clinical, biospecimen} → omics / single-cell``),
and writes a self-contained page (vis-network via CDN):

  * every node and edge is labelled;
  * nodes are coloured by layer, with a legend;
  * clicking a node opens its id + documented properties in a side panel.

Node layers are seeded from the known backbone anchors and then filled in by
graph reachability, so a newly added node is auto-classified by what it links to.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path

try:
    from . import PROJECT_ROOT
    from .schema import load_schema, Schema
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from src import PROJECT_ROOT
    from src.schema import load_schema, Schema

# Backbone anchors → layer.  Everything else is filled in by nearest-seed BFS.
_SEEDS: dict[str, str] = {
    # backbone
    "Program": "backbone", "Study": "backbone", "Subject": "backbone",
    # clinical
    "Diagnosis": "clinical", "Condition": "clinical", "PathologyDetail": "clinical",
    "Survival": "clinical", "PhenotypeObservation": "clinical",
    # biospecimen
    "Sample": "biospecimen", "Assay": "biospecimen", "LibraryPreparation": "biospecimen",
    # omics
    "Gene": "omics", "CpGSite": "omics", "Variant": "omics",
    "Protein": "omics", "Pathway": "omics", "Metabolite": "omics",
    "ExpressionObservation": "omics", "MethylationObservation": "omics",
    "VariantObservation": "omics", "ProteinObservation": "omics",
    "MetaboliteObservation": "omics", "GenomicRegion": "omics",
    "RegulatoryElement": "omics",
    # single-cell
    "CellSet": "singlecell", "CellType": "singlecell", "CellState": "singlecell",
    "SingleCellDataset": "singlecell", "Repository": "singlecell", "Feature": "singlecell",
    # intervention / perturbation
    "Intervention": "intervention", "ChemicalEntity": "intervention",
    "Procedure": "intervention", "Perturbation": "intervention",
    # reference / provenance
    "Evidence": "reference",
    "MethylationStatusRule": "reference", "Publication": "reference",
    "Organism": "reference",
}

# layer → (legend label, colour).  Order here is the legend order.
_LAYERS: dict[str, tuple[str, str]] = {
    "backbone":     ("Backbone · Program→Study→Subject",      "#1f4e79"),
    "clinical":     ("Clinical · Subject branch",              "#2e8b74"),
    "biospecimen":  ("Biospecimen · Sample branch",            "#e0851e"),
    "omics":        ("Omics · measurements & features",        "#7b52ab"),
    "singlecell":   ("Single-cell / spatial",                  "#c94f9b"),
    "intervention": ("Intervention / perturbation",            "#c0392b"),
    "reference":    ("Reference / provenance",                 "#6c7a89"),
    "other":        ("Other (unanchored)",                     "#9aa0a6"),
}


def _classify(labels: set[str], adjacency: dict[str, set]) -> dict[str, str]:
    """Assign each node label to a layer: seeded anchors first, then BFS from nearest seed."""
    layer: dict[str, str] = {}
    queue: deque[str] = deque()
    for lbl in labels:
        if lbl in _SEEDS:
            layer[lbl] = _SEEDS[lbl]
            queue.append(lbl)
    while queue:
        u = queue.popleft()
        for v in adjacency[u]:
            if v not in layer:
                layer[v] = layer[u]
                queue.append(v)
    for lbl in labels:
        layer.setdefault(lbl, "other")
    return layer


def build(schema: Schema) -> tuple[list, list, dict, set]:
    adjacency: dict[str, set] = defaultdict(set)
    edge_rows: list[tuple[str, str, str, list]] = []

    for type_, edge in schema.edges.items():
        for source_label, target_label in edge.pairs:
            edge_rows.append((source_label, target_label, type_, list(edge.properties)))
            adjacency[source_label].add(target_label)
            adjacency[target_label].add(source_label)

    labels = set(schema.nodes)
    for lbl in labels:
        adjacency.setdefault(lbl, set())

    layer = _classify(labels, adjacency)

    vis_nodes: list[dict] = []
    node_info: dict[str, dict] = {}
    for label, node in schema.nodes.items():
        name, colour = _LAYERS[layer[label]]
        vis_nodes.append({
            "id": label, "label": label, "shape": "dot", "size": 18,
            "color": {"background": colour, "border": "#20232a",
                      "highlight": {"background": colour, "border": "#000"}},
        })
        node_info[label] = {
            "layer": name,
            "colour": colour,
            "id_prop": node.id,
            "props": list(node.properties),
        }

    vis_edges = [{
        "from": sl, "to": tl, "label": el, "arrows": "to",
        "title": el + (f"  {{{', '.join(props)}}}" if props else ""),
    } for sl, tl, el, props in edge_rows]

    present = {layer[lbl] for lbl in labels}
    return vis_nodes, vis_edges, node_info, present


_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>LifeSphere KG — live schema</title>
<script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
<style>
  html,body{margin:0;height:100%;font-family:-apple-system,Segoe UI,Roboto,Helvetica,sans-serif;}
  #wrap{display:flex;height:100vh;}
  #graph{flex:1;height:100%;background:#fafbfc;}
  #panel{width:330px;box-sizing:border-box;padding:16px 18px;border-left:1px solid #e3e6ea;
         overflow:auto;background:#fff;}
  #panel h1{font-size:15px;margin:0 0 4px;color:#111;}
  #panel .sub{color:#666;font-size:12px;margin-bottom:16px;line-height:1.4;}
  .leg{display:flex;align-items:center;font-size:12px;margin:4px 0;color:#333;}
  .sw{width:12px;height:12px;border-radius:50%;margin-right:8px;border:1px solid rgba(0,0,0,.25);flex:none;}
  #sel{border-top:1px solid #eee;margin-top:14px;padding-top:14px;}
  .badge{display:inline-block;padding:2px 9px;border-radius:11px;color:#fff;font-size:11px;margin-bottom:8px;}
  #sel h2{font-size:17px;margin:6px 0;color:#111;}
  .idp{font-size:12px;color:#444;margin-bottom:12px;}
  #sel ul{margin:6px 0;padding-left:18px;}
  #sel li{font-size:12.5px;margin:3px 0;color:#333;}
  .muted{color:#999;font-size:12px;}
  .lbl{font-size:12px;color:#666;margin-bottom:2px;text-transform:uppercase;letter-spacing:.04em;}
  code{background:#f2f3f5;padding:1px 5px;border-radius:4px;font-size:12px;}
</style>
</head>
<body>
<div id="wrap">
  <div id="graph"></div>
  <div id="panel">
    <h1>LifeSphere KG schema</h1>
    <div class="sub">Live from <code>config/schema/nodes.yaml</code> + <code>edges.yaml</code>.<br>
      Click a node for its properties · double-click to zoom · drag to reposition.</div>
    <div class="lbl">Layers</div>
    <div id="legend"><!--LEGEND--></div>
    <div id="sel"><div class="muted">No node selected — click one in the graph.</div></div>
  </div>
</div>
<script>
const NODES = /*NODES*/, EDGES = /*EDGES*/, NODE_INFO = /*NODEINFO*/;
const network = new vis.Network(
  document.getElementById('graph'),
  {nodes: new vis.DataSet(NODES), edges: new vis.DataSet(EDGES)},
  {
    nodes:{shape:'dot', size:18, borderWidth:2,
           font:{size:14, color:'#1a1a1a', face:'Segoe UI'}},
    edges:{arrows:{to:{enabled:true, scaleFactor:0.6}},
           color:{color:'#b9c0c8', highlight:'#6c7a89'},
           font:{size:11, color:'#555', strokeWidth:4, strokeColor:'#fafbfc', align:'middle'},
           smooth:{enabled:true, type:'dynamic'}},
    physics:{barnesHut:{gravitationalConstant:-9000, springLength:170, springConstant:0.04},
             stabilization:{iterations:250}},
    interaction:{hover:true, tooltipDelay:120}
  }
);
function esc(s){return (s||'').replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
function showNode(id){
  const info = NODE_INFO[id]; if(!info) return;
  let h = '<span class="badge" style="background:'+info.colour+'">'+esc(info.layer)+'</span>';
  h += '<h2>'+esc(id)+'</h2>';
  h += '<div class="idp">id · <code>'+esc(info.id_prop||'—')+'</code></div>';
  if(info.props && info.props.length){
    h += '<div class="lbl">Properties</div><ul>';
    info.props.forEach(p => { h += '<li>'+esc(p)+'</li>'; });
    h += '</ul>';
  } else {
    h += '<div class="muted">No documented properties.</div>';
  }
  document.getElementById('sel').innerHTML = h;
}
network.on('click', p => { if(p.nodes.length) showNode(p.nodes[0]); });
network.on('doubleClick', p => { if(p.nodes.length) network.focus(p.nodes[0], {scale:1.3, animation:true}); });
</script>
</body>
</html>
"""


def _render(vis_nodes: list, vis_edges: list, node_info: dict, present: set) -> str:
    legend = "".join(
        f'<div class="leg"><span class="sw" style="background:{colour}"></span>'
        f'{html.escape(name)}</div>'
        for layer, (name, colour) in _LAYERS.items() if layer in present
    )
    return (_HTML
            .replace("/*NODES*/", json.dumps(vis_nodes))
            .replace("/*EDGES*/", json.dumps(vis_edges))
            .replace("/*NODEINFO*/", json.dumps(node_info))
            .replace("<!--LEGEND-->", legend))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config-dir", type=Path, default=None,
                    help="Config directory containing schema/ (default: config/)")
    ap.add_argument("--out", type=Path, default=None,
                    help="Output HTML path (default: docs/schema_graph_<YYYYMMDD_HHMMSS>.html)")
    args = ap.parse_args(argv)

    purge_previous = args.out is None
    if args.out is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.out = PROJECT_ROOT / "docs" / f"schema_graph_{stamp}.html"

    schema = load_schema(args.config_dir)
    vis_nodes, vis_edges, node_info, present = build(schema)

    if purge_previous:
        for stale in sorted(args.out.parent.glob("schema_graph*.html")):
            if stale != args.out:
                stale.unlink()
                print(f"Removed previous {stale.name}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(_render(vis_nodes, vis_edges, node_info, present))

    layers = ", ".join(sorted(present))
    print(f"Wrote {args.out}")
    print(f"  {len(vis_nodes)} nodes, {len(vis_edges)} edges; layers: {layers}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
