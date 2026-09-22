# Changelog

## v1.0.0

First GitHub-ready stable release of **Core Control**.

This release promotes the playtested v0.8 prototype to **v1.0** and packages it in a cleaner public-repository format.

### Highlights

- Persistent **1-D Fokker–Planck** reactor evolution across all 20 turns
- Score-attack gameplay centered on **survive first, optimize power second**
- Distinct control roles for **COOL** and **STABILIZE**
- **Core Load** mechanic that prevents `HIGH every turn` from being trivially optimal
- Random operating events, crisis turns, upgrades, and a successful-run-only leaderboard
- Advanced science panel showing the live distribution evolution

### Packaging / repository updates

- Version number updated from **v0.8** to **v1.0.0**
- README rewritten for GitHub publication
- Gameplay screenshot added to the repository
- Local leaderboard storage key moved to a v1.0-specific key
- Smoke test renamed to `test_v10_smoke.py`

## v0.8.0

Gameplay-balance pass after hands-on playtesting. The v0.7 game loop, persistent Fokker–Planck physics, Core Load system, upgrades, events, 20-turn record rules, and UI structure were intentionally unchanged.

### Control specialization

- **COOL** now costs **6 Battery** instead of 9.
  - It is the cheap, specialized response to high HEAT.
  - Its Fokker–Planck action emphasizes reduced diffusion and a cooler equilibrium state.
  - It provides essentially no direct operational-Stress relief.
- **STABILIZE** now costs **10 Battery** instead of 9.
  - It is the more expensive response to high STRESS / unstable distribution shape.
  - Its relaxation effect remains strong, but its direct cooling effect is deliberately weaker than COOL.
  - Direct operational-Stress relief is slightly strengthened.

### Design goal

The two buttons should no longer compete as near-substitutes at the same price:

- high HEAT + manageable STRESS → **COOL** should usually be the efficient choice;
- manageable HEAT + high STRESS → **STABILIZE** should justify its higher price;
- when both are high, Battery level and remaining turns create a real trade-off.

### Records

v0.8 used its own local leaderboard key because the Battery economy changed. Earlier-version records were not mixed with v0.8 records.
