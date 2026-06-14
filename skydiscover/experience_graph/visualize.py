"""
ExperienceGraph visualizer.

Reads experience_graph_events.jsonl and snapshot files from an output directory,
generates a self-contained HTML file for interactive exploration of the tree
and score timeline.

Usage:
    python -m skydiscover.experience_graph.visualize <output_dir> [--out viz.html]
    python -m skydiscover.experience_graph.visualize ./my_run
    python -m skydiscover.experience_graph.visualize ./my_run --out graph_viz.html
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional


# ── Data loading ──────────────────────────────────────────────────────────────


def load_events(output_dir: str) -> List[Dict[str, Any]]:
    path = os.path.join(output_dir, "experience_graph_events.jsonl")
    if not os.path.exists(path):
        return []
    events = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return events


def load_snapshots(output_dir: str) -> List[Dict[str, Any]]:
    snap_dir = os.path.join(output_dir, "experience_graph_snapshots")
    if not os.path.isdir(snap_dir):
        return []
    snapshots = []
    for fpath in sorted(glob.glob(os.path.join(snap_dir, "snapshot_*.json"))):
        try:
            with open(fpath) as f:
                snapshots.append(json.load(f))
        except Exception:
            continue
    return snapshots


def compute_stats(events: List[Dict], snapshots: List[Dict]) -> Dict[str, Any]:
    insert_events = [e for e in events if e.get("event_type") == "insert"]
    summarize_events = [e for e in events if e.get("event_type") == "summarize"]

    best_score: Optional[float] = None
    total_pb = 0
    for e in insert_events:
        s = e.get("score")
        if s is not None:
            if best_score is None or s > best_score:
                best_score = s
        if e.get("is_paradigm_breakthrough"):
            total_pb += 1

    n_leaves = insert_events[-1].get("total_leaves", 0) if insert_events else 0
    n_paradigms = snapshots[-1].get("tree", {}).get("children", []) if snapshots else []
    n_paradigms = len(n_paradigms)

    return {
        "total_leaves": n_leaves,
        "total_paradigm_branches": n_paradigms,
        "total_paradigm_breakthrough": total_pb,
        "best_score": best_score,
        "n_summarize_events": len(summarize_events),
    }


# ── HTML generation ───────────────────────────────────────────────────────────


def build_html(
    events: List[Dict],
    snapshots: List[Dict],
    stats: Dict[str, Any],
    output_dir: str,
) -> str:
    data_json = json.dumps(
        {"events": events, "snapshots": snapshots, "stats": stats},
        default=str,
    )

    best_score_str = (
        f"{stats['best_score']:.4f}" if stats.get("best_score") is not None else "N/A"
    )
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ExperienceGraph Visualizer</title>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<script src="https://d3js.org/d3.v7.min.js"></script>
<style>
  :root {{
    --bg: #f0f2f5; --bg2: #ffffff; --bg3: #e8ecf0;
    --text: #1f2328; --text-dim: #656d76;
    --border: #d0d7de; --shadow: rgba(0,0,0,0.08);
    --accent: #0969da; --green: #1a7f37; --orange: #bc4c00;
    --purple: #8250df; --cyan: #0598c1; --red: #cf222e;
    --paradigm: #0969da; --formulation: #1a7f37;
    --mechanism: #bc4c00; --leaf-normal: #656d76;
    --leaf-pb: #8250df;
  }}
  [data-theme="dark"] {{
    --bg: #0d1117; --bg2: #161b22; --bg3: #21262d;
    --text: #e6edf3; --text-dim: #7d8590;
    --border: #30363d; --shadow: rgba(0,0,0,0.3);
    --accent: #58a6ff; --green: #3fb950; --orange: #d29922;
    --purple: #bc8cff; --cyan: #56d4dd; --red: #ff7b72;
    --paradigm: #58a6ff; --formulation: #3fb950;
    --mechanism: #d29922; --leaf-normal: #7d8590;
    --leaf-pb: #bc8cff;
  }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:'Segoe UI',system-ui,-apple-system,sans-serif;
          background:var(--bg); color:var(--text); min-height:100vh; }}
  header {{ background:var(--bg2); border-bottom:1px solid var(--border);
            padding:12px 20px; display:flex; align-items:center; gap:16px; }}
  header h1 {{ font-size:16px; font-weight:600; }}
  header .meta {{ font-size:12px; color:var(--text-dim); margin-left:auto; }}
  .theme-btn {{ cursor:pointer; background:var(--bg3); border:1px solid var(--border);
                border-radius:6px; padding:4px 10px; font-size:12px; color:var(--text); }}
  .stats-bar {{ display:flex; gap:0; background:var(--bg2);
                border-bottom:1px solid var(--border); }}
  .stat {{ flex:1; padding:10px 16px; border-right:1px solid var(--border); text-align:center; }}
  .stat:last-child {{ border-right:none; }}
  .stat-val {{ font-size:20px; font-weight:700; color:var(--accent); }}
  .stat-lbl {{ font-size:11px; color:var(--text-dim); margin-top:2px; }}
  .main {{ display:grid; grid-template-columns:1fr 1fr; height:calc(100vh - 160px); gap:0; }}
  .panel {{ overflow:hidden; border-right:1px solid var(--border); }}
  .panel:last-child {{ border-right:none; }}
  .panel-hdr {{ padding:8px 14px; font-size:12px; font-weight:600;
                background:var(--bg3); border-bottom:1px solid var(--border);
                display:flex; align-items:center; gap:8px; }}
  .panel-body {{ height:calc(100% - 34px); overflow:hidden; position:relative; }}
  #timeline-chart {{ width:100%; height:100%; }}
  #tree-container {{ width:100%; height:100%; overflow:auto; }}
  svg#tree-svg {{ min-width:100%; }}
  .bottom-bar {{ background:var(--bg2); border-top:1px solid var(--border);
                 padding:8px 16px; display:flex; align-items:center; gap:12px; }}
  .bottom-bar label {{ font-size:12px; color:var(--text-dim); }}
  #snap-slider {{ flex:1; cursor:pointer; }}
  #snap-info {{ font-size:12px; color:var(--text-dim); min-width:200px; }}
  .legend {{ display:flex; gap:12px; font-size:11px; color:var(--text-dim);
             margin-left:auto; align-items:center; }}
  .leg-dot {{ width:10px; height:10px; border-radius:50%; display:inline-block; margin-right:3px; }}
  /* D3 tree styles */
  .node circle {{ stroke-width:2px; cursor:pointer; }}
  .node text {{ font-size:11px; fill:var(--text); }}
  .link {{ fill:none; stroke:var(--border); stroke-width:1.5px; }}
  .tooltip {{ position:fixed; background:var(--bg2); border:1px solid var(--border);
              border-radius:6px; padding:8px 10px; font-size:12px; pointer-events:none;
              box-shadow:0 4px 12px var(--shadow); z-index:999; display:none;
              max-width:260px; line-height:1.5; }}
</style>
</head>
<body data-theme="light">

<header>
  <h1>⬡ ExperienceGraph Visualizer</h1>
  <span class="meta">Generated: {generated_at} &nbsp;|&nbsp; {output_dir}</span>
  <button class="theme-btn" onclick="toggleTheme()">🌙 Dark</button>
</header>

<div class="stats-bar">
  <div class="stat"><div class="stat-val" id="s-leaves">{stats['total_leaves']}</div>
    <div class="stat-lbl">Total solutions</div></div>
  <div class="stat"><div class="stat-val" id="s-pars">{stats['total_paradigm_branches']}</div>
    <div class="stat-lbl">Paradigm branches</div></div>
  <div class="stat"><div class="stat-val" id="s-pb">{stats['total_paradigm_breakthrough']}</div>
    <div class="stat-lbl">Paradigm breakthroughs</div></div>
  <div class="stat"><div class="stat-val" id="s-best">{best_score_str}</div>
    <div class="stat-lbl">Best score</div></div>
  <div class="stat"><div class="stat-val" id="s-sums">{stats['n_summarize_events']}</div>
    <div class="stat-lbl">Summarize events</div></div>
</div>

<div class="main">
  <div class="panel">
    <div class="panel-hdr">
      📈 Score Timeline
      <div class="legend" style="margin-left:auto">
        <span><span class="leg-dot" style="background:var(--accent)"></span>Normal</span>
        <span><span class="leg-dot" style="background:var(--leaf-pb)"></span>Paradigm</span>
      </div>
    </div>
    <div class="panel-body"><div id="timeline-chart"></div></div>
  </div>
  <div class="panel">
    <div class="panel-hdr">
      🌳 Exploration Tree
      <div class="legend" style="margin-left:auto">
        <span><span class="leg-dot" style="background:var(--paradigm)"></span>paradigm</span>
        <span><span class="leg-dot" style="background:var(--formulation)"></span>formulation</span>
        <span><span class="leg-dot" style="background:var(--mechanism)"></span>mechanism</span>
        <span><span class="leg-dot" style="background:var(--leaf-pb)"></span>★PB leaf</span>
      </div>
    </div>
    <div class="panel-body"><div id="tree-container"><svg id="tree-svg"></svg></div></div>
  </div>
</div>

<div class="bottom-bar">
  <label>Snapshot:</label>
  <input type="range" id="snap-slider" min="0" max="0" value="0" oninput="onSliderChange(this.value)">
  <span id="snap-info">No snapshots loaded</span>
</div>

<div class="tooltip" id="tooltip"></div>

<script>
const RAW = {data_json};
const events = RAW.events || [];
const snapshots = RAW.snapshots || [];

// ── Theme ────────────────────────────────────────────────────────────────────
function toggleTheme() {{
  const body = document.body;
  const isDark = body.dataset.theme === 'dark';
  body.dataset.theme = isDark ? 'light' : 'dark';
  document.querySelector('.theme-btn').textContent = isDark ? '🌙 Dark' : '☀️ Light';
  renderTimeline();
  if (currentSnap) renderTree(currentSnap.tree);
}}

function cssVar(name) {{
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}}

// ── Timeline ─────────────────────────────────────────────────────────────────
function renderTimeline() {{
  const insertEvts = events.filter(e => e.event_type === 'insert');
  const sumEvts = events.filter(e => e.event_type === 'summarize');

  const normalX = [], normalY = [], normalText = [];
  const pbX = [], pbY = [], pbText = [];

  insertEvts.forEach(e => {{
    const x = e.iteration ?? 0;
    const y = e.score ?? null;
    const txt = [
      `<b>${{e.leaf_label || ''}}</b>`,
      `Action: ${{e.action || ''}}`,
      `Path: ${{(e.placement_path || []).join(' → ')}}`,
      `ID: ${{(e.solution_id || '').slice(0, 8)}}`,
      `Score: ${{y !== null ? y.toFixed(4) : 'N/A'}}`,
    ].join('<br>');
    if (e.is_paradigm_breakthrough) {{
      pbX.push(x); pbY.push(y); pbText.push(txt);
    }} else {{
      normalX.push(x); normalY.push(y); normalText.push(txt);
    }}
  }});

  const bg = cssVar('--bg2');
  const textColor = cssVar('--text');
  const dimColor = cssVar('--text-dim');
  const gridColor = cssVar('--border');
  const accentColor = cssVar('--accent');
  const pbColor = cssVar('--leaf-pb');

  const shapes = sumEvts.map(e => ({{
    type: 'line', xref: 'x', yref: 'paper',
    x0: e.iteration, x1: e.iteration, y0: 0, y1: 1,
    line: {{ color: cssVar('--red'), width: 1.5, dash: 'dot' }},
  }}));

  const annotations = sumEvts.map(e => ({{
    x: e.iteration, y: 1, xref: 'x', yref: 'paper',
    text: '⚡', showarrow: false, font: {{ size: 12 }},
    yanchor: 'bottom',
  }}));

  const traces = [
    {{
      x: normalX, y: normalY, mode: 'markers', name: 'Normal',
      marker: {{ color: accentColor, size: 5, opacity: 0.7 }},
      text: normalText, hoverinfo: 'text',
    }},
    {{
      x: pbX, y: pbY, mode: 'markers', name: 'Paradigm BT',
      marker: {{ color: pbColor, size: 8, symbol: 'star', opacity: 0.9 }},
      text: pbText, hoverinfo: 'text',
    }},
  ];

  const layout = {{
    paper_bgcolor: bg, plot_bgcolor: bg,
    font: {{ color: textColor, size: 11 }},
    xaxis: {{ title: 'Iteration', gridcolor: gridColor, zeroline: false }},
    yaxis: {{ title: 'Score', gridcolor: gridColor, zeroline: false }},
    legend: {{ bgcolor: bg, bordercolor: gridColor, borderwidth: 1 }},
    margin: {{ l: 50, r: 20, t: 20, b: 40 }},
    shapes, annotations,
    hovermode: 'closest',
  }};

  Plotly.react('timeline-chart', traces, layout, {{ responsive: true, displayModeBar: false }});
}}

// ── Snapshot slider ───────────────────────────────────────────────────────────
let currentSnap = null;

function initSlider() {{
  const slider = document.getElementById('snap-slider');
  if (snapshots.length === 0) {{
    document.getElementById('snap-info').textContent = 'No snapshots available';
    return;
  }}
  slider.max = snapshots.length - 1;
  slider.value = snapshots.length - 1;
  onSliderChange(snapshots.length - 1);
}}

function onSliderChange(idx) {{
  idx = parseInt(idx);
  if (idx < 0 || idx >= snapshots.length) return;
  currentSnap = snapshots[idx];
  const info = document.getElementById('snap-info');
  info.textContent = (
    `#${{idx + 1}}/${{snapshots.length}} | `
    + `iter ${{currentSnap.iteration}} | `
    + `${{currentSnap.total_leaves}} leaves | `
    + `trigger: ${{currentSnap.trigger}}`
  );
  renderTree(currentSnap.tree);
}}

// ── D3 tree ───────────────────────────────────────────────────────────────────
const NODE_COLORS = {{
  root: () => cssVar('--text-dim'),
  paradigm: () => cssVar('--paradigm'),
  formulation: () => cssVar('--formulation'),
  mechanism: () => cssVar('--mechanism'),
  leaf_normal: () => cssVar('--leaf-normal'),
  leaf_pb: () => cssVar('--leaf-pb'),
}};

function nodeColor(d) {{
  const n = d.data;
  if (n.node_type === 'root') return NODE_COLORS.root();
  if (n.node_type === 'leaf') return n.is_paradigm_breakthrough ? NODE_COLORS.leaf_pb() : NODE_COLORS.leaf_normal();
  return NODE_COLORS[n.field_name] ? NODE_COLORS[n.field_name]() : cssVar('--text-dim');
}}

function nodeRadius(d) {{
  const n = d.data;
  if (n.node_type === 'root') return 8;
  if (n.node_type === 'leaf') {{
    const s = n.score;
    if (s === null || s === undefined) return 4;
    return 4 + Math.min(8, s * 10);
  }}
  return 7;
}}

function renderTree(treeData) {{
  const container = document.getElementById('tree-container');
  const svg = d3.select('#tree-svg');
  svg.selectAll('*').remove();

  if (!treeData) return;

  const root = d3.hierarchy(treeData, d => d.children || []);

  // Toggle children on click (collapse/expand)
  root.descendants().forEach(d => {{
    if (d.depth > 0) {{ d._children = d.children; }}
  }});

  function update(source) {{
    const treeLayout = d3.tree().nodeSize([26, 180]);
    treeLayout(root);

    const nodes = root.descendants();
    const links = root.links();

    // Compute extents
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    nodes.forEach(n => {{
      if (n.x < minX) minX = n.x;
      if (n.x > maxX) maxX = n.x;
      if (n.y < minY) minY = n.y;
      if (n.y > maxY) maxY = n.y;
    }});

    const W = Math.max(container.clientWidth, (maxY - minY) + 240);
    const H = Math.max(400, (maxX - minX) + 60);
    svg.attr('width', W).attr('height', H);

    const g = svg.append('g')
      .attr('transform', `translate(${{-minY + 40}}, ${{-minX + 30}})`);

    // Links
    g.selectAll('.link').data(links).join('path')
      .attr('class', 'link')
      .attr('d', d3.linkHorizontal().x(d => d.y).y(d => d.x));

    // Nodes
    const node = g.selectAll('.node').data(nodes).join('g')
      .attr('class', 'node')
      .attr('transform', d => `translate(${{d.y}},${{d.x)}}`)
      .on('click', (evt, d) => {{
        if (d._children) {{ d.children = d._children; d._children = null; }}
        else {{ d._children = d.children; d.children = null; }}
        update(d);
      }})
      .on('mouseover', (evt, d) => showTooltip(evt, d))
      .on('mousemove', (evt) => moveTooltip(evt))
      .on('mouseout', hideTooltip);

    node.append('circle')
      .attr('r', d => nodeRadius(d))
      .attr('fill', d => nodeColor(d))
      .attr('stroke', d => d3.color(nodeColor(d))?.darker(0.6) || '#333')
      .attr('opacity', 0.85);

    // Star for paradigm breakthrough leaves
    node.filter(d => d.data.node_type === 'leaf' && d.data.is_paradigm_breakthrough)
      .append('text')
      .attr('dy', '0.35em').attr('dx', '-0.35em')
      .attr('font-size', '9px').attr('fill', '#fff').attr('pointer-events', 'none')
      .text('★');

    // Labels
    node.append('text')
      .attr('dy', '0.31em')
      .attr('x', d => (d.children || d._children) ? -11 : 11)
      .attr('text-anchor', d => (d.children || d._children) ? 'end' : 'start')
      .attr('font-size', '11px')
      .text(d => {{
        const lbl = d.data.label || '';
        const suffix = d.data.node_type === 'leaf' && d.data.score !== null && d.data.score !== undefined
          ? ` ${{d.data.score.toFixed(2)}}` : '';
        const collapsed = d._children ? ` [+${{d._children.length}}]` : '';
        return lbl.slice(0, 20) + suffix + collapsed;
      }});
  }}

  update(root);
}}

// ── Tooltip ───────────────────────────────────────────────────────────────────
const tooltip = document.getElementById('tooltip');

function showTooltip(evt, d) {{
  const n = d.data;
  let html = `<b>${{n.label || ''}}</b><br>`;
  html += `Type: ${{n.node_type}}`;
  if (n.field_name) html += ` (${{n.field_name}})`;
  html += '<br>';
  if (n.node_type === 'leaf') {{
    if (n.score !== null && n.score !== undefined) html += `Score: ${{n.score.toFixed(4)}}<br>`;
    if (n.solution_id) html += `ID: ${{n.solution_id.slice(0, 12)}}...<br>`;
    if (n.is_paradigm_breakthrough) html += `<span style="color:var(--leaf-pb)">★ Paradigm Breakthrough</span><br>`;
    if (n.rationale_ref) html += `<span style="color:var(--text-dim);font-size:10px">${{n.rationale_ref.slice(0, 80)}}...</span>`;
  }} else {{
    html += `Children: ${{(n.children || []).length}}`;
  }}
  tooltip.innerHTML = html;
  tooltip.style.display = 'block';
  moveTooltip(evt);
}}

function moveTooltip(evt) {{
  tooltip.style.left = (evt.clientX + 14) + 'px';
  tooltip.style.top = (evt.clientY - 10) + 'px';
}}

function hideTooltip() {{
  tooltip.style.display = 'none';
}}

// ── Init ──────────────────────────────────────────────────────────────────────
renderTimeline();
initSlider();
</script>
</body>
</html>"""


