"""Checkpoint Analysis Web App — Flask backend."""

import json
import os
import re
import difflib
from flask import Flask, request, jsonify, send_from_directory, Response, stream_with_context

app = Flask(__name__)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_iteration(name: str) -> int:
    m = re.search(r"checkpoint_(\d+)$", name)
    return int(m.group(1)) if m else -1


def resolve_checkpoints_dir(path: str) -> str | None:
    """Resolve the directory that contains checkpoint_N subdirectories.

    Accepts:
      - an output_dir that has a 'checkpoints/' subdir
      - a 'checkpoints/' directory directly
      - a directory that itself contains checkpoint_N entries
    """
    path = path.strip()
    if not os.path.isdir(path):
        return None
    try:
        entries = os.listdir(path)
    except PermissionError:
        return None
    # Already a checkpoints dir?
    if any(re.match(r"checkpoint_\d+$", e) for e in entries):
        return path
    # Has a checkpoints/ subdir?
    sub = os.path.join(path, "checkpoints")
    if os.path.isdir(sub):
        return sub
    return None


def load_summary(cp_path: str, source_dir: str) -> dict:
    """Load lightweight metadata for one checkpoint (no program code)."""
    name = os.path.basename(cp_path)
    result: dict = {
        "path": cp_path,
        "name": name,
        "iteration": parse_iteration(name),
        "metrics": {},
        "best_score": None,
        "best_program_id": None,
        "program_count": 0,
        "source_dir": source_dir,
    }

    info_path = os.path.join(cp_path, "best_program_info.json")
    if os.path.exists(info_path):
        try:
            with open(info_path) as f:
                info = json.load(f)
            result["metrics"] = info.get("metrics", {})
            result["best_program_id"] = info.get("id")
        except Exception:
            pass

    meta_path = os.path.join(cp_path, "metadata.json")
    if os.path.exists(meta_path):
        try:
            with open(meta_path) as f:
                meta = json.load(f)
            if not result["best_program_id"]:
                result["best_program_id"] = meta.get("best_program_id")
        except Exception:
            pass

    prog_dir = os.path.join(cp_path, "programs")
    if os.path.isdir(prog_dir):
        result["program_count"] = sum(
            1 for f in os.listdir(prog_dir) if f.endswith(".json")
        )

    m = result["metrics"]
    if "combined_score" in m:
        result["best_score"] = m["combined_score"]
    elif m:
        numeric = [v for v in m.values() if isinstance(v, (int, float))]
        result["best_score"] = max(numeric) if numeric else None

    return result


def get_best_code(cp_path: str) -> str:
    """Return the best program source from a checkpoint directory."""
    try:
        for fname in sorted(os.listdir(cp_path)):
            if fname.startswith("best_program") and not fname.endswith(".json"):
                fpath = os.path.join(cp_path, fname)
                with open(fpath) as f:
                    return f.read()
    except Exception:
        pass
    # Fallback: read from programs/<best_program_id>.json
    meta_path = os.path.join(cp_path, "metadata.json")
    if os.path.exists(meta_path):
        try:
            with open(meta_path) as f:
                meta = json.load(f)
            bp_id = meta.get("best_program_id")
            if bp_id:
                prog_path = os.path.join(cp_path, "programs", f"{bp_id}.json")
                with open(prog_path) as f:
                    prog = json.load(f)
                return prog.get("solution", "")
        except Exception:
            pass
    return ""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory(SCRIPT_DIR, "index.html")


@app.route("/api/load", methods=["POST"])
def api_load():
    """Load and sort checkpoints from one or more directories."""
    dirs = (request.json or {}).get("dirs", [])
    dir_order = {d.strip(): i for i, d in enumerate(dirs)}
    all_cps: list[dict] = []

    for raw_dir in dirs:
        cp_dir = resolve_checkpoints_dir(raw_dir)
        if not cp_dir:
            continue
        try:
            entries = os.listdir(cp_dir)
        except PermissionError:
            continue
        for entry in entries:
            if not re.match(r"checkpoint_\d+$", entry):
                continue
            ep = os.path.join(cp_dir, entry)
            if os.path.isdir(ep):
                summary = load_summary(ep, raw_dir.strip())
                all_cps.append(summary)

    all_cps.sort(
        key=lambda x: (dir_order.get(x["source_dir"], 999), x["iteration"])
    )
    return jsonify(all_cps)


