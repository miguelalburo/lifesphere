#!/usr/bin/env python3
"""Generate an interactive HTML visualisation of the live LifeSphere KG schema.

Reads ``config/schema_config.yaml`` — the BioCypher ontology, the single live
source that spans the clinical, omics, single-cell and reference layers — builds
the node/edge graph, colours each node by the layer it sits in relative to the
backbone (``Program -> Project -> Subject -> {clinical, biospecimen} -> omics /
single-cell``), and writes a self-contained page (vis-network via CDN):

  * every node and edge is labelled;
  * nodes are coloured by layer, with a legend;
  * clicking a node opens its id + documented properties in a side panel.

Pure standard library (no pyvis / PyYAML): the YAML is parsed line-wise so the
``# props:`` comment hints — which real YAML parsers discard — are preserved.
Node layers are seeded from the known backbone anchors and then filled in by
graph reachability, so a newly added node is auto-classified by what it links to.

    python3 scripts/visualise.schema.py [--config PATH] [--out PATH]
"""

import argparse
import html
import json
import re
from collections import defaultdict, deque
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent

# Top-level block header: ``key:`` at column 0, tolerating a trailing # comment.
_HEADER = re.compile(r"^([A-Za-z][\w ]*?):\s*(?:#.*)?$")
# Indented ``key: value`` field line inside a block.
_FIELD = re.compile(r"^\s+([A-Za-z_]\w*):\s*(.*?)\s*$")
# The ``# props:`` documentation comment (and its continuation lines).
_PROPS = re.compile(r"^\s*#\s*props:\s*(.*?)\s*$")
_COMMENT = re.compile(r"^\s*#\s?(.*?)\s*$")

_KNOWN_FIELDS = {"represented_as", "is_a", "input_label", "preferred_id",
                 "source", "target", "properties"}

# Backbone anchors -> layer. Everything else is filled in by reachability BFS.
_SEEDS = {
    "Program": "backbone", "Project": "backbone", "Subject": "backbone",
    "Diagnosis": "clinical", "Treatment": "clinical", "PathologyDetail": "clinical",
    "FollowUp": "clinical", "MolecularTest": "clinical", "Exposure": "clinical",
    "FamilyHistory": "clinical",
    "Sample": "biospecimen", "ExperimentalGroup": "biospecimen",
    "Gene": "omics", "CpGSite": "omics", "Variant": "omics", "Protein": "omics",
    "Pathway": "omics", "Expression": "omics", "Methylation": "omics",
    "VariantCall": "omics", "ProteinExpression": "omics",
    "Assay": "singlecell", "Cell": "singlecell", "CellSet": "singlecell",
    "CellType": "singlecell", "CellState": "singlecell", "TissueRegion": "singlecell",
    "PseudobulkExpression": "singlecell",
    "Disease": "reference", "ProcessedDataOutput": "reference",
}

# layer -> (legend label, colour). Order here is the legend order.
_LAYERS = {
    "backbone": ("Backbone · Program→Project→Subject", "#1f4e79"),
    "clinical": ("Clinical · Subject branch", "#2e8b74"),
    "biospecimen": ("Biospecimen · Sample branch", "#e0851e"),
    "omics": ("Omics · measurements & features", "#7b52ab"),
    "singlecell": ("Single-cell / spatial", "#c94f9b"),
    "reference": ("Reference / provenance", "#6c7a89"),
    "other": ("Other (unanchored)", "#9aa0a6"),
}


def _strip_comment(value: str) -> str:
    return value.split("#", 1)[0].strip()


def _split_list(value: str) -> list[str]:
    """Parse a scalar or ``[a, b, c]`` YAML flow list into class names."""
    value = value.strip().strip("[]")
    return [x.strip() for x in value.split(",") if x.strip()]


