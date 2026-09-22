"""Smoke checks for Core Control v1.0 persistent physics and load mechanics."""
from __future__ import annotations

import numpy as np

from game_engine import CoreControlEngine, CORE_LOAD_MAX, CONTROLS


def main() -> None:
    engine = CoreControlEngine()
    state = engine.new_run(seed=707)
    run_id = state["run_id"]
    f0 = engine.runs[run_id].distribution.copy()

    # HIGH builds persistent Core Load and evolves the same distribution.
    state = engine.act(run_id, "high", "hold")
    f1 = engine.runs[run_id].distribution.copy()
    assert state["core_load"] == 1
    assert not np.allclose(f0, f1)
    assert abs(np.sum(f1) * engine.physics.dv - 1.0) < 1e-10

    state = engine.next_turn(run_id)
    assert np.array_equal(f1, engine.runs[run_id].distribution)

    state = engine.act(run_id, "high", "hold")
    assert state["core_load"] == 2
    state = engine.next_turn(run_id)

    # NORMAL bleeds one level of load.
    state = engine.act(run_id, "normal", "hold")
    assert state["core_load"] == 1
    state = engine.next_turn(run_id)

    # LOW clears load and recovers Battery when there is room.
    battery_before = state["battery"]
    state = engine.act(run_id, "low", "hold")
    assert state["core_load"] == 0
    assert state["battery"] >= battery_before
    assert state["result"]["battery_recovery"] >= 0

    # v1.0 control specialization: COOL is cheaper and acts as the
    # stronger pure-heat tool, while STABILIZE is the stronger stress tool.
    cool_state = engine.new_run(seed=808)
    stab_state = engine.new_run(seed=808)
    assert CONTROLS["cool"]["cost"] == 6
    assert CONTROLS["stabilize"]["cost"] == 10
    cool_after = engine.act(cool_state["run_id"], "normal", "cool")
    stab_after = engine.act(stab_state["run_id"], "normal", "stabilize")
    assert cool_after["heat"] < stab_after["heat"]
    assert stab_after["stress"] < cool_after["stress"]

    # Damage is deliberately nonlinear in the red zone.
    assert engine._nonlinear_damage(85, 85) < engine._nonlinear_damage(95, 95)
    assert engine._nonlinear_damage(95, 95) < engine._nonlinear_damage(100, 100)

    # Repeated HIGH saturates at the configured maximum load.
    run = engine.runs[run_id]
    run.core_load = CORE_LOAD_MAX
    assert engine._next_core_load(run.core_load, "high") == CORE_LOAD_MAX

    print("PASS: v1.0 persistent f(v), control specialization, Core Load, LOW recovery, and nonlinear damage")


if __name__ == "__main__":
    main()
