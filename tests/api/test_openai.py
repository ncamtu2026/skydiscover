"""
OpenAI GPT cloudcast request benchmark
Exact production setup (max_tokens=32000, non-streaming OpenAI SDK).
Logs full response to response_<timestamp>.txt for overhead investigation.
"""

import os
import time
from datetime import datetime

from openai import OpenAI

MODEL = "gpt-5"
API_BASE = "https://api.openai.com/v1"
MAX_TOKENS = 32000

# Real cloudcast request extracted from adaevolve log (same as test_deepseek.py)
MESSAGES = [
    {
        "role": "system",
        "content": (
            "You are an expert in cloud infrastructure optimization. Your task is to evolve the\n"
            "search_algorithm(src, dsts, G, num_partitions) function to minimize overall\n"
            "data transfer cost across multiple clouds.\n"
            "Focus on efficiently broadcasting input data to multiple destination nodes by leveraging\n"
            "parallel paths and overlapping transfers across networks. Use the BroadCastTopology\n"
            "class and make_nx_graph function to identify low-cost routes.\n"
            "Prioritize strategies that reduce redundant transfers, balance load across networks,\n"
            "and exploit multi-network topologies to minimize cost."
        ),
    },
    {
        "role": "user",
        "content": (
            "# Current Solution Information\n"
            "- Main Metrics: \n"
            "- combined_score: 0.0010\n"
            "\n"
            "Metrics:\n"
            "  - runs_successfully: 1.0000\n"
            "  - total_cost: 1035.1357\n"
            "  - avg_cost: 207.0271\n"
            "  - successful_configs: 5\n"
            "  - failed_configs: 0\n"
            "  - cost_score: 0.0010\n"
            "  - success_rate: 1.0000\n"
            "- Focus areas: - Consider simplifying - solution length exceeds 500 characters\n"
            "\n"
            "# Program Generation History\n"
            "## Previous Attempts\n"
            "\n"
            "No previous attempts yet.\n"
            "\n"
            "\n"
            "## Other Context Solutions\n"
            "These programs represent diverse approaches and creative solutions that may be relevant to the current task:\n"
            "\n"
            "### Program 1 (combined_score: 0.0010)\n"
            "Score breakdown:  - runs_successfully: 1.0000  - total_cost: 1035.1357  - avg_cost: 207.0271"
            "  - successful_configs: 5  - failed_configs: 0  - cost_score: 0.0010  - success_rate: 1.0000\n"
            "\n"
            "```python\n"
            "# EVOLVE-BLOCK-START\n"
            "import networkx as nx\n"
            "import json\n"
            "import os\n"
            "import pandas as pd\n"
            "from typing import Dict, List\n"
            "\n"
            "\n"
            "def search_algorithm(src, dsts, G, num_partitions):\n"
            "    h = G.copy()\n"
            "    h.remove_edges_from(list(h.in_edges(src)) + list(nx.selfloop_edges(h)))\n"
            "    bc_topology = BroadCastTopology(src, dsts, num_partitions)\n"
            "\n"
            "    for dst in dsts:\n"
            '        path = nx.dijkstra_path(h, src, dst, weight="cost")\n'
            "        for i in range(0, len(path) - 1):\n"
            "            s, t = path[i], path[i + 1]\n"
            "            for j in range(bc_topology.num_partitions):\n"
            "                bc_topology.append_dst_partition_path(dst, j, [s, t, G[s][t]])\n"
            "\n"
            "    return bc_topology\n"
            "# EVOLVE-BLOCK-END\n"
            "```\n"
            "\n"
            "\n"
            "# Current Solution\n"
            "\n"
            "## PARENT SELECTION CONTEXT\n"
            "This parent was selected through diversity-driven sampling to explore different regions.\n"
            "\n"
            "### EXPLORATION GUIDANCE\n"
            "- Consider alternative algorithmic approaches\n"
            "- Don't be constrained by the parent's approach\n"
            "- Look for fundamentally different algorithms or novel techniques\n"
            "- Balance creativity with correctness\n"
            "\n"
            "Your goal: Discover new approaches that might outperform current solutions.\n"
            "\n"
            "## Program Information\n"
            "combined_score: 0.0010\n"
            "\n"
            "```python\n"
            "# EVOLVE-BLOCK-START\n"
            "import networkx as nx\n"
            "import json\n"
            "import os\n"
            "import pandas as pd\n"
            "from typing import Dict, List\n"
            "\n"
            "\n"
            "def search_algorithm(src, dsts, G, num_partitions):\n"
            "    h = G.copy()\n"
            "    h.remove_edges_from(list(h.in_edges(src)) + list(nx.selfloop_edges(h)))\n"
            "    bc_topology = BroadCastTopology(src, dsts, num_partitions)\n"
            "\n"
            "    for dst in dsts:\n"
            '        path = nx.dijkstra_path(h, src, dst, weight="cost")\n'
            "        for i in range(0, len(path) - 1):\n"
            "            s, t = path[i], path[i + 1]\n"
            "            for j in range(bc_topology.num_partitions):\n"
            "                bc_topology.append_dst_partition_path(dst, j, [s, t, G[s][t]])\n"
            "\n"
            "    return bc_topology\n"
            "# EVOLVE-BLOCK-END\n"
            "```\n"
            "\n"
            "\n"
            "# Task\n"
            "Suggest improvements to the program that will improve its COMBINED_SCORE.\n"
            "The system maintains diversity across these dimensions: score, complexity.\n"
            "Different solutions with similar combined_score but different features are valuable.\n"
            "\n"
            "You MUST use the exact SEARCH/REPLACE diff format shown below to indicate changes:\n"
            "\n"
            "<<<<<<< SEARCH\n"
            "# Original code to find and replace (must match exactly)\n"
            "=======\n"
            "# New replacement code\n"
            ">>>>>>> REPLACE\n"
            "\n"
            "**CRITICAL**: Each SEARCH section must EXACTLY match code in \"# Current Solution\".\n"
            "Be thoughtful about your changes and explain your reasoning thoroughly.\n"
            "\n"
            "- Time limit: Programs should complete execution within 600 seconds; otherwise, they will timeout."
        ),
    },
]


