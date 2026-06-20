"""
ExperienceGraph visualizer.

Single run:
    python -m skydiscover.experience_graph.visualize <output_dir> [--out viz.html]

Compare multiple runs (overlaid timeline + tab-based tree):
    python -m skydiscover.experience_graph.visualize <dir1> <dir2> ... [--out comparison.html]
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
    snapshots = []
    if os.path.isdir(snap_dir):
        for fpath in sorted(glob.glob(os.path.join(snap_dir, "snapshot_*.json"))):
            try:
                with open(fpath) as f:
                    snapshots.append(json.load(f))
            except Exception:
                continue

    # Always append the current state file as the final "snapshot" if it's
    # newer than (or absent from) the saved snapshots — covers in-progress runs
    # and runs that ended without a clean shutdown snapshot.
    state_path = os.path.join(output_dir, "experience_graph.json")
    if os.path.exists(state_path):
        try:
            with open(state_path) as f:
                current = json.load(f)
            last_saved_at = snapshots[-1].get("saved_at", "") if snapshots else ""
            if current.get("saved_at", "") > last_saved_at:
                current.setdefault("trigger", "current")
                current.setdefault("iteration", current.get("insert_count", 0))
                snapshots.append(current)
        except Exception:
            pass

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


# ── Shared CSS + D3 helpers (embedded as template fragments) ──────────────────

_SHARED_CSS = """
  :root {
    --bg: #f0f2f5; --bg2: #ffffff; --bg3: #e8ecf0;
    --text: #1f2328; --text-dim: #656d76;
    --border: #d0d7de; --shadow: rgba(0,0,0,0.08);
    --accent: #0969da; --green: #1a7f37; --orange: #bc4c00;
    --purple: #8250df; --cyan: #0598c1; --red: #cf222e;
    --problem-view: #0969da; --solution-strategy: #1a7f37;
    --leaf-normal: #656d76; --leaf-pb: #8250df;
  }
  [data-theme="dark"] {
    --bg: #0d1117; --bg2: #161b22; --bg3: #21262d;
    --text: #e6edf3; --text-dim: #7d8590;
    --border: #30363d; --shadow: rgba(0,0,0,0.3);
    --accent: #58a6ff; --green: #3fb950; --orange: #d29922;
    --purple: #bc8cff; --cyan: #56d4dd; --red: #ff7b72;
    --problem-view: #58a6ff; --solution-strategy: #3fb950;
    --leaf-normal: #7d8590; --leaf-pb: #bc8cff;
  }
  * { margin:0; padding:0; box-sizing:border-box; }
  body { font-family:'Segoe UI',system-ui,-apple-system,sans-serif;
         background:var(--bg); color:var(--text); min-height:100vh; }
  header { background:var(--bg2); border-bottom:1px solid var(--border);
           padding:12px 20px; display:flex; align-items:center; gap:16px; }
  header h1 { font-size:16px; font-weight:600; }
  header .meta { font-size:12px; color:var(--text-dim); margin-left:auto; }
  .theme-btn { cursor:pointer; background:var(--bg3); border:1px solid var(--border);
               border-radius:6px; padding:4px 10px; font-size:12px; color:var(--text); }
  .main { display:grid; grid-template-columns:1fr 1fr; gap:0; }
  .panel { overflow:hidden; border-right:1px solid var(--border); }
  .panel:last-child { border-right:none; }
  .panel-hdr { padding:8px 14px; font-size:12px; font-weight:600;
               background:var(--bg3); border-bottom:1px solid var(--border);
               display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
  .panel-body { overflow:hidden; position:relative; }
  #timeline-chart { width:100%; height:100%; }
  #tree-container { width:100%; height:100%; overflow:auto; }
  svg#tree-svg { min-width:100%; }
  .bottom-bar { background:var(--bg2); border-top:1px solid var(--border);
                padding:8px 16px; display:flex; align-items:center; gap:12px; }
  .bottom-bar label { font-size:12px; color:var(--text-dim); }
  #snap-slider { flex:1; cursor:pointer; }
  #snap-info { font-size:12px; color:var(--text-dim); min-width:220px; }
  .legend { display:flex; gap:12px; font-size:11px; color:var(--text-dim);
            margin-left:auto; align-items:center; }
  .leg-dot { width:10px; height:10px; border-radius:50%; display:inline-block; margin-right:3px; }
  .node circle { stroke-width:2px; cursor:pointer; }
  .node text { font-size:11px; fill:var(--text); }
  .link { fill:none; stroke:var(--border); stroke-width:1.5px; }
  .tooltip { position:fixed; background:var(--bg2); border:1px solid var(--border);
             border-radius:8px; padding:12px 16px; font-size:12px; pointer-events:none;
             box-shadow:0 6px 24px var(--shadow); z-index:999; display:none;
             min-width:260px; max-width:420px; line-height:1.65;
             border-left:3px solid var(--accent); }
  .tt-label { font-size:13px; font-weight:700; color:var(--text); }
  .tt-type  { font-size:10px; color:var(--text-dim); margin-left:5px; font-weight:400; }
  .tt-desc  { margin:7px 0 5px; color:var(--text); font-size:12px; line-height:1.55; }
  .tt-meta  { border-top:1px solid var(--border); margin-top:6px; padding-top:6px;
              font-size:11px; color:var(--text-dim); display:flex; gap:12px; }
  .tt-rationale { border-top:1px solid var(--border); margin-top:6px; padding-top:6px;
                  font-size:10.5px; color:var(--text-dim); max-height:150px;
                  overflow-y:auto; line-height:1.55; white-space:pre-wrap; }
  /* Run tabs (comparison mode) */
  .run-tabs { display:flex; gap:2px; flex-wrap:wrap; }
  .run-tab { cursor:pointer; background:none; border:none; border-bottom:2px solid transparent;
             padding:3px 10px; font-size:11px; color:var(--text-dim); transition:all 0.15s; }
  .run-tab.active { font-weight:700; }
  .run-tab:hover { color:var(--text); }
  /* Comparison stats table */
  .stats-table-wrap { background:var(--bg2); border-bottom:1px solid var(--border); overflow-x:auto; }
  .stats-table { border-collapse:collapse; width:100%; font-size:13px; }
  .stats-table th, .stats-table td { padding:7px 16px; text-align:right;
                                     border-bottom:1px solid var(--border); white-space:nowrap; }
  .stats-table .mname { text-align:left; font-weight:500; color:var(--text-dim); }
  .stats-table thead th { font-weight:600; padding:9px 16px; }
  /* Single stats bar */
  .stats-bar { display:flex; gap:0; background:var(--bg2); border-bottom:1px solid var(--border); }
  .stat { flex:1; padding:10px 16px; border-right:1px solid var(--border); text-align:center; }
  .stat:last-child { border-right:none; }
  .stat-val { font-size:20px; font-weight:700; color:var(--accent); }
  .stat-lbl { font-size:11px; color:var(--text-dim); margin-top:2px; }
  .toggle-btn { cursor:pointer; background:none; border:1px solid var(--border);
               border-radius:5px; padding:2px 8px; font-size:11px; color:var(--text-dim);
               white-space:nowrap; }
  .toggle-btn:hover { background:var(--bg3); color:var(--text); }
  .toggle-btn.active { background:rgba(188,76,0,0.1); border-color:var(--orange);
                       color:var(--orange); }
  .parent-arrow-line { pointer-events:none; }
"""

_SHARED_JS = """
// ── Theme ─────────────────────────────────────────────────────────────────────
function toggleTheme() {
  const body = document.body;
  const isDark = body.dataset.theme === 'dark';
  body.dataset.theme = isDark ? 'light' : 'dark';
  document.querySelector('.theme-btn').textContent = isDark ? '🌙 Dark' : '☀️ Light';
  renderTimeline();
  if (typeof currentSnap !== 'undefined' && currentSnap) renderTree(currentSnap.tree, _treeEvts);
}

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

// ── Policy mode (GraphEvolve & any algo that logs policy_action) ───────────────
function modeKey(e) {
  if (!e.policy_action) return 'seed';
  if (e.policy_action === 'space_explore') return 'explore_' + (e.space_target || 'new_dir');
  return e.policy_action;  // 'exploit' | 'crossover'
}
const MODE_ORDER = ['exploit', 'crossover', 'explore_new_form', 'explore_new_dir', 'seed'];
function modeStyles() {
  return {
    exploit:          { color: cssVar('--accent'),  symbol: 'circle',           name: 'Exploit' },
    crossover:        { color: cssVar('--orange'),  symbol: 'diamond',          name: 'Crossover' },
    explore_new_form: { color: cssVar('--purple'),  symbol: 'star-triangle-up', name: 'Explore · new formulation' },
    explore_new_dir:  { color: cssVar('--cyan'),    symbol: 'triangle-up',      name: 'Explore · new direction' },
    seed:             { color: cssVar('--text-dim'),symbol: 'circle-open',      name: 'Seed' },
  };
}
const MODE_LABEL = {
  exploit: 'Exploit', crossover: 'Crossover',
  explore_new_form: 'Explore (new formulation)',
  explore_new_dir: 'Explore (new direction)', seed: 'Seed',
};
// Build per-mode marker traces from insert events (empty when no policy logged).
function buildModeTraces(insertEvts, txtMap) {
  const styles = modeStyles();
  const groups = {};
  insertEvts.forEach(e => { const k = modeKey(e); (groups[k] = groups[k] || []).push(e); });
  const traces = [];
  MODE_ORDER.forEach(k => {
    const g = groups[k];
    if (!g || !g.length) return;
    const st = styles[k];
    traces.push({
      x: g.map(e => e.iteration), y: g.map(e => e.score),
      mode: 'markers', name: st.name,
      marker: { color: st.color, size: 7, symbol: st.symbol, opacity: 0.9,
                line: { color: cssVar('--bg2'), width: 0.5 } },
      text: g.map(e => txtMap[e.solution_id] || ''),
      customdata: g.map(e => e.solution_id || null), hoverinfo: 'text',
    });
  });
  return traces;
}

// ── Lineage arrow toggle ───────────────────────────────────────────────────────
let _treeEvts = [];
let parentArrowsVisible = true;
function toggleParentArrows() {
  parentArrowsVisible = !parentArrowsVisible;
  document.querySelectorAll('.parent-arrow-line').forEach(el => {
    el.style.display = parentArrowsVisible ? '' : 'none';
  });
  const btn = document.getElementById('toggle-arrows-btn');
  if (btn) {
    btn.textContent = parentArrowsVisible ? 'Hide lineage' : 'Show lineage';
    btn.classList.toggle('active', parentArrowsVisible);
  }
}

// ── Cross-panel selection ─────────────────────────────────────────────────────
let selectedSolIds = new Set();
let _solEventMap = {};   // solution_id → {iter, score}

function getLeafSolIds(d) {
  if (d.data.node_type === 'leaf') return d.data.solution_id ? [d.data.solution_id] : [];
  const ch = d.children || d._children || [];
  return ch.flatMap(c => getLeafSolIds(c));
}

function highlightSolutions(solIds) {
  selectedSolIds = new Set(solIds.filter(Boolean));
  applyTreeHighlight();
  applyTimelineHighlight();
}

function clearHighlight() {
  selectedSolIds = new Set();
  applyTreeHighlight();
  applyTimelineHighlight();
}

function applyTreeHighlight() {
  const has = selectedSolIds.size > 0;
  d3.selectAll('.node').each(function(d) {
    const n = d.data;
    let lit = false;
    if (n.node_type === 'leaf') lit = selectedSolIds.has(n.solution_id);
    else if (has) lit = getLeafSolIds(d).some(sid => selectedSolIds.has(sid));
    d3.select(this).select('circle')
      .attr('opacity', has ? (lit ? 1.0 : 0.14) : 0.85)
      .attr('stroke-width', lit ? 4 : 2)
      .style('filter', lit ? 'drop-shadow(0 0 5px currentColor)' : null);
    d3.select(this).selectAll('text')
      .attr('opacity', has ? (lit ? 1.0 : 0.2) : 1.0);
  });
  d3.selectAll('.parent-arrow-line')
    .attr('opacity', has ? 0.18 : 0.65);
}

function applyTimelineHighlight() {
  const div = document.getElementById('timeline-chart');
  if (!div || !div.data) return;
  const selX = [], selY = [];
  selectedSolIds.forEach(sid => {
    const pt = _solEventMap[sid];
    if (pt) { selX.push(pt.iter); selY.push(pt.score); }
  });
  const idx = div.data.findIndex(t => t.name === '●sel');
  if (idx === -1) return;
  Plotly.restyle('timeline-chart', { x: [selX], y: [selY] }, [idx]);
}

function initTimelineClick() {
  const div = document.getElementById('timeline-chart');
  if (!div || div._selBound) return;
  div._selBound = true;
  div.on('plotly_click', function(data) {
    if (!data.points || !data.points.length) { clearHighlight(); return; }
    const pt = data.points[0];
    const sid = pt.customdata;
    if (!sid) return;
    if (selectedSolIds.size === 1 && selectedSolIds.has(sid)) clearHighlight();
    else highlightSolutions([sid]);
  });
}

// ── D3 tree ───────────────────────────────────────────────────────────────────
function nodeColor(d) {
  const n = d.data;
  if (n.node_type === 'root') return cssVar('--text-dim');
  if (n.node_type === 'leaf')
    return n.is_paradigm_breakthrough ? cssVar('--leaf-pb') : cssVar('--leaf-normal');
  const map = { problem_view: '--problem-view', solution_strategy: '--solution-strategy' };
  return cssVar(map[n.field_name] || '--text-dim');
}

function nodeRadius(d) {
  const n = d.data;
  if (n.node_type === 'root') return 8;
  if (n.node_type === 'leaf') {
    const s = n.score;
    return (s === null || s === undefined) ? 4 : 4 + Math.min(8, s * 10);
  }
  return 7;
}

function renderTree(treeData, evts) {
  _treeEvts = evts || [];
  const container = document.getElementById('tree-container');
  const svg = d3.select('#tree-svg');
  svg.selectAll('*').remove();
  if (!treeData) return;

  // Build lineage map: child solution_id → parent solution_id (from events)
  const solParentMap = {};
  _treeEvts.filter(e => e.event_type === 'insert' && e.parent_id && e.solution_id)
    .forEach(e => { solParentMap[e.solution_id] = e.parent_id; });

  // Click on SVG background clears selection
  svg.on('click', () => clearHighlight());

  const root = d3.hierarchy(treeData, d => d.children || []);

  function update() {
    const treeLayout = d3.tree().nodeSize([26, 180]);
    treeLayout(root);
    const nodes = root.descendants();
    const links = root.links();
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    nodes.forEach(n => {
      if (n.x < minX) minX = n.x; if (n.x > maxX) maxX = n.x;
      if (n.y < minY) minY = n.y; if (n.y > maxY) maxY = n.y;
    });
    const W = Math.max(container.clientWidth, (maxY - minY) + 240);
    const H = Math.max(400, (maxX - minX) + 60);
    svg.attr('width', W).attr('height', H);
    svg.selectAll('*').remove();

    // Arrowhead marker for lineage arrows
    const defs = svg.append('defs');
    const marker = defs.append('marker')
      .attr('id', 'lineage-arrow')
      .attr('viewBox', '0 -4 8 8').attr('refX', 8).attr('refY', 0)
      .attr('markerWidth', 5).attr('markerHeight', 5).attr('orient', 'auto');
    marker.append('path').attr('d', 'M0,-4L8,0L0,4').attr('fill', cssVar('--orange'));

    const g = svg.append('g').attr('transform', `translate(${-minY + 40},${-minX + 30})`);

    g.selectAll('.link').data(links).join('path')
      .attr('class', 'link')
      .attr('d', d3.linkHorizontal().x(d => d.y).y(d => d.x));

    // ── Lineage arrows: parent leaf → child leaf ──────────────────────────
    const leafPosMap = {};
    nodes.forEach(d => {
      if (d.data.node_type === 'leaf' && d.data.solution_id)
        leafPosMap[d.data.solution_id] = { x: d.y, y: d.x };
    });
    const lineageData = Object.entries(solParentMap)
      .filter(([sid, pid]) => leafPosMap[sid] && leafPosMap[pid])
      .map(([sid, pid]) => ({ from: leafPosMap[pid], to: leafPosMap[sid] }));
    g.selectAll('.parent-arrow-line').data(lineageData).join('path')
      .attr('class', 'parent-arrow-line')
      .attr('d', d => {
        const mx = (d.from.x + d.to.x) / 2;
        return `M${d.from.x},${d.from.y} C${mx},${d.from.y} ${mx},${d.to.y} ${d.to.x},${d.to.y}`;
      })
      .attr('stroke', cssVar('--orange')).attr('stroke-width', 1.5)
      .attr('stroke-dasharray', '5,3').attr('fill', 'none')
      .attr('marker-end', 'url(#lineage-arrow)').attr('opacity', 0.65)
      .style('display', parentArrowsVisible ? '' : 'none');

    const node = g.selectAll('.node').data(nodes).join('g')
      .attr('class', 'node')
      .attr('transform', d => `translate(${d.y},${d.x})`)
      .on('click', (evt, d) => {
        evt.stopPropagation();
        // Toggle highlight: leaf → self, internal → all leaf descendants
        const solIds = getLeafSolIds(d);
        const allSel = solIds.length > 0 && solIds.every(s => selectedSolIds.has(s));
        if (allSel) clearHighlight();
        else highlightSolutions(solIds);
      })
      .on('mouseover', (evt, d) => showTooltip(evt, d))
      .on('mousemove', evt => moveTooltip(evt))
      .on('mouseout', hideTooltip);

    node.append('circle')
      .attr('r', d => nodeRadius(d))
      .attr('fill', d => nodeColor(d))
      .attr('stroke', d => d3.color(nodeColor(d))?.darker(0.6) || '#333')
      .attr('opacity', 0.85);

    node.filter(d => d.data.node_type === 'leaf' && d.data.is_paradigm_breakthrough)
      .append('text')
      .attr('dy', '0.35em').attr('dx', '-0.35em')
      .attr('font-size', '9px').attr('fill', '#fff').attr('pointer-events', 'none')
      .text('★');

    node.append('text')
      .attr('dy', '0.31em')
      .attr('x', d => (d.children || d._children) ? -11 : 11)
      .attr('text-anchor', d => (d.children || d._children) ? 'end' : 'start')
      .attr('font-size', '11px')
      .text(d => {
        const lbl = d.data.label || '';
        const col = d._children ? ` [+${d._children.length}]` : '';
        if (d.data.node_type === 'leaf' && d.data.score != null) {
          const s = d.data.score;
          const sc = s < 0.01 ? s.toExponential(2) : s.toFixed(4);
          return lbl.slice(0, 18) + ' ' + sc + col;
        }
        return lbl.slice(0, 22) + col;
      });
    applyTreeHighlight();
  }

  // Start with all nodes expanded
  update();
}

// ── Tooltip ───────────────────────────────────────────────────────────────────
const tooltip = document.getElementById('tooltip');

function showTooltip(evt, d) {
  const n = d.data;
  let html = `<span class="tt-label">${n.label || ''}</span>`;
  if (n.field_name) html += `<span class="tt-type">(${n.field_name})</span>`;
  if (n.description) html += `<div class="tt-desc">${n.description}</div>`;
  if (n.node_type === 'leaf') {
    html += '<div class="tt-meta">';
    if (n.score != null) {
      const s = n.score;
      html += `<span><b>Score</b> ${s < 0.01 ? s.toExponential(3) : s.toFixed(4)}</span>`;
    }
    if (n.solution_id) html += `<span style="color:var(--text-dim)">ID ${n.solution_id.slice(0,8)}…</span>`;
    if (n.is_paradigm_breakthrough) html += `<span style="color:var(--leaf-pb)">★ PB</span>`;
    html += '</div>';
    if (n.rationale_ref) html += `<div class="tt-rationale">${n.rationale_ref}</div>`;
  } else if (n.node_type !== 'root') {
    const cnt = (n.children || []).length;
    html += `<div class="tt-meta"><span>${cnt} child${cnt !== 1 ? 'ren' : ''}</span></div>`;
  }
  tooltip.innerHTML = html;
  tooltip.style.display = 'block';
  moveTooltip(evt);
}

function moveTooltip(evt) {
  const GAP = 14;
  const vw = window.innerWidth, vh = window.innerHeight;
  const tw = tooltip.offsetWidth, th = tooltip.offsetHeight;
  const x = evt.clientX + GAP + tw > vw ? evt.clientX - GAP - tw : evt.clientX + GAP;
  const y = evt.clientY - 10 + th > vh ? evt.clientY - th + 10  : evt.clientY - 10;
  tooltip.style.left = Math.max(4, x) + 'px';
  tooltip.style.top  = Math.max(4, y) + 'px';
}

function hideTooltip() { tooltip.style.display = 'none'; }
"""


# ── Single-run HTML ───────────────────────────────────────────────────────────


def build_html(
    events: List[Dict],
    snapshots: List[Dict],
    stats: Dict[str, Any],
    output_dir: str,
) -> str:
    data_json = json.dumps(
        {"events": events, "snapshots": snapshots, "stats": stats}, default=str
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
<title>ExperienceGraph — {os.path.basename(output_dir)}</title>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<script src="https://d3js.org/d3.v7.min.js"></script>
<style>
{_SHARED_CSS}
  .main {{ height: calc(100vh - 160px); }}
  .panel-body {{ height: calc(100% - 34px); }}
</style>
</head>
<body data-theme="light">

<header>
  <h1>⬡ ExperienceGraph</h1>
  <span class="meta">Generated: {generated_at} &nbsp;|&nbsp; {output_dir}</span>
  <button class="theme-btn" onclick="toggleTheme()">🌙 Dark</button>
</header>

<div class="stats-bar">
  <div class="stat"><div class="stat-val">{stats['total_leaves']}</div>
    <div class="stat-lbl">Total solutions</div></div>
  <div class="stat"><div class="stat-val">{stats['total_paradigm_branches']}</div>
    <div class="stat-lbl">Paradigm branches</div></div>
  <div class="stat"><div class="stat-val">{stats['total_paradigm_breakthrough']}</div>
    <div class="stat-lbl">Paradigm breakthroughs</div></div>
  <div class="stat"><div class="stat-val">{best_score_str}</div>
    <div class="stat-lbl">Best score</div></div>
  <div class="stat"><div class="stat-val">{stats['n_summarize_events']}</div>
    <div class="stat-lbl">Summarize events</div></div>
</div>

<div class="main">
  <div class="panel">
    <div class="panel-hdr">
      📈 Score Timeline
      <div class="legend">
        <span><span class="leg-dot" style="background:var(--accent)"></span>Normal</span>
        <span><span class="leg-dot" style="background:var(--leaf-pb)"></span>Paradigm</span>
      </div>
    </div>
    <div class="panel-body"><div id="timeline-chart"></div></div>
  </div>
  <div class="panel">
    <div class="panel-hdr">
      🌳 Exploration Tree
      <button id="toggle-arrows-btn" class="toggle-btn active" onclick="toggleParentArrows()">Hide lineage</button>
      <div class="legend">
        <span><span class="leg-dot" style="background:var(--problem-view)"></span>problem view</span>
        <span><span class="leg-dot" style="background:var(--solution-strategy)"></span>strategy</span>
        <span><span class="leg-dot" style="background:var(--leaf-pb)"></span>★PB</span>
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

{_SHARED_JS}

// ── Timeline (single run) ────────────────────────────────────────────────────
function renderTimeline() {{
  const insertEvts = events.filter(e => e.event_type === 'insert');
  const sumEvts   = events.filter(e => e.event_type === 'summarize');

  const allX = [], allY = [], allText = [], allSolIds = [];
  const pbX = [], pbY = [], pbText = [], pbSolIds = [];
  const solMap = {{}};
  insertEvts.forEach(e => {{
    if (e.solution_id) {{
      solMap[e.solution_id] = {{ iter: e.iteration, score: e.score }};
      _solEventMap[e.solution_id] = {{ iter: e.iteration, score: e.score }};
    }}
  }});
  // Adaptive: when the search algorithm records a per-iteration policy mode
  // (e.g. GraphEvolve), colour the timeline by mode instead of a single series.
  const hasPolicy = insertEvts.some(e => e.policy_action);
  const txtMap = {{}};
  insertEvts.forEach(e => {{
    const mk = modeKey(e);
    const txt = [
      `<b>${{e.leaf_label || ''}}</b>`,
      hasPolicy ? `Mode: ${{MODE_LABEL[mk] || mk}}` : `Action: ${{e.action || ''}}`,
      hasPolicy ? `Placement: ${{e.action || ''}}` : null,
      `Path: ${{(e.placement_path || []).join(' → ')}}`,
      `ID: ${{(e.solution_id || '').slice(0, 8)}}`,
      `Score: ${{e.score != null ? e.score.toFixed(4) : 'N/A'}}`,
    ].filter(x => x != null).join('<br>');
    txtMap[e.solution_id] = txt;
    allX.push(e.iteration); allY.push(e.score); allText.push(txt);
    allSolIds.push(e.solution_id || null);
    if (e.is_paradigm_breakthrough) {{
      pbX.push(e.iteration); pbY.push(e.score); pbText.push(txt);
      pbSolIds.push(e.solution_id || null);
    }}
  }});
  const arrowAnnotations = insertEvts
    .filter(e => e.parent_id && solMap[e.parent_id])
    .map(e => {{
      const p = solMap[e.parent_id];
      return {{
        x: e.iteration, y: e.score,
        ax: p.iter, ay: p.score,
        axref: 'x', ayref: 'y', xref: 'x', yref: 'y',
        showarrow: true, arrowhead: 2, arrowsize: 1, arrowwidth: 1.2,
        arrowcolor: cssVar('--text-dim'), opacity: 0.5, text: '',
      }};
    }});

  const bg = cssVar('--bg2'), textColor = cssVar('--text'), gridColor = cssVar('--border');
  const shapes = sumEvts.map(e => ({{
    type: 'line', xref: 'x', yref: 'paper',
    x0: e.iteration, x1: e.iteration, y0: 0, y1: 1,
    line: {{ color: cssVar('--red'), width: 1.5, dash: 'dot' }},
  }}));
  const annotations = sumEvts.map(e => ({{
    x: e.iteration, y: 1, xref: 'x', yref: 'paper',
    text: '⚡', showarrow: false, font: {{ size: 12 }}, yanchor: 'bottom',
  }}));
  const baseTraces = [];
  if (hasPolicy) {{
    baseTraces.push({{ x: allX, y: allY, mode: 'lines', name: 'Score path',
       line: {{ color: cssVar('--border'), width: 1 }}, hoverinfo: 'skip', showlegend: false }});
    buildModeTraces(insertEvts, txtMap).forEach(t => baseTraces.push(t));
  }} else {{
    baseTraces.push({{ x: allX, y: allY, mode: 'lines+markers', name: 'Score',
       line: {{ color: cssVar('--accent'), width: 1.5 }},
       marker: {{ color: cssVar('--accent'), size: 4, opacity: 0.8 }},
       text: allText, customdata: allSolIds, hoverinfo: 'text' }});
  }}
  baseTraces.push({{ x: pbX, y: pbY, mode: 'markers', name: '★ Paradigm BT',
       marker: {{ color: cssVar('--leaf-pb'), size: 10, symbol: 'star', opacity: 0.95 }},
       text: pbText, customdata: pbSolIds, hoverinfo: 'text' }});
  baseTraces.push({{ x: [], y: [], name: '●sel', mode: 'markers',
       marker: {{ color: 'transparent', size: 18, line: {{ color: cssVar('--orange'), width: 2.5 }} }},
       hoverinfo: 'skip', showlegend: false }});
  Plotly.react('timeline-chart', baseTraces, {{
    paper_bgcolor: bg, plot_bgcolor: bg,
    font: {{ color: textColor, size: 11 }},
    xaxis: {{ title: 'Iteration', gridcolor: gridColor, zeroline: false }},
    yaxis: {{ title: 'Score', gridcolor: gridColor, zeroline: false }},
    legend: {{ bgcolor: bg, bordercolor: gridColor, borderwidth: 1 }},
    margin: {{ l: 50, r: 20, t: 20, b: 40 }},
    shapes, annotations: [...annotations, ...arrowAnnotations], hovermode: 'closest',
  }}, {{ responsive: true, displayModeBar: false }});
  initTimelineClick();
  applyTimelineHighlight();
}}

// ── Slider (single run) ──────────────────────────────────────────────────────
let currentSnap = null;

function initSlider() {{
  const slider = document.getElementById('snap-slider');
  if (!snapshots.length) {{ document.getElementById('snap-info').textContent = 'No snapshots'; return; }}
  slider.max = snapshots.length - 1;
  slider.value = snapshots.length - 1;
  onSliderChange(snapshots.length - 1);
}}

function onSliderChange(idx) {{
  idx = parseInt(idx);
  if (idx < 0 || idx >= snapshots.length) return;
  currentSnap = snapshots[idx];
  document.getElementById('snap-info').textContent =
    `#${{idx + 1}}/${{snapshots.length}} | iter ${{currentSnap.iteration}} | ` +
    `${{currentSnap.total_leaves}} leaves | trigger: ${{currentSnap.trigger}}`;
  renderTree(currentSnap.tree, events);
}}

renderTimeline();
initSlider();
</script>
</body>
</html>"""


# ── Multi-run comparison HTML ─────────────────────────────────────────────────

_PALETTE = ["#0969da", "#1a7f37", "#bc4c00", "#8250df", "#0598c1", "#cf222e"]


def build_comparison_html(runs: List[Dict[str, Any]]) -> str:
    runs_json = json.dumps(
        [
            {
                "label": r["label"],
                "dir": r["dir"],
                "events": r["events"],
                "snapshots": r["snapshots"],
                "stats": r["stats"],
            }
            for r in runs
        ],
        default=str,
    )
    palette_json = json.dumps(_PALETTE)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    title = " vs ".join(r["label"] for r in runs)

    # Build stats table rows
    metric_rows = ""
    for label, key, fmt in [
        ("Solutions", "total_leaves", lambda v: str(v)),
        ("Paradigm branches", "total_paradigm_branches", lambda v: str(v)),
        ("Breakthroughs", "total_paradigm_breakthrough", lambda v: str(v)),
        ("Best score", "best_score", lambda v: f"{v:.4f}" if v is not None else "N/A"),
        ("Summarize events", "n_summarize_events", lambda v: str(v)),
    ]:
        cells = "".join(
            f"<td>{fmt(r['stats'].get(key))}</td>" for r in runs
        )
        metric_rows += f"<tr><td class='mname'>{label}</td>{cells}</tr>"

    header_cells = "".join(
        f"<th style='color:{_PALETTE[i % len(_PALETTE)]}'>{r['label']}</th>"
        for i, r in enumerate(runs)
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ExperienceGraph Comparison</title>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<script src="https://d3js.org/d3.v7.min.js"></script>
<style>
{_SHARED_CSS}
  .main {{ height: calc(100vh - 220px); }}
  .panel-body {{ height: calc(100% - 34px); }}
</style>
</head>
<body data-theme="light">

<header>
  <h1>⬡ ExperienceGraph Comparison ({len(runs)} runs)</h1>
  <span class="meta">Generated: {generated_at}</span>
  <button class="theme-btn" onclick="toggleTheme()">🌙 Dark</button>
</header>

<div class="stats-table-wrap">
  <table class="stats-table">
    <thead><tr><th class="mname">Metric</th>{header_cells}</tr></thead>
    <tbody>{metric_rows}</tbody>
  </table>
</div>

<div class="main">
  <div class="panel">
    <div class="panel-hdr">
      📈 Score Timeline
      <div class="legend" id="timeline-legend"></div>
    </div>
    <div class="panel-body"><div id="timeline-chart"></div></div>
  </div>
  <div class="panel">
    <div class="panel-hdr">
      🌳 Exploration Tree
      <div class="run-tabs" id="run-tabs"></div>
      <button id="toggle-arrows-btn" class="toggle-btn active" onclick="toggleParentArrows()">Hide lineage</button>
      <div class="legend" style="margin-left:auto">
        <span><span class="leg-dot" style="background:var(--problem-view)"></span>PV</span>
        <span><span class="leg-dot" style="background:var(--solution-strategy)"></span>SS</span>
        <span><span class="leg-dot" style="background:var(--leaf-pb)"></span>★PB</span>
      </div>
    </div>
    <div class="panel-body"><div id="tree-container"><svg id="tree-svg"></svg></div></div>
  </div>
</div>

<div class="bottom-bar">
  <label>Snapshot:</label>
  <input type="range" id="snap-slider" min="0" max="0" value="0" oninput="onSliderChange(this.value)">
  <span id="snap-info">Select a run above</span>
</div>

<div class="tooltip" id="tooltip"></div>

<script>
const RUNS = {runs_json};
const PALETTE = {palette_json};

{_SHARED_JS}

// ── Timeline (comparison: overlaid) ──────────────────────────────────────────
function renderTimeline() {{
  const traces = [];
  const shapes = [];
  const annotations = [];
  const bg = cssVar('--bg2'), textColor = cssVar('--text'), gridColor = cssVar('--border');

  RUNS.forEach((run, i) => {{
    const color = PALETTE[i % PALETTE.length];
    const inserts = run.events.filter(e => e.event_type === 'insert');
    const sumEvts = run.events.filter(e => e.event_type === 'summarize');
    const allX = [], allY = [], allText = [], allSolIds = [];
    const pbX = [], pbY = [], pbText = [], pbSolIds = [];
    const solMap = {{}};
    inserts.forEach(e => {{
      if (e.solution_id) {{
        solMap[e.solution_id] = {{ iter: e.iteration, score: e.score }};
        _solEventMap[e.solution_id] = {{ iter: e.iteration, score: e.score }};
      }}
    }});
    inserts.forEach(e => {{
      const txt = [
        `<b>${{run.label}}</b>`,
        `${{e.leaf_label || ''}}`,
        `Score: ${{e.score != null ? e.score.toFixed(4) : 'N/A'}}`,
        `Action: ${{e.action || ''}}`,
        `Path: ${{(e.placement_path || []).join(' → ')}}`,
      ].join('<br>');
      allX.push(e.iteration); allY.push(e.score); allText.push(txt);
      allSolIds.push(e.solution_id || null);
      if (e.is_paradigm_breakthrough) {{
        pbX.push(e.iteration); pbY.push(e.score); pbText.push(txt);
        pbSolIds.push(e.solution_id || null);
      }}
    }});
    inserts.filter(e => e.parent_id && solMap[e.parent_id]).forEach(e => {{
      const p = solMap[e.parent_id];
      annotations.push({{
        x: e.iteration, y: e.score, ax: p.iter, ay: p.score,
        axref: 'x', ayref: 'y', xref: 'x', yref: 'y',
        showarrow: true, arrowhead: 2, arrowsize: 1, arrowwidth: 1.2,
        arrowcolor: color, opacity: 0.4, text: '',
      }});
    }});
    traces.push({{
      x: allX, y: allY, mode: 'lines+markers', name: run.label,
      line: {{ color, width: 1.5 }},
      marker: {{ color, size: 4, opacity: 0.75 }},
      text: allText, customdata: allSolIds, hoverinfo: 'text',
      legendgroup: run.label, showlegend: true,
    }});
    traces.push({{
      x: pbX, y: pbY, mode: 'markers', name: `${{run.label}} ★`,
      marker: {{ color, size: 10, symbol: 'star', opacity: 0.95 }},
      text: pbText, customdata: pbSolIds, hoverinfo: 'text',
      legendgroup: run.label, showlegend: false,
    }});
    sumEvts.forEach(e => {{
      shapes.push({{
        type: 'line', xref: 'x', yref: 'paper',
        x0: e.iteration, x1: e.iteration, y0: 0, y1: 1,
        line: {{ color, width: 1, dash: 'dot', opacity: 0.4 }},
      }});
    }});
  }});

  traces.push({{
    x: [], y: [], name: '●sel', mode: 'markers',
    marker: {{ color: 'transparent', size: 18, line: {{ color: cssVar('--orange'), width: 2.5 }} }},
    hoverinfo: 'skip', showlegend: false,
  }});
  Plotly.react('timeline-chart', traces, {{
    paper_bgcolor: bg, plot_bgcolor: bg,
    font: {{ color: textColor, size: 11 }},
    xaxis: {{ title: 'Iteration', gridcolor: gridColor, zeroline: false }},
    yaxis: {{ title: 'Score', gridcolor: gridColor, zeroline: false }},
    legend: {{ bgcolor: bg, bordercolor: gridColor, borderwidth: 1 }},
    margin: {{ l: 50, r: 20, t: 20, b: 40 }},
    shapes, annotations, hovermode: 'closest',
  }}, {{ responsive: true, displayModeBar: false }});
  initTimelineClick();
  applyTimelineHighlight();
}}

// ── Run tabs + slider ─────────────────────────────────────────────────────────
let selectedRunIdx = 0;
let currentSnap = null;

function initRunTabs() {{
  const container = document.getElementById('run-tabs');
  RUNS.forEach((run, i) => {{
    const btn = document.createElement('button');
    btn.className = 'run-tab' + (i === 0 ? ' active' : '');
    btn.textContent = run.label;
    btn.style.color = PALETTE[i % PALETTE.length];
    btn.onclick = () => selectRun(i);
    container.appendChild(btn);
  }});
  selectRun(0);
}}

function selectRun(idx) {{
  selectedRunIdx = idx;
  document.querySelectorAll('.run-tab').forEach((t, i) => t.classList.toggle('active', i === idx));
  const snaps = RUNS[idx].snapshots;
  const slider = document.getElementById('snap-slider');
  if (!snaps.length) {{
    document.getElementById('snap-info').textContent = 'No snapshots for this run';
    d3.select('#tree-svg').selectAll('*').remove();
    return;
  }}
  slider.max = snaps.length - 1;
  slider.value = snaps.length - 1;
  onSliderChange(snaps.length - 1);
}}

function onSliderChange(idx) {{
  const snaps = RUNS[selectedRunIdx].snapshots;
  idx = parseInt(idx);
  if (idx < 0 || idx >= snaps.length) return;
  currentSnap = snaps[idx];
  document.getElementById('snap-info').textContent =
    `${{RUNS[selectedRunIdx].label}} | #${{idx + 1}}/${{snaps.length}} | ` +
    `iter ${{currentSnap.iteration}} | ${{currentSnap.total_leaves}} leaves | ${{currentSnap.trigger}}`;
  renderTree(currentSnap.tree, RUNS[selectedRunIdx].events);
}}

renderTimeline();
initRunTabs();
</script>
</body>
</html>"""


# ── Live server ───────────────────────────────────────────────────────────────


def _build_live_data(output_dirs: List[str]) -> Dict[str, Any]:
    runs = []
    for d in output_dirs:
        if not os.path.isdir(d):
            continue
        events = load_events(d)
        snapshots = load_snapshots(d)
        stats = compute_stats(events, snapshots)
        runs.append({
            "label": os.path.basename(d.rstrip("/")),
            "dir": d,
            "events": events,
            "snapshots": snapshots,
            "stats": stats,
        })
    return {"runs": runs, "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}


def _build_live_html(output_dirs: List[str], refresh_interval: int) -> str:
    palette_json = json.dumps(_PALETTE)
    interval_ms = refresh_interval * 1000

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ExperienceGraph Live</title>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<script src="https://d3js.org/d3.v7.min.js"></script>
<style>
{_SHARED_CSS}
  .main {{ height: calc(100vh - 220px); }}
  .panel-body {{ height: calc(100% - 34px); }}
  .live-badge {{ display:inline-flex; align-items:center; gap:5px;
                 background:rgba(26,127,55,0.15); border:1px solid var(--green);
                 border-radius:4px; padding:2px 8px; font-size:11px; color:var(--green); }}
  .live-dot {{ width:7px; height:7px; border-radius:50%; background:var(--green);
               animation:pulse 1.5s infinite; }}
  @keyframes pulse {{ 0%,100% {{ opacity:1; }} 50% {{ opacity:0.3; }} }}
  .live-badge.err {{ background:rgba(207,34,46,0.12); border-color:var(--red); color:var(--red); }}
  .live-badge.err .live-dot {{ background:var(--red); animation:none; }}
</style>
</head>
<body data-theme="light">

<header>
  <h1>⬡ ExperienceGraph Live</h1>
  <span class="live-badge" id="live-badge"><span class="live-dot"></span><span id="live-label">connecting…</span></span>
  <span class="meta" id="updated-at" style="margin-left:8px"></span>
  <button class="theme-btn" onclick="toggleTheme()">🌙 Dark</button>
</header>

<div class="stats-table-wrap">
  <table class="stats-table">
    <thead id="stats-thead"><tr><th class="mname">Metric</th><th>—</th></tr></thead>
    <tbody id="stats-tbody"></tbody>
  </table>
</div>

<div class="main">
  <div class="panel">
    <div class="panel-hdr">📈 Score Timeline</div>
    <div class="panel-body"><div id="timeline-chart"></div></div>
  </div>
  <div class="panel">
    <div class="panel-hdr">
      🌳 Exploration Tree
      <div class="run-tabs" id="run-tabs"></div>
      <button id="toggle-arrows-btn" class="toggle-btn active" onclick="toggleParentArrows()">Hide lineage</button>
      <div class="legend" style="margin-left:auto">
        <span><span class="leg-dot" style="background:var(--problem-view)"></span>PV</span>
        <span><span class="leg-dot" style="background:var(--solution-strategy)"></span>SS</span>
        <span><span class="leg-dot" style="background:var(--leaf-pb)"></span>★PB</span>
      </div>
    </div>
    <div class="panel-body"><div id="tree-container"><svg id="tree-svg"></svg></div></div>
  </div>
</div>

<div class="bottom-bar">
  <label>Snapshot:</label>
  <input type="range" id="snap-slider" min="0" max="0" value="0">
  <span id="snap-info">Waiting for data…</span>
</div>

<div class="tooltip" id="tooltip"></div>

<script>
const PALETTE = {palette_json};
const REFRESH_INTERVAL = {interval_ms};

{_SHARED_JS}

// ── Live state ────────────────────────────────────────────────────────────────
let RUNS = [];
let selectedRunIdx = 0;
let currentSnap = null;
let sliderAtLatest = true;

document.getElementById('snap-slider').addEventListener('input', function () {{
  const snaps = RUNS[selectedRunIdx]?.snapshots || [];
  sliderAtLatest = (parseInt(this.value) === snaps.length - 1);
  onSliderChange(this.value);
}});

// ── Stats table ───────────────────────────────────────────────────────────────
const METRICS = [
  ['Solutions',         r => r.stats.total_leaves],
  ['Paradigm branches', r => r.stats.total_paradigm_branches],
  ['Breakthroughs',     r => r.stats.total_paradigm_breakthrough],
  ['Best score',        r => r.stats.best_score != null ? r.stats.best_score.toFixed(4) : 'N/A'],
  ['Summarize events',  r => r.stats.n_summarize_events],
];

function updateStatsTable() {{
  if (!RUNS.length) return;
  document.getElementById('stats-thead').innerHTML =
    '<tr><th class="mname">Metric</th>' +
    RUNS.map((r, i) => `<th style="color:${{PALETTE[i % PALETTE.length]}}">${{r.label}}</th>`).join('') +
    '</tr>';
  document.getElementById('stats-tbody').innerHTML = METRICS.map(([name, fn]) =>
    `<tr><td class="mname">${{name}}</td>` + RUNS.map(r => `<td>${{fn(r)}}</td>`).join('') + '</tr>'
  ).join('');
}}

// ── Timeline ──────────────────────────────────────────────────────────────────
function renderTimeline() {{
  if (!RUNS.length) return;
  const traces = [], shapes = [], annotations = [];
  const bg = cssVar('--bg2'), textColor = cssVar('--text'), gridColor = cssVar('--border');
  RUNS.forEach((run, i) => {{
    const color = PALETTE[i % PALETTE.length];
    const inserts = run.events.filter(e => e.event_type === 'insert');
    const sumEvts  = run.events.filter(e => e.event_type === 'summarize');
    const ax=[], ay=[], at=[], asd=[], px=[], py=[], pt=[], psd=[];
    const solMap = {{}};
    inserts.forEach(e => {{
      if (e.solution_id) {{
        solMap[e.solution_id] = {{ iter: e.iteration, score: e.score }};
        _solEventMap[e.solution_id] = {{ iter: e.iteration, score: e.score }};
      }}
    }});
    const hasPolicy = inserts.some(e => e.policy_action);
    const txtMap = {{}};
    inserts.forEach(e => {{
      const mk = modeKey(e);
      const modeLine = hasPolicy ? `<br>Mode: ${{MODE_LABEL[mk] || mk}}` : '';
      const txt = `<b>${{run.label}}</b><br>${{e.leaf_label||''}}<br>Score: ${{e.score!=null?e.score.toFixed(4):'N/A'}}${{modeLine}}<br>Placement: ${{e.action||''}}<br>Path: ${{(e.placement_path||[]).join(' → ')}}`;
      txtMap[e.solution_id] = txt;
      ax.push(e.iteration); ay.push(e.score); at.push(txt); asd.push(e.solution_id||null);
      if (e.is_paradigm_breakthrough) {{ px.push(e.iteration); py.push(e.score); pt.push(txt); psd.push(e.solution_id||null); }}
    }});
    inserts.filter(e => e.parent_id && solMap[e.parent_id]).forEach(e => {{
      const p = solMap[e.parent_id];
      annotations.push({{ x:e.iteration, y:e.score, ax:p.iter, ay:p.score,
        axref:'x', ayref:'y', xref:'x', yref:'y',
        showarrow:true, arrowhead:2, arrowsize:1, arrowwidth:1.2,
        arrowcolor:color, opacity:0.4, text:'' }});
    }});
    if (hasPolicy && RUNS.length === 1) {{
      // Single GraphEvolve run: colour markers by policy mode.
      traces.push({{ x:ax, y:ay, mode:'lines', name:run.label,
        line:{{ color: cssVar('--border'), width:1 }}, hoverinfo:'skip',
        legendgroup:run.label, showlegend:false }});
      buildModeTraces(inserts, txtMap).forEach(t => {{ t.legendgroup = run.label; traces.push(t); }});
    }} else {{
      traces.push({{ x:ax, y:ay, mode:'lines+markers', name:run.label,
        line:{{ color, width:1.5 }}, marker:{{ color, size:4, opacity:0.75 }},
        text:at, customdata:asd, hoverinfo:'text', legendgroup:run.label, showlegend:true }});
    }}
    traces.push({{ x:px, y:py, mode:'markers', name:`${{run.label}} ★`,
      marker:{{ color, size:10, symbol:'star', opacity:0.95 }}, text:pt, customdata:psd, hoverinfo:'text',
      legendgroup:run.label, showlegend:false }});
    sumEvts.forEach(e => shapes.push({{
      type:'line', xref:'x', yref:'paper',
      x0:e.iteration, x1:e.iteration, y0:0, y1:1,
      line:{{ color, width:1, dash:'dot', opacity:0.4 }},
    }}));
  }});
  traces.push({{
    x:[], y:[], name:'●sel', mode:'markers',
    marker:{{ color:'transparent', size:18, line:{{ color:cssVar('--orange'), width:2.5 }} }},
    hoverinfo:'skip', showlegend:false,
  }});
  Plotly.react('timeline-chart', traces, {{
    paper_bgcolor:bg, plot_bgcolor:bg, font:{{ color:textColor, size:11 }},
    xaxis:{{ title:'Iteration', gridcolor:gridColor, zeroline:false }},
    yaxis:{{ title:'Score', gridcolor:gridColor, zeroline:false }},
    legend:{{ bgcolor:bg, bordercolor:gridColor, borderwidth:1 }},
    margin:{{ l:50, r:20, t:20, b:40 }}, shapes, annotations, hovermode:'closest',
  }}, {{ responsive:true, displayModeBar:false }});
  initTimelineClick();
  applyTimelineHighlight();
}}

// ── Run tabs ──────────────────────────────────────────────────────────────────
let _tabCount = 0;
function syncRunTabs() {{
  if (RUNS.length === _tabCount) return;
  _tabCount = RUNS.length;
  const c = document.getElementById('run-tabs');
  c.innerHTML = '';
  RUNS.forEach((run, i) => {{
    const btn = document.createElement('button');
    btn.className = 'run-tab' + (i === selectedRunIdx ? ' active' : '');
    btn.textContent = run.label;
    btn.style.color = PALETTE[i % PALETTE.length];
    btn.onclick = () => selectRun(i);
    c.appendChild(btn);
  }});
}}

function selectRun(idx) {{
  selectedRunIdx = idx; sliderAtLatest = true;
  document.querySelectorAll('.run-tab').forEach((t, i) => t.classList.toggle('active', i === idx));
  refreshTree();
}}

// ── Tree + slider ─────────────────────────────────────────────────────────────
function refreshTree() {{
  const run = RUNS[selectedRunIdx];
  if (!run) return;
  const snaps = run.snapshots;
  const slider = document.getElementById('snap-slider');
  if (!snaps.length) {{
    document.getElementById('snap-info').textContent = 'No snapshots yet…';
    d3.select('#tree-svg').selectAll('*').remove(); return;
  }}
  slider.max = snaps.length - 1;
  if (sliderAtLatest) {{ slider.value = snaps.length - 1; onSliderChange(snaps.length - 1); }}
}}

function onSliderChange(idx) {{
  const run = RUNS[selectedRunIdx]; if (!run) return;
  const snaps = run.snapshots; idx = parseInt(idx);
  if (idx < 0 || idx >= snaps.length) return;
  currentSnap = snaps[idx];
  document.getElementById('snap-info').textContent =
    `${{run.label}} | #${{idx+1}}/${{snaps.length}} | iter ${{currentSnap.iteration}} | ` +
    `${{currentSnap.total_leaves}} leaves | ${{currentSnap.trigger}}` +
    (sliderAtLatest ? '' : ' ⏸ paused');
  renderTree(currentSnap.tree, run.events || []);
}}

// ── Fetch loop ────────────────────────────────────────────────────────────────
async function fetchData() {{
  try {{
    const resp = await fetch('/api/data');
    if (!resp.ok) throw new Error(resp.status);
    const data = await resp.json();
    RUNS = data.runs || [];
    const badge = document.getElementById('live-badge');
    badge.className = 'live-badge';
    document.getElementById('live-label').textContent = `every ${{REFRESH_INTERVAL/1000}}s`;
    document.getElementById('updated-at').textContent = `Last: ${{data.updated_at.slice(11,19)}}`;
    syncRunTabs(); updateStatsTable(); renderTimeline(); refreshTree();
  }} catch(e) {{
    document.getElementById('live-badge').className = 'live-badge err';
    document.getElementById('live-label').textContent = 'disconnected';
  }}
}}

fetchData();
setInterval(fetchData, REFRESH_INTERVAL);
</script>
</body>
</html>"""


def serve_live(output_dirs: List[str], port: int = 8765, refresh_interval: int = 5) -> None:
    from http.server import BaseHTTPRequestHandler, HTTPServer

    live_html = _build_live_html(output_dirs, refresh_interval).encode("utf-8")

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path in ("/", "/index.html"):
                self._send(200, "text/html; charset=utf-8", live_html)
            elif self.path == "/api/data":
                body = json.dumps(_build_live_data(output_dirs), default=str).encode("utf-8")
                self._send(200, "application/json", body)
            else:
                self._send(404, "text/plain", b"not found")

        def _send(self, status: int, ctype: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", len(body))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args: Any) -> None:
            pass  # suppress per-request logging

    server = HTTPServer(("localhost", port), _Handler)
    url = f"http://localhost:{port}"
    print(f"Live ExperienceGraph visualizer → {url}")
    print(f"Watching {len(output_dirs)} dir(s), refreshing every {refresh_interval}s.")
    print("Ctrl+C to stop.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        server.shutdown()


# ── CLI ───────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Visualize ExperienceGraph exploration history.\n"
            "Pass one directory for a single-run view, or multiple for comparison.\n"
            "Add --live to start an auto-refreshing server instead of writing a static file."
        )
    )
    parser.add_argument(
        "output_dirs",
        nargs="+",
        help="One or more run output directories containing experience_graph_events.jsonl",
    )
    parser.add_argument("--out", default=None, help="Output HTML path (static mode only)")
    parser.add_argument("--live", action="store_true", help="Start live HTTP server (auto-refresh)")
    parser.add_argument("--port", type=int, default=8765, help="Port for live server (default: 8765)")
    parser.add_argument("--interval", type=int, default=5, help="Refresh interval in seconds (default: 5)")
    args = parser.parse_args()

    # Validate dirs
    valid_dirs = [d for d in args.output_dirs if os.path.isdir(d)]
    for d in args.output_dirs:
        if not os.path.isdir(d):
            print(f"Warning: directory not found, skipping: {d}", file=sys.stderr)

    if not valid_dirs:
        print("Error: no valid output directories found.", file=sys.stderr)
        sys.exit(1)

    if args.live:
        serve_live(valid_dirs, port=args.port, refresh_interval=args.interval)
        return

    # Static generation
    runs: List[Dict[str, Any]] = []
    for d in valid_dirs:
        events = load_events(d)
        snapshots = load_snapshots(d)
        stats = compute_stats(events, snapshots)
        label = os.path.basename(d.rstrip("/"))
        runs.append({"label": label, "dir": d, "events": events, "snapshots": snapshots, "stats": stats})
        print(f"  {d}: {len(events)} events, {len(snapshots)} snapshots")

    if len(runs) == 1:
        r = runs[0]
        out_path = args.out or os.path.join(r["dir"], "experience_graph_viz.html")
        html = build_html(r["events"], r["snapshots"], r["stats"], r["dir"])
    else:
        parent = os.path.dirname(runs[0]["dir"].rstrip("/"))
        ts = datetime.now().strftime("%m%d_%H%M%S")
        out_path = args.out or os.path.join(parent, f"viz_comparison_{ts}.html")
        html = build_comparison_html(runs)

    with open(out_path, "w") as f:
        f.write(html)
    print(f"\nVisualization written to: {out_path}")
    print("Open the file in a browser to explore.")


if __name__ == "__main__":
    main()
