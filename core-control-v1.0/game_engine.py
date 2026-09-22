from __future__ import annotations

from dataclasses import dataclass, field
import math
import random
import time
import uuid
from typing import Any

import numpy as np

from physics_engine import FokkerPlanckRuntime

MAX_TURNS = 20
MAX_INTEGRITY = 100
START_BATTERY = 90
BASE_MAX_BATTERY = 100
DANGER_THRESHOLD = 80.0
CORE_LOAD_MAX = 6
LOW_BATTERY_RECOVERY = 3
CONTROL_EFFICIENCY = {"low": 1.25, "normal": 1.00, "high": 0.65}
HIGH_LOAD_DIFFUSION_STEP = 0.22
HIGH_LOAD_RELAXATION_STEP = 0.08

# One persistent FP distribution is advanced every turn. Output changes the
# diffusion/relaxation balance; controls modify it further.
BASE_D0 = 0.070
BASE_NU = 0.180
BASE_DURATION = 0.80
BASE_EQ_SIGMA = 0.78

OUTPUTS = {
    "low": {
        "name": "LOW",
        "generation": 4,
        "d_mult": 0.55,
        "nu_mult": 1.30,
        "stress_load": -3.0,
        "risk": "Reset Load · Battery +3",
    },
    "normal": {
        "name": "NORMAL",
        "generation": 8,
        "d_mult": 1.00,
        "nu_mult": 1.00,
        "stress_load": 3.0,
        "risk": "Load -1 · normal control",
    },
    "high": {
        "name": "HIGH",
        "generation": 14,
        "d_mult": 2.25,
        "nu_mult": 0.65,
        "stress_load": 13.0,
        "risk": "Load +1 · control 35% weaker",
    },
}

CONTROLS = {
    "cool": {
        "name": "COOL",
        "icon": "❄",
        "description": "Cheap HEAT control. Strong cooling, little direct Stress relief.",
        "cost": 6,
        "d_mult": 0.45,
        "nu_mult": 1.15,
        "eq_sigma": 0.58,
        "stress_relief": 0.0,
    },
    "stabilize": {
        "name": "STABILIZE",
        "icon": "🛡",
        "description": "Expensive STRESS control. Strong stabilization, modest cooling.",
        "cost": 10,
        "d_mult": 0.96,
        "nu_mult": 3.20,
        "eq_sigma": 0.90,
        "stress_relief": 30.0,
    },
    "repair": {
        "name": "REPAIR",
        "icon": "🔧",
        "description": "Restore INTEGRITY.",
        "cost": 12,
        "d_mult": 1.00,
        "nu_mult": 1.00,
        "eq_sigma": BASE_EQ_SIGMA,
        "stress_relief": -2.0,
        "repair": 15,
    },
    "hold": {
        "name": "HOLD",
        "icon": "⏸",
        "description": "Spend no Battery. Let the current state evolve.",
        "cost": 0,
        "d_mult": 1.00,
        "nu_mult": 1.00,
        "eq_sigma": BASE_EQ_SIGMA,
        "stress_relief": 0.0,
    },
    "scram": {
        "name": "EMERGENCY",
        "icon": "🚨",
        "description": "One use. No power; force the core toward a safe state.",
        "cost": 20,
        "special": "scram",
        "stress_relief": 42.0,
        "integrity_cost": 2,
    },
}

