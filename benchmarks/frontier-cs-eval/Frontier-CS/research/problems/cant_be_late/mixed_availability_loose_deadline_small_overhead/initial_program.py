"""
Seed solution for cant-be-late scheduling problem.

Implements a 4-rule greedy policy:
  1. Thrifty:      job done → NONE
  2. Sticky OD:    once on ON_DEMAND, stay until done
  3. Exploitation: stay on SPOT until preempted
  4. Safety Net:   R < C + 2d → switch to ON_DEMAND permanently
"""
import json
from argparse import Namespace

from sky_spot.strategies.strategy import Strategy
from sky_spot.utils import ClusterType

# EVOLVE-BLOCK-START
class Solution(Strategy):
    """4-rule greedy: exploit spot freely, fall back to on-demand only when deadline is at risk."""

    NAME = "greedy_4rule"

    def solve(self, spec_path: str) -> "Solution":
        with open(spec_path) as f:
            config = json.load(f)
        args = Namespace(
            deadline_hours=float(config["deadline"]),
            task_duration_hours=[float(config["duration"])],
            restart_overhead_hours=[float(config["overhead"])],
            inter_task_overhead=[0.0],
        )
        super().__init__(args)
        return self

    @classmethod
    def _from_args(cls, parser):
        args, _ = parser.parse_known_args()
        return cls(args)

    def _step(self, last_cluster_type: ClusterType, has_spot: bool) -> ClusterType:
        C = self.task_duration - sum(self.task_done_time)
        R = self.deadline - self.env.elapsed_seconds
        d = self.restart_overhead

        # Rule 1 — Thrifty: job finished
        if C <= 1e-9:
            return ClusterType.NONE

        # Rule 2 — Sticky ON_DEMAND: once committed, stay until done
        if last_cluster_type == ClusterType.ON_DEMAND:
            return ClusterType.ON_DEMAND

        # Rule 3 — Exploitation: stay on spot until preempted
        if last_cluster_type == ClusterType.SPOT and has_spot:
            return ClusterType.SPOT
        # (if SPOT but preempted, fall through to IDLE logic below)

        # Rule 4 — Safety Net (IDLE state): switch permanently to on-demand if buffer exhausted
        if R < C + 2 * d:
            return ClusterType.ON_DEMAND

        return ClusterType.SPOT if has_spot else ClusterType.NONE
# EVOLVE-BLOCK-END
