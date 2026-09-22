from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

from fp_solver_v1 import maxwellian, normalize_distribution, solve_fp, velocity_grid


@dataclass(frozen=True)
class PhysicsStep:
    distribution: np.ndarray
    d0: float
    nu: float
    equilibrium_sigma: float
    duration: float
    mass: float
    sigma: float
    tail_fraction: float
    shape_error: float
    model_heat: float
    model_stress: float


class FokkerPlanckRuntime:
    """Persistent 1-D Fokker--Planck runtime used by Core Control.

    A run owns one distribution f(v). Every game turn advances that exact
    distribution by one finite interval; no turn reinitializes f to a new
    Maxwellian.  The equation is

        df/dt = d/dv[D(v) df/dv] + nu (f_eq - f),
        D(v)  = D0 (1 + 0.1 v^2),

    with zero-flux velocity boundaries and a Chang--Cooper finite-volume
    discretization in fp_solver_v1.py.
    """

    def __init__(
        self,
        *,
        vmin: float = -8.0,
        vmax: float = 8.0,
        nv: int = 400,
        internal_dt: float = 0.05,
        initial_sigma: float = 0.85,
        normal_sigma: float = 0.85,
    ) -> None:
        self.velocity, self.dv = velocity_grid(vmin, vmax, nv)
        self.internal_dt = float(internal_dt)
        self.initial_sigma = float(initial_sigma)
        self.normal_sigma = float(normal_sigma)
        self.normal_curve = maxwellian(self.velocity, sigma=self.normal_sigma)

    def initial_distribution(self) -> np.ndarray:
        return maxwellian(self.velocity, sigma=self.initial_sigma)

    def advance(
        self,
        distribution: np.ndarray,
        *,
        d0: float,
        nu: float,
        equilibrium_sigma: float,
        duration: float,
    ) -> PhysicsStep:
        d0 = float(np.clip(d0, 0.005, 1.0))
        nu = float(np.clip(nu, 0.0, 1.5))
        equilibrium_sigma = float(np.clip(equilibrium_sigma, 0.50, 2.0))
        duration = float(np.clip(duration, 0.10, 2.0))

        f0 = np.asarray(distribution, dtype=float).copy()
        f0[f0 < 0.0] = 0.0
        f0 = normalize_distribution(f0, self.dv, mass=1.0)
        f_eq = maxwellian(self.velocity, sigma=equilibrium_sigma)

        def diffusion(x: np.ndarray) -> np.ndarray:
            return d0 * (1.0 + 0.1 * x**2)

        solution = solve_fp(
            self.velocity,
            f0,
            np.asarray([duration], dtype=float),
            drift=0.0,
            diffusion=diffusion,
            nu_collision=nu,
            f_equilibrium=f_eq,
            dt=self.internal_dt,
            theta=1.0,
        )
        f1 = np.asarray(solution.f[-1], dtype=float)
        f1[f1 < 0.0] = 0.0
        f1 = normalize_distribution(f1, self.dv, mass=1.0)
        metrics = self.metrics(f1)
        return PhysicsStep(
            distribution=f1,
            d0=d0,
            nu=nu,
            equilibrium_sigma=equilibrium_sigma,
            duration=duration,
            **metrics,
        )

    def metrics(self, distribution: np.ndarray) -> dict[str, float]:
        f = np.maximum(np.asarray(distribution, dtype=float), 0.0)
        f = normalize_distribution(f, self.dv, mass=1.0)
        mass = float(np.sum(f) * self.dv)
        mean = float(np.sum(self.velocity * f) * self.dv)
        variance = float(np.sum((self.velocity - mean) ** 2 * f) * self.dv)
        sigma = math.sqrt(max(variance, 0.0))
        tail = float(np.sum(f[np.abs(self.velocity) >= 2.5]) * self.dv)

        matched_gaussian = maxwellian(self.velocity, sigma=max(sigma, 0.05), mean=mean)
        shape_error = float(np.sum(np.abs(f - matched_gaussian)) * self.dv)

        # Player-facing meters. These are dimensionless game mappings of
        # physically derived moments/tails, not literal reactor temperature
        # or engineering stress values.
        heat = float(np.clip(100.0 * (sigma - 0.55) / (1.65 - 0.55), 0.0, 100.0))
        tail_score = float(np.clip(100.0 * tail / 0.18, 0.0, 100.0))
        shape_score = float(np.clip(100.0 * shape_error / 0.12, 0.0, 100.0))
        model_stress = float(np.clip(0.62 * tail_score + 0.38 * shape_score, 0.0, 100.0))

        return {
            "mass": mass,
            "sigma": sigma,
            "tail_fraction": tail,
            "shape_error": shape_error,
            "model_heat": heat,
            "model_stress": model_stress,
        }