@app.route("/api/best-code", methods=["POST"])
def api_best_code():
    cp_path = (request.json or {}).get("path", "")
    if not os.path.isdir(cp_path):
        return jsonify({"error": "not found"}), 404
    return jsonify({"code": get_best_code(cp_path)})


@app.route("/api/programs", methods=["POST"])
def api_programs():
    """Return all candidate programs for a checkpoint, sorted by score."""
    cp_path = (request.json or {}).get("path", "")
    if not os.path.isdir(cp_path):
        return jsonify([])

    prog_dir = os.path.join(cp_path, "programs")
    if not os.path.isdir(prog_dir):
        return jsonify([])

    programs = []
    for fname in os.listdir(prog_dir):
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(prog_dir, fname)) as f:
                p = json.load(f)
            programs.append(
                {
                    "id": p.get("id"),
                    "metrics": p.get("metrics", {}),
                    "iteration_found": p.get("iteration_found"),
                    "parent_id": p.get("parent_id"),
                    "generation": p.get("generation"),
                    "metadata": p.get("metadata", {}),
                    "solution": p.get("solution", ""),
                    "prompts": p.get("prompts"),
                }
            )
        except Exception:
            continue

    def _score(p: dict) -> float:
        m = p.get("metrics", {})
        if "combined_score" in m:
            return float(m["combined_score"])
        nums = [v for v in m.values() if isinstance(v, (int, float))]
        return max(nums) if nums else 0.0

    programs.sort(key=_score, reverse=True)
    return jsonify(programs)


@app.route("/api/diff", methods=["POST"])
def api_diff():
    data = request.json or {}
    a = (data.get("code_a") or "").splitlines(keepends=True)
    b = (data.get("code_b") or "").splitlines(keepends=True)
    label_a = data.get("label_a", "a")
    label_b = data.get("label_b", "b")
    diff = "".join(difflib.unified_diff(a, b, fromfile=label_a, tofile=label_b))
    return jsonify({"diff": diff})


@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    """Stream an LLM analysis of sampled checkpoints via Server-Sent Events."""
    data = request.json or {}
    cp_paths: list[str] = data.get("checkpoint_paths", [])
    cp_metas: dict[str, dict] = {
        m["path"]: m for m in data.get("checkpoint_metas", [])
    }
    api_base = (data.get("api_base") or "https://api.openai.com/v1").strip()
    api_key = (data.get("api_key") or "").strip() or os.environ.get("OPENAI_API_KEY", "")
    model = (data.get("model") or "gpt-4o").strip()
    prompt = (data.get("prompt") or "").strip()

    def build_context() -> str:
        parts = []
        for path in cp_paths:
            meta = cp_metas.get(path, {})
            iteration = meta.get("iteration", "?")
            metrics = meta.get("metrics", {})
            metrics_str = ", ".join(
                f"{k}: {v:.4f}" if isinstance(v, float) else f"{k}: {v}"
                for k, v in metrics.items()
            )
            code = get_best_code(path) if os.path.isdir(path) else ""
            if len(code) > 4000:
                code = code[:4000] + "\n# ... (truncated)"
            parts.append(
                f"### Checkpoint {iteration}\n"
                f"Metrics: {metrics_str}\n\n"
                f"```python\n{code}\n```"
            )
        return "\n\n---\n\n".join(parts)

    context = build_context()
    system = (
        "You are an expert AI research analyst specialising in evolutionary algorithm analysis. "
        "Analyse the evolution of algorithm solutions across checkpoints from an automated "
        "discovery system. Be specific, insightful, and identify concrete patterns."
    )
    user_msg = (
        f"Checkpoint evolution data:\n\n{context}\n\n---\n\n"
        + (
            prompt
            or (
                "Please analyse:\n"
                "1. Key algorithmic changes that drove improvements\n"
                "2. Major breakthroughs or turning points\n"
                "3. Dead ends or regressions worth noting\n"
                "4. What techniques or patterns worked best"
            )
        )
    )

    def generate():
        try:
            import openai

            client = openai.OpenAI(api_key=api_key, base_url=api_base)
            stream = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_msg},
                ],
                stream=True,
                max_tokens=8192,
            )
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield f"data: {json.dumps({'text': chunk.choices[0].delta.content})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        yield "data: [DONE]\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    app.run(debug=True, port=5050, threaded=True)
