"""Pipeline + stages. A bullpen has one or more pipelines, each with an
ordered list of stages with probabilities (for weighted forecasting).

Default seed: Lead → Contacted → Qualified → Demo → Pilot → Closed-Won
                                                          ↘ Closed-Lost

Pipeline JSON shape:
  {
    "name": "default",
    "stages": [
      {"id": "lead",       "name": "Lead",        "probability": 0.05, "color": "#7a6f5f"},
      {"id": "contacted",  "name": "Contacted",   "probability": 0.15, "color": "#22d3ee"},
      {"id": "qualified",  "name": "Qualified",   "probability": 0.30, "color": "#34d399"},
      {"id": "demo",       "name": "Demo",        "probability": 0.50, "color": "#6ee7b7"},
      {"id": "pilot",      "name": "Pilot",       "probability": 0.75, "color": "#fbbf24"},
      {"id": "won",        "name": "Closed-Won",  "probability": 1.00, "color": "#34d399", "terminal": true},
      {"id": "lost",       "name": "Closed-Lost", "probability": 0.00, "color": "#f87171", "terminal": true}
    ],
    "default": true
  }
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Optional

from paths import DATA_DIR as REPO
BULLPENS_ROOT = REPO / "bullpens"


DEFAULT_PIPELINE = {
    "name": "default",
    "stages": [
        {"id": "lead",       "name": "Lead",        "probability": 0.05, "color": "#7a6f5f"},
        {"id": "contacted",  "name": "Contacted",   "probability": 0.15, "color": "#22d3ee"},
        {"id": "qualified",  "name": "Qualified",   "probability": 0.30, "color": "#34d399"},
        {"id": "demo",       "name": "Demo",        "probability": 0.50, "color": "#6ee7b7"},
        {"id": "pilot",      "name": "Pilot",       "probability": 0.75, "color": "#fbbf24"},
        {"id": "won",        "name": "Closed-Won",  "probability": 1.00, "color": "#34d399", "terminal": True},
        {"id": "lost",       "name": "Closed-Lost", "probability": 0.00, "color": "#f87171", "terminal": True},
    ],
    "default": True,
}


def _pipeline_dir(bullpen: str) -> Path:
    return BULLPENS_ROOT / bullpen / "pipelines"


def _pipeline_path(bullpen: str, name: str) -> Path:
    return _pipeline_dir(bullpen) / f"{name}.json"


def ensure_default(bullpen: str) -> dict:
    """Create the default pipeline if it doesn't exist. Returns the pipeline."""
    p = _pipeline_path(bullpen, "default")
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(DEFAULT_PIPELINE, indent=2) + "\n")
    return get(bullpen, "default")


def get(bullpen: str, name: str = "default") -> Optional[dict]:
    p = _pipeline_path(bullpen, name)
    if not p.exists():
        if name == "default":
            return ensure_default(bullpen)
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def list_pipelines(bullpen: str) -> list[dict]:
    d = _pipeline_dir(bullpen)
    if not d.exists():
        # Auto-create default on first access
        ensure_default(bullpen)
    out = []
    for p in sorted(d.glob("*.json")):
        try:
            out.append(json.loads(p.read_text()))
        except Exception:
            continue
    return out


def stage(pipeline: dict, stage_id: str) -> Optional[dict]:
    """Look up a stage by id within a pipeline."""
    for s in pipeline.get("stages", []):
        if s.get("id") == stage_id:
            return s
    return None


def stage_probability(pipeline: dict, stage_id: str) -> float:
    """Convenience — returns 0.0 if stage missing."""
    s = stage(pipeline, stage_id)
    return float(s.get("probability", 0.0)) if s else 0.0


def is_terminal(pipeline: dict, stage_id: str) -> bool:
    s = stage(pipeline, stage_id)
    return bool(s and s.get("terminal"))