def _split_props(prop_lines: list[str]) -> list[str]:
    """Split the joined ``# props:`` hint on top-level commas (commas nested inside
    ``(...)`` / ``[...]`` stay with their property, e.g. a parenthesised sublist)."""
    text = " ".join(line.strip() for line in prop_lines if line.strip()).strip()
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    for ch in text:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def parse_schema(path: Path) -> tuple[dict, list]:
    """Return ({class_key: node_dict}, [edge_dict]) parsed from schema_config.yaml."""
    blocks: list[dict] = []
    cur: dict | None = None
    in_props = False

    for raw in path.read_text().splitlines():
        if not raw.startswith("#") and (m := _HEADER.match(raw)):
            cur = {"key": m.group(1).strip(), "fields": {}, "props": [], "extra": {}}
            blocks.append(cur)
            in_props = False
            continue
        if cur is None:
            continue
        if fm := _FIELD.match(raw):
            key, val = fm.group(1), _strip_comment(fm.group(2))
            (cur["fields"] if key in _KNOWN_FIELDS else cur["extra"])[key] = val
            in_props = False
            continue
        if pm := _PROPS.match(raw):
            cur["props"].append(pm.group(1))
            in_props = True
            continue
        if in_props and (cm := _COMMENT.match(raw)):
            cur["props"].append(cm.group(1))  # continuation of the props comment
            continue
        in_props = False

    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    for b in blocks:
        kind = b["fields"].get("represented_as")
        if kind == "node":
            nodes[b["key"]] = {
                "label": b["fields"].get("input_label", b["key"]),
                "id": b["fields"].get("preferred_id", ""),
                "props": _split_props(b["props"]),
            }
        elif kind == "edge":
            edges.append({
                "label": b["fields"].get("input_label", b["key"]),
                "sources": _split_list(b["fields"].get("source", "")),
                "targets": _split_list(b["fields"].get("target", "")),
                "props": list(b["extra"].keys()),
            })
    return nodes, edges


def classify(labels: set[str], adjacency: dict[str, set]) -> dict[str, str]:
    """Assign each node label to a layer: seeded anchors first, then nearest-seed BFS."""
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


def build(nodes: dict, edges: list) -> tuple[list, list, dict, set]:
    label_of = {key: n["label"] for key, n in nodes.items()}
    adjacency: dict[str, set] = defaultdict(set)
    edge_rows: list[tuple[str, str, str, list]] = []
    for e in edges:
        for s in e["sources"]:
            for t in e["targets"]:
                sl, tl = label_of.get(s), label_of.get(t)
                if not sl or not tl:
                    continue
                edge_rows.append((sl, tl, e["label"], e["props"]))
                adjacency[sl].add(tl)
                adjacency[tl].add(sl)

    labels = set(label_of.values())
    for lbl in labels:
        adjacency.setdefault(lbl, set())
    layer = classify(labels, adjacency)

    vis_nodes, node_info = [], {}
    for n in nodes.values():
        lbl = n["label"]
        name, colour = _LAYERS[layer[lbl]]
        vis_nodes.append({
            "id": lbl, "label": lbl, "shape": "dot", "size": 18,
            "color": {"background": colour, "border": "#20232a",
                      "highlight": {"background": colour, "border": "#000"}},
        })
        node_info[lbl] = {"layer": name, "colour": colour,
                          "id_prop": n["id"], "props": n["props"]}

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
    <div class="sub">Live from <code>config/schema_config.yaml</code>.<br>
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


def render(vis_nodes, vis_edges, node_info, present) -> str:
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
    ap.add_argument("--config", type=Path, default=_REPO / "config" / "schema_config.yaml",
                    help="Path to the live BioCypher ontology (schema_config.yaml)")
    ap.add_argument("--out", type=Path, default=_REPO / "docs" / "schema_graph.html",
                    help="Output HTML path (default: docs/schema_graph.html)")
    args = ap.parse_args(argv)

    if not args.config.exists():
        ap.error(f"config not found: {args.config}")

    nodes, edges = parse_schema(args.config)
    vis_nodes, vis_edges, node_info, present = build(nodes, edges)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(vis_nodes, vis_edges, node_info, present))

    layers = ", ".join(sorted(present))
    print(f"Wrote {args.out}")
    print(f"  {len(vis_nodes)} nodes, {len(vis_edges)} edges; layers: {layers}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