# Events now perturb transition coefficients only. They never replace f(v).
EVENTS = [
    {
        "id": "steady_shift",
        "title": "STEADY SHIFT",
        "description": "Conditions are normal. Push for power or save resources.",
        "tag": "CALM",
        "d_mult": 1.00,
        "nu_mult": 1.00,
        "stress_load": -2.0,
    },
    {
        "id": "hot_air",
        "title": "HOT AIR INTAKE",
        "description": "The environment drives faster spreading this turn.",
        "tag": "HEAT +",
        "d_mult": 1.28,
        "nu_mult": 0.96,
        "stress_load": 1.0,
    },
    {
        "id": "vibration",
        "title": "CORE VIBRATION",
        "description": "Structural vibration makes the core harder to stabilize.",
        "tag": "STRESS +",
        "d_mult": 1.12,
        "nu_mult": 0.70,
        "stress_load": 12.0,
    },
    {
        "id": "power_bonus",
        "title": "POWER PRICE SPIKE",
        "description": "Extra generation is worth more this turn.",
        "tag": "POWER BONUS",
        "d_mult": 1.08,
        "nu_mult": 0.95,
        "stress_load": 1.0,
        "generation_bonus": {"low": 1, "normal": 2, "high": 4},
    },
    {
        "id": "control_fault",
        "title": "CONTROL GRID FAULT",
        "description": "Powered controls cost extra Battery this turn.",
        "tag": "BATTERY COST +3",
        "d_mult": 1.05,
        "nu_mult": 0.92,
        "stress_load": 4.0,
        "control_cost_add": 3,
    },
    {
        "id": "maintenance",
        "title": "MAINTENANCE CREW READY",
        "description": "Repairs are stronger this turn if you choose to use them.",
        "tag": "REPAIR BONUS",
        "d_mult": 0.96,
        "nu_mult": 1.05,
        "stress_load": -1.0,
        "repair_bonus": 8,
    },
]

CRISIS_EVENTS: dict[int, dict[str, Any]] = {
    5: {
        "id": "grid_demand",
        "title": "GRID DEMAND SURGE",
        "description": "A demand spike offers a large power bonus while loading the same evolving core.",
        "tag": "CRISIS · POWER BONUS",
        "d_mult": 1.18,
        "nu_mult": 0.90,
        "stress_load": 6.0,
        "generation_bonus": {"low": 1, "normal": 3, "high": 6},
        "crisis": True,
    },
    10: {
        "id": "heat_wave",
        "title": "COOLING LOOP STRAIN",
        "description": "Diffusive heating is stronger this turn.",
        "tag": "CRISIS · HEAT",
        "d_mult": 1.42,
        "nu_mult": 0.86,
        "stress_load": 4.0,
        "crisis": True,
    },
    15: {
        "id": "structural_shock",
        "title": "STRUCTURAL SHOCK",
        "description": "Relaxation is temporarily weakened and stress rises faster.",
        "tag": "CRISIS · STRESS",
        "d_mult": 1.20,
        "nu_mult": 0.52,
        "stress_load": 18.0,
        "crisis": True,
    },
    20: {
        "id": "final_push",
        "title": "FINAL PUSH",
        "description": "Last turn. Any power counts, but failure invalidates the entire run.",
        "tag": "FINAL TURN · POWER BONUS",
        "d_mult": 1.22,
        "nu_mult": 0.80,
        "stress_load": 8.0,
        "generation_bonus": {"low": 1, "normal": 2, "high": 4},
        "crisis": True,
    },
}

UPGRADES = {
    "efficient_cooling": {
        "name": "Efficient Cooling",
        "icon": "❄",
        "description": "COOL costs 3 less Battery.",
    },
    "precision_control": {
        "name": "Precision Control",
        "icon": "🛡",
        "description": "STABILIZE costs 3 less Battery.",
    },
    "reinforced_shell": {
        "name": "Reinforced Shell",
        "icon": "🧱",
        "description": "Reactor damage is reduced by 25%.",
    },
    "battery_pack": {
        "name": "Battery Pack",
        "icon": "🔋",
        "description": "+20 maximum Battery and +20 Battery now.",
    },
    "turbine_upgrade": {
        "name": "Turbine Upgrade",
        "icon": "⚡",
        "description": "NORMAL and HIGH generate +2 Power every turn.",
    },
    "repair_drones": {
        "name": "Repair Drones",
        "icon": "🔧",
        "description": "REPAIR costs 2 less Battery and restores 6 more Integrity.",
    },
}