def run() -> dict:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError("Set OPENAI_API_KEY env var")

    client = OpenAI(api_key=api_key, base_url=API_BASE)

    input_chars = sum(len(m["content"]) for m in MESSAGES)
    print(f"Model       : {MODEL}")
    print(f"max_tokens={MAX_TOKENS}")
    print(f"Input chars : {input_chars} (~{input_chars // 4} tokens estimated)\n")
    print("Sending request...")

    t0 = time.perf_counter()
    response = client.chat.completions.create(
        model=MODEL,
        messages=MESSAGES,
        stream=False,
        max_completion_tokens=MAX_TOKENS,
    )
    elapsed = time.perf_counter() - t0

    content = response.choices[0].message.content or ""
    usage = response.usage

    in_tokens = usage.prompt_tokens if usage else None
    out_tokens = usage.completion_tokens if usage else None
    reasoning_tokens = None
    if usage and hasattr(usage, "completion_tokens_details") and usage.completion_tokens_details:
        reasoning_tokens = getattr(usage.completion_tokens_details, "reasoning_tokens", None)

    tok_per_s = out_tokens / elapsed if out_tokens and elapsed > 0 else None

    search_replace_count = content.count("<<<<<<< SEARCH")
    code_block_count = content.count("```")

    print(f"\n{'='*60}")
    print(f"RESULT")
    print(f"{'='*60}")
    print(f"Latency     : {elapsed:.2f}s")
    print(f"Throughput  : {tok_per_s:.1f} tok/s" if tok_per_s else "Throughput  : N/A")
    print(f"Tokens in   : {in_tokens}")
    print(f"Tokens out  : {out_tokens}" + (f"  (reasoning: {reasoning_tokens})" if reasoning_tokens else ""))
    print(f"Response len: {len(content)} chars")
    print(f"SEARCH/REPLACE blocks: {search_replace_count}")
    print(f"Code blocks (``` pairs): {code_block_count // 2}")

    out_dir = os.path.dirname(os.path.abspath(__file__))
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(out_dir, f"response_{ts}.txt")
    with open(out_path, "w") as f:
        f.write(f"# model={MODEL}  elapsed={elapsed:.2f}s  in={in_tokens}  out={out_tokens}\n\n")
        f.write(content)
    print(f"\nFull response saved → {out_path}")

    print(f"\n--- response preview (first 500 chars) ---\n{content[:500]}\n---")

    return {
        "elapsed_s": elapsed,
        "tok_per_s": tok_per_s,
        "in_tokens": in_tokens,
        "out_tokens": out_tokens,
        "reasoning_tokens": reasoning_tokens,
        "search_replace_blocks": search_replace_count,
        "response_path": out_path,
    }


if __name__ == "__main__":
    run()
