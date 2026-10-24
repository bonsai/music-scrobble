"""
FastAPI application for Houdini Fire generation.
Provides REST endpoints and serves the HTML front-end.
"""

import os
import subprocess
import sys
from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# ----------------------------------------------------------------------
# Paths
# ----------------------------------------------------------------------
APP_DIR = Path(__file__).parent.resolve()
FIRE_YAML = APP_DIR / "fire.yaml"
OUTPUT_BGEO = APP_DIR / "fire.bgeo"
PYRO_SCRIPT = APP_DIR / "pyro.py"

# ----------------------------------------------------------------------
# FastAPI app
# ----------------------------------------------------------------------
app = FastAPI(
    title="Houdini Fire FastAPI Service",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def load_fire_params() -> dict:
    """Load parameters from fire.yaml."""
    if not FIRE_YAML.exists():
        return {}
    try:
        with open(FIRE_YAML, "r") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def update_fire_params(params: dict) -> dict:
    """Update fire parameters in fire.yaml."""
    existing = load_fire_params()
    for k, v in params.items():
        if isinstance(v, dict) and k in existing:
            existing[k].update(v)
        else:
            existing[k] = v
    with open(FIRE_YAML, "w") as f:
        yaml.dump(existing, f, default_flow_style=False)
    return existing


def run_pyro():
    result = subprocess.run(
        [sys.executable, str(PYRO_SCRIPT)],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(APP_DIR),
    )
    if result.returncode != 0:
        raise RuntimeError(f"pyro.py failed: {result.stderr}")
    return result


# ----------------------------------------------------------------------
# Endpoints
# ----------------------------------------------------------------------
@app.post("/fire/generate")
def generate_fire():
    try:
        run_pyro()
        return {"status": "success", "file": str(OUTPUT_BGEO)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/fire/bgeo")
def serve_bgeo():
    if not OUTPUT_BGEO.exists():
        raise HTTPException(status_code=404, detail="Fire geometry not generated yet")
    return FileResponse(OUTPUT_BGEO, media_type="application/octet-stream")


@app.post("/fire/update")
def update_fire(params: dict):
    try:
        if not isinstance(params, dict):
            raise HTTPException(status_code=400, detail="Parameters must be a JSON object")
        return {"status": "success", "updated": update_fire_params(params)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/fire/params")
def get_params():
    return load_fire_params()


@app.post("/fire/delete")
def delete_fire():
    if OUTPUT_BGEO.exists():
        OUTPUT_BGEO.unlink()
        return {"status": "success", "message": "Deleted fire.bgeo"}
    return {"status": "info", "message": "fire.bgeo does not exist"}


@app.get("/")
def read_root():
    return FileResponse(APP_DIR / "index.html", media_type="text/html")


@app.on_event("startup")
async def startup_event():
    if not OUTPUT_BGEO.exists():
        try:
            run_pyro()
        except Exception as e:
            print(f"Failed to generate initial fire: {e}")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
