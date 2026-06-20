"""Pure unit tests for the GraphEvolve policy (no LLM, no graph)."""

import random
from types import SimpleNamespace

from skydiscover.search.graphevolve.policy import (
    CROSSOVER,
    EXPLOIT,
    NEW_DIR,
    NEW_FORM,
    SPACE_EXPLORE,
    DirectionStats,
    GraphEvolvePolicy,
    PolicyState,
)


def _cfg(**overrides):
    base = dict(
        sigmoid_lambda=100.0,
        tau_stag=0.01,
        decay_rho=0.9,
        bandit_alpha=0.5,
        bandit_beta=0.5,
        w_max=10.0,
        ucb_c=1.0,
        powerlaw_alpha=1.0,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _policy(state=None, seed=0, **cfg):
    return GraphEvolvePolicy(_cfg(**cfg), state or PolicyState(), rng=random.Random(seed))


def test_choose_action_no_directions_is_exploit():
    p = _policy()
    assert p.choose_action(has_directions=False) == EXPLOIT


def test_cold_direction_always_chosen():
    # d1 is cold (pull_count 0); d2 has been pulled. Cold must win every time.
    state = PolicyState(pull_count={"d2": 5}, t=10)
    p = _policy(state)
    d1 = DirectionStats(node_id="d1", scores=[0.1])
    d2 = DirectionStats(node_id="d2", scores=[0.9, 0.95])
    for _ in range(20):
        assert p.choose_direction([d1, d2]) == "d1"


def test_warm_ucb_prefers_higher_mean_when_variance_zero():
    state = PolicyState(pull_count={"a": 3, "b": 3}, t=50)
    p = _policy(state)
    a = DirectionStats(node_id="a", scores=[0.2, 0.2, 0.2])  # mu=0.2 var=0
    b = DirectionStats(node_id="b", scores=[0.8, 0.8, 0.8])  # mu=0.8 var=0
    assert p.choose_direction([a, b]) == "b"


def test_powerlaw_alpha_zero_is_uniformish():
    p = _policy(powerlaw_alpha=0.0, seed=1)
    scores = [0.0, 1.0, 2.0, 3.0]
    counts = {i: 0 for i in range(4)}
    for _ in range(4000):
        counts[p.sample_powerlaw(scores)] += 1
    # Uniform => each ~1000; allow generous slack.
    for i in range(4):
        assert 700 < counts[i] < 1300


def test_powerlaw_large_alpha_picks_best():
    p = _policy(powerlaw_alpha=50.0, seed=2)
    scores = [0.0, 1.0, 2.0, 3.0]  # index 3 is best
    for _ in range(50):
        assert p.sample_powerlaw(scores) == 3


def test_sample_context_distinct_and_excludes():
    p = _policy(seed=3)
    scores = [0.1, 0.2, 0.3, 0.4]
    ctx = p.sample_context(scores, m=2, exclude={3})
    assert len(ctx) == 2
    assert len(set(ctx)) == 2
    assert 3 not in ctx


def test_bandit_reward_updates():
    p = _policy()
    # win -> += alpha
    p.update_action_reward(EXPLOIT, improved=True)
    assert abs(p.state.w_exploit - 1.5) < 1e-9
    # loss -> max(1, beta*w) ; beta=0.5 so 1.5*0.5=0.75 -> clamped to 1.0
    p.update_action_reward(EXPLOIT, improved=False)
    assert abs(p.state.w_exploit - 1.0) < 1e-9


def test_bandit_weight_clipped_to_w_max():
    p = _policy(w_max=2.0)
    for _ in range(20):
        p.update_action_reward(EXPLOIT, improved=True)
    assert p.state.w_exploit <= 2.0 + 1e-9


def test_crossover_is_fixed_anchor():
    p = _policy()
    before = (p.state.w_exploit, p.state.w_crossover)
    p.update_action_reward(CROSSOVER, improved=True)
    assert (p.state.w_exploit, p.state.w_crossover) == before


def test_space_bandit_only_updates_new_form():
    p = _policy()
    p.update_space_reward(NEW_DIR, improved=True)
    assert p.state.w_new_form == 1.0 and p.state.w_new_dir == 1.0
    p.update_space_reward(NEW_FORM, improved=True)
    assert abs(p.state.w_new_form - 1.5) < 1e-9


def test_p_space_monotonic_decreasing_in_g_global():
    p = _policy()
    p.state.G_global = 0.0
    high = p.p_space()  # G below tau -> large p_space
    p.state.G_global = 1.0
    low = p.p_space()  # G above tau -> small p_space
    assert high > low
    assert 0.0 <= low <= high <= 1.0


def test_update_global_tracks_best_and_signal():
    p = _policy()
    p.update_global(1.0)
    assert p.state.best_global == 1.0
    assert p.state.G_global == 0.0  # first observation only sets best
    p.update_global(2.0)  # improvement -> signal rises
    assert p.state.best_global == 2.0
    assert p.state.G_global > 0.0
    g_after_improve = p.state.G_global
    p.update_global(0.5)  # no improvement -> signal decays toward 0
    assert p.state.best_global == 2.0
    assert p.state.G_global < g_after_improve


def test_choose_space_target_respects_weights():
    state = PolicyState(w_new_form=1e6, w_new_dir=1.0)
    p = _policy(state, seed=4)
    assert all(p.choose_space_target() == NEW_FORM for _ in range(20))


def test_choose_action_space_when_stagnant():
    # G_global well below tau and equal exploit/crossover weights.
    state = PolicyState(G_global=0.0)
    p = _policy(state, seed=5)
    actions = {p.choose_action(has_directions=True) for _ in range(50)}
    assert SPACE_EXPLORE in actions