@dataclass
class RunState:
    run_id: str
    seed: int
    turn: int = 1
    integrity: int = MAX_INTEGRITY
    battery: int = START_BATTERY
    max_battery: int = BASE_MAX_BATTERY
    heat: float = 0.0
    stress: float = 0.0
    operational_stress: float = 10.0
    generated_power: int = 0
    resolved: bool = False
    finished: bool = False
    survived: bool = False
    current: dict[str, Any] | None = None
    distribution: np.ndarray | None = None
    upgrades: list[str] = field(default_factory=list)
    upgrade_pending: bool = False
    emergency_used: bool = False
    damage_taken: int = 0
    high_turns: int = 0
    hold_turns: int = 0
    core_load: int = 0
    max_core_load_seen: int = 0


class CoreControlEngine:
    def __init__(self, physics: FokkerPlanckRuntime | None = None):
        self.physics = physics or FokkerPlanckRuntime()
        self.runs: dict[str, RunState] = {}

    @staticmethod
    def _rng(seed: int, turn: int, salt: int = 0) -> random.Random:
        return random.Random(seed * 1009 + turn * 9176 + salt)

    @staticmethod
    def _clip(x: float) -> float:
        return float(np.clip(x, 0.0, 100.0))

    @staticmethod
    def _curve_payload(v: np.ndarray, f: np.ndarray, max_points: int = 140) -> dict[str, list[float]]:
        step = max(1, int(math.ceil(len(v) / max_points)))
        return {
            "v": np.asarray(v[::step], dtype=float).round(6).tolist(),
            "f": np.asarray(f[::step], dtype=float).round(9).tolist(),
        }

    def _event_for_turn(self, run: RunState, turn: int) -> dict[str, Any]:
        if turn in CRISIS_EVENTS:
            return dict(CRISIS_EVENTS[turn])
        rng = self._rng(run.seed, turn, salt=4)
        event = dict(rng.choice(EVENTS))
        event["crisis"] = False
        return event

    def _make_turn(self, run: RunState) -> dict[str, Any]:
        return self._event_for_turn(run, run.turn)

    def _upgrade_options(self, run: RunState) -> list[dict[str, str]]:
        available = [k for k in UPGRADES if k not in run.upgrades]
        rng = self._rng(run.seed, run.turn, salt=88)
        rng.shuffle(available)
        return [{"id": k, **UPGRADES[k]} for k in available[:3]]

    def _control_cost(self, run: RunState, control_id: str) -> int:
        cost = int(CONTROLS[control_id]["cost"])
        if control_id == "cool" and "efficient_cooling" in run.upgrades:
            cost -= 3
        if control_id == "stabilize" and "precision_control" in run.upgrades:
            cost -= 3
        if control_id == "repair" and "repair_drones" in run.upgrades:
            cost -= 2
        if cost > 0 and run.current is not None:
            cost += int(run.current.get("control_cost_add", 0))
        return max(0, cost)

    def _generation_preview(self, run: RunState, output_id: str) -> int:
        generation = int(OUTPUTS[output_id]["generation"])
        if run.current is not None:
            generation += int((run.current.get("generation_bonus") or {}).get(output_id, 0))
        if "turbine_upgrade" in run.upgrades and output_id in ("normal", "high"):
            generation += 2
        return max(0, generation)

    @staticmethod
    def _next_core_load(current: int, output_id: str, emergency: bool = False) -> int:
        if emergency or output_id == "low":
            return 0
        if output_id == "normal":
            return max(0, current - 1)
        if output_id == "high":
            return min(CORE_LOAD_MAX, current + 1)
        return current

    @staticmethod
    def _control_efficiency(output_id: str) -> float:
        return float(CONTROL_EFFICIENCY[output_id])

    @staticmethod
    def _scaled_control_multiplier(multiplier: float, efficiency: float) -> float:
        # Interpolate a control multiplier around the neutral value 1.0.
        # Efficiency >1 strengthens the action; efficiency <1 weakens it.
        return max(0.05, 1.0 + efficiency * (float(multiplier) - 1.0))

    @staticmethod
    def _nonlinear_damage(heat: float, stress: float) -> int:
        heat_excess = max(0.0, float(heat) - DANGER_THRESHOLD)
        stress_excess = max(0.0, float(stress) - DANGER_THRESHOLD)
        damage = 0.055 * heat_excess**2 + 0.045 * stress_excess**2
        if heat > 95.0 and stress > 90.0:
            damage += 10.0
        return int(round(damage))

    def _control_public(self, run: RunState, control_id: str) -> dict[str, Any]:
        spec = CONTROLS[control_id]
        cost = self._control_cost(run, control_id)
        reason = None
        if run.finished or run.resolved or run.upgrade_pending:
            reason = "TURN LOCKED"
        elif control_id == "scram" and run.emergency_used:
            reason = "USED"
        elif cost > run.battery:
            reason = "LOW BATTERY"
        return {
            "id": control_id,
            "name": spec["name"],
            "icon": spec["icon"],
            "description": spec["description"],
            "cost": cost,
            "available": reason is None,
            "disabled_reason": reason,
        }

    def _forecast(self, run: RunState) -> dict[str, Any] | None:
        if run.turn >= MAX_TURNS:
            return None
        e = self._event_for_turn(run, run.turn + 1)
        return {
            "turn": run.turn + 1,
            "title": e["title"],
            "tag": e["tag"],
            "crisis": bool(e.get("crisis", False)),
        }

    def _public_state(self, run: RunState) -> dict[str, Any]:
        cur = run.current
        assert cur is not None and run.distribution is not None
        return {
            "run_id": run.run_id,
            "seed": run.seed,
            "turn": run.turn,
            "max_turns": MAX_TURNS,
            "integrity": run.integrity,
            "max_integrity": MAX_INTEGRITY,
            "battery": run.battery,
            "max_battery": run.max_battery,
            "heat": round(run.heat, 1),
            "stress": round(run.stress, 1),
            "generated_power": run.generated_power,
            "core_load": run.core_load,
            "max_core_load": CORE_LOAD_MAX,
            "resolved": run.resolved,
            "finished": run.finished,
            "survived": run.survived,
            "record_eligible": bool(run.finished and run.survived),
            "upgrade_pending": run.upgrade_pending,
            "upgrades": [{"id": u, **UPGRADES[u]} for u in run.upgrades],
            "upgrade_choices": self._upgrade_options(run) if run.upgrade_pending else [],
            "stats": {
                "damage_taken": run.damage_taken,
                "high_turns": run.high_turns,
                "hold_turns": run.hold_turns,
                "max_core_load_seen": run.max_core_load_seen,
            },
            "event": {
                "title": cur["title"],
                "description": cur["description"],
                "tag": cur["tag"],
                "crisis": bool(cur.get("crisis", False)),
            },
            "outputs": [
                {
                    "id": k,
                    "name": spec["name"],
                    "generation": self._generation_preview(run, k),
                    "risk": spec["risk"],
                    "control_efficiency": round(self._control_efficiency(k), 2),
                }
                for k, spec in OUTPUTS.items()
            ],
            "controls": [self._control_public(run, k) for k in CONTROLS],
            "forecast": self._forecast(run),
            "current_curve": self._curve_payload(self.physics.velocity, run.distribution),
            "normal_curve": self._curve_payload(self.physics.velocity, self.physics.normal_curve),
        }

    def new_run(self, seed: int | None = None) -> dict[str, Any]:
        if seed is None:
            seed = int(time.time_ns() % 2_147_483_647)
        run = RunState(run_id=str(uuid.uuid4()), seed=int(seed))
        run.distribution = self.physics.initial_distribution()
        m = self.physics.metrics(run.distribution)
        run.heat = float(m["model_heat"])
        run.stress = float(0.60 * m["model_stress"] + 0.40 * run.operational_stress)
        run.current = self._make_turn(run)
        self.runs[run.run_id] = run
        return self._public_state(run)

    def _transition_parameters(
        self,
        event: dict[str, Any],
        output_id: str,
        control_id: str,
        core_load: int,
    ) -> tuple[float, float, float, float, float]:
        output = OUTPUTS[output_id]
        control = CONTROLS[control_id]
        if control.get("special") == "scram":
            return 0.010, 1.10, 0.58, 1.10, 1.0

        efficiency = self._control_efficiency(output_id)
        control_d = self._scaled_control_multiplier(float(control["d_mult"]), efficiency)
        control_nu = self._scaled_control_multiplier(float(control["nu_mult"]), efficiency)
        eq_sigma = BASE_EQ_SIGMA + efficiency * (float(control.get("eq_sigma", BASE_EQ_SIGMA)) - BASE_EQ_SIGMA)

        d0 = BASE_D0 * float(event.get("d_mult", 1.0)) * float(output["d_mult"]) * control_d
        nu = BASE_NU * float(event.get("nu_mult", 1.0)) * float(output["nu_mult"]) * control_nu

        # Consecutive HIGH output builds Core Load. It directly strengthens
        # diffusion and weakens relaxation, so HIGH cannot be made harmless
        # simply by pressing STABILIZE every turn.
        if output_id == "high":
            d0 *= 1.0 + HIGH_LOAD_DIFFUSION_STEP * core_load
            nu *= max(0.40, 1.0 - HIGH_LOAD_RELAXATION_STEP * core_load)

        duration = BASE_DURATION * float(event.get("duration_mult", 1.0))
        return (
            float(np.clip(d0, 0.005, 1.0)),
            float(np.clip(nu, 0.0, 1.5)),
            float(np.clip(eq_sigma, 0.50, 2.0)),
            float(np.clip(duration, 0.10, 2.0)),
            efficiency,
        )

    def act(self, run_id: str, output_id: str, control_id: str) -> dict[str, Any]:
        if run_id not in self.runs:
            raise KeyError("Unknown run_id")
        run = self.runs[run_id]
        if run.finished:
            raise ValueError("Run is already finished")
        if run.upgrade_pending:
            raise ValueError("Choose an upgrade first")
        if run.resolved:
            raise ValueError("This turn has already been resolved")
        if output_id not in OUTPUTS:
            raise ValueError("Unknown output level")
        if control_id not in CONTROLS:
            raise ValueError("Unknown control")
        if run.distribution is None or run.current is None:
            raise ValueError("Run physics state is missing")

        control_public = self._control_public(run, control_id)
        if not control_public["available"]:
            raise ValueError(control_public["disabled_reason"] or "Control unavailable")

        output = OUTPUTS[output_id]
        control = CONTROLS[control_id]
        event = run.current
        before = {
            "integrity": run.integrity,
            "battery": run.battery,
            "heat": run.heat,
            "stress": run.stress,
            "generated_power": run.generated_power,
            "core_load": run.core_load,
        }

        cost = int(control_public["cost"])
        run.battery -= cost

        if control.get("special") == "scram":
            generation = 0
            effective_output_id = "scram"
            run.emergency_used = True
            run.core_load = 0
        else:
            generation = self._generation_preview(run, output_id)
            effective_output_id = output_id
            run.core_load = self._next_core_load(run.core_load, output_id)
        run.max_core_load_seen = max(run.max_core_load_seen, run.core_load)

        battery_recovery = 0
        if output_id == "low" and effective_output_id != "scram":
            old_battery = run.battery
            run.battery = min(run.max_battery, run.battery + LOW_BATTERY_RECOVERY)
            battery_recovery = run.battery - old_battery

        d0, nu, eq_sigma, duration, control_efficiency = self._transition_parameters(
            event, output_id, control_id, run.core_load
        )
        physics_step = self.physics.advance(
            run.distribution,
            d0=d0,
            nu=nu,
            equilibrium_sigma=eq_sigma,
            duration=duration,
        )
        run.distribution = physics_step.distribution

        # Operational stress is persistent. Controls are intentionally less
        # effective at HIGH output and stronger at LOW output. Consecutive HIGH
        # turns also add load stress, while LOW gives an extra recovery window.
        if control.get("special") == "scram":
            run.operational_stress -= float(control.get("stress_relief", 0.0))
        else:
            run.operational_stress += float(output.get("stress_load", 0.0))
            run.operational_stress += float(event.get("stress_load", 0.0))
            if output_id == "high":
                run.operational_stress += 2.5 * run.core_load
            run.operational_stress -= float(control.get("stress_relief", 0.0)) * control_efficiency
            run.operational_stress -= 1.5
            if output_id == "low":
                run.operational_stress -= 3.0
        run.operational_stress = self._clip(run.operational_stress)

        run.heat = self._clip(physics_step.model_heat)
        run.stress = self._clip(0.58 * physics_step.model_stress + 0.42 * run.operational_stress)
        run.generated_power += generation
        if output_id == "high" and effective_output_id != "scram":
            run.high_turns += 1
        if control_id == "hold":
            run.hold_turns += 1

        repaired = 0
        if control_id == "repair":
            repair_base = int(control.get("repair", 0)) + int(event.get("repair_bonus", 0))
            if "repair_drones" in run.upgrades:
                repair_base += 6
            repaired = max(1, int(round(repair_base * control_efficiency)))
            old = run.integrity
            run.integrity = min(MAX_INTEGRITY, run.integrity + repaired)
            repaired = run.integrity - old

        # Red-zone damage is deliberately nonlinear: nudging 82% is survivable,
        # sitting near 100% is dramatically more expensive.
        damage = self._nonlinear_damage(run.heat, run.stress)
        damage += int(control.get("integrity_cost", 0))
        if "reinforced_shell" in run.upgrades:
            damage = int(round(damage * 0.75))
        run.integrity = max(0, run.integrity - damage)
        run.damage_taken += damage

        run.resolved = True
        if run.integrity <= 0:
            run.finished = True
            run.survived = False
        elif run.turn == MAX_TURNS:
            run.finished = True
            run.survived = True
        elif run.turn in (5, 10, 15):
            run.upgrade_pending = True

        result = {
            "output_id": output_id,
            "output_name": output["name"],
            "control_id": control_id,
            "control_name": control["name"],
            "control_icon": control["icon"],
            "generation": generation,
            "effective_output": effective_output_id,
            "damage": max(0, before["integrity"] + repaired - run.integrity),
            "repaired": repaired,
            "battery_change": run.battery - before["battery"],
            "battery_recovery": battery_recovery,
            "heat_change": round(run.heat - before["heat"], 1),
            "stress_change": round(run.stress - before["stress"], 1),
            "core_load_change": run.core_load - before["core_load"],
            "core_load": run.core_load,
            "control_efficiency": round(control_efficiency, 2),
            "physics": {
                "D0": round(physics_step.d0, 5),
                "nu_collision": round(physics_step.nu, 5),
                "duration": round(physics_step.duration, 3),
                "equilibrium_sigma": round(physics_step.equilibrium_sigma, 3),
                "sigma": round(physics_step.sigma, 5),
                "tail_fraction": round(physics_step.tail_fraction, 6),
                "shape_error": round(physics_step.shape_error, 6),
                "mass": round(physics_step.mass, 9),
            },
            "curve": self._curve_payload(self.physics.velocity, run.distribution),
        }
        response = self._public_state(run)
        response["result"] = result
        return response

    def choose_upgrade(self, run_id: str, upgrade_id: str) -> dict[str, Any]:
        if run_id not in self.runs:
            raise KeyError("Unknown run_id")
        run = self.runs[run_id]
        if not run.upgrade_pending:
            raise ValueError("No upgrade is available now")
        offered = {u["id"] for u in self._upgrade_options(run)}
        if upgrade_id not in offered:
            raise ValueError("Upgrade was not offered")
        if upgrade_id in run.upgrades:
            raise ValueError("Upgrade already owned")
        run.upgrades.append(upgrade_id)
        if upgrade_id == "battery_pack":
            run.max_battery += 20
            run.battery = min(run.max_battery, run.battery + 20)
        run.upgrade_pending = False
        return self._public_state(run)

    def next_turn(self, run_id: str) -> dict[str, Any]:
        if run_id not in self.runs:
            raise KeyError("Unknown run_id")
        run = self.runs[run_id]
        if run.finished:
            return self._public_state(run)
        if run.upgrade_pending:
            raise ValueError("Choose an upgrade first")
        if not run.resolved:
            raise ValueError("Run the reactor first")
        run.turn += 1
        run.resolved = False
        run.current = self._make_turn(run)
        # Crucially, run.distribution is NOT reset here.
        return self._public_state(run)
