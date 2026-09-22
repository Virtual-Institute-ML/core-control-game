from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from game_engine import CoreControlEngine
from physics_engine import FokkerPlanckRuntime

ROOT = Path(__file__).resolve().parent

app = FastAPI(title="Core Control v1.0")
physics = FokkerPlanckRuntime()
engine = CoreControlEngine(physics)

app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


class NewRunRequest(BaseModel):
    seed: int | None = None


class ActionRequest(BaseModel):
    run_id: str
    output_id: str
    control_id: str


class UpgradeRequest(BaseModel):
    run_id: str
    upgrade_id: str


class NextRequest(BaseModel):
    run_id: str


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "game": "Core Control v1.0",
        "physics": "persistent 1D Chang-Cooper Fokker-Planck solver",
        "velocity_cells": len(physics.velocity),
    }


@app.post("/api/new-run")
def new_run(req: NewRunRequest):
    return engine.new_run(req.seed)


@app.post("/api/action")
def action(req: ActionRequest):
    try:
        return engine.act(req.run_id, req.output_id, req.control_id)
    except (KeyError, ValueError, FloatingPointError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/upgrade")
def upgrade(req: UpgradeRequest):
    try:
        return engine.choose_upgrade(req.run_id, req.upgrade_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/next")
def next_turn(req: NextRequest):
    try:
        return engine.next_turn(req.run_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