# ── CLI entry point ───────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Visualize ExperienceGraph exploration history as an interactive HTML file."
    )
    parser.add_argument("output_dir", help="Run output directory containing experience_graph_events.jsonl and snapshots/")
    parser.add_argument(
        "--out",
        default=None,
        help="Output HTML file path (default: <output_dir>/experience_graph_viz.html)",
    )
    args = parser.parse_args()

    output_dir = args.output_dir
    if not os.path.isdir(output_dir):
        print(f"Error: directory not found: {output_dir}", file=sys.stderr)
        sys.exit(1)

    out_path = args.out or os.path.join(output_dir, "experience_graph_viz.html")

    print(f"Loading events from {output_dir}...")
    events = load_events(output_dir)
    print(f"  {len(events)} events loaded.")

    print("Loading snapshots...")
    snapshots = load_snapshots(output_dir)
    print(f"  {len(snapshots)} snapshots loaded.")

    if not events and not snapshots:
        print("Warning: no data found. Make sure ExperienceGraph ran with output_dir set.")

    stats = compute_stats(events, snapshots)
    print(f"  Stats: {stats}")

    html = build_html(events, snapshots, stats, output_dir)

    with open(out_path, "w") as f:
        f.write(html)
    print(f"\nVisualization written to: {out_path}")
    print("Open the file in a browser to explore.")


if __name__ == "__main__":
    main()
