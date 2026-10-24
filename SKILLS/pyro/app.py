"""
FastAPI service that generates a Houdini fire simulation (.bgeo)
from fire.yaml and serves it.

Usage:
    uvicorn app:app --host 0.0.0.0 --port 8000

Endpoints:
    POST /fire/generate  – Generate fire geometry (calls pyro.py)
    GET  /fire/bgeo      – Serve the generated .bgeo file
"""

import os
import subprocess
import shutil
from pathlib import Path

import yaml
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import StreamingResponse

# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------
APP_DIR = Path(__file__).parent.resolve()
FIRE_YAML = APP_DIR / "fire.yaml"
OUTPUT_BGEO = APP_DIR / "fire.bgeo"
PYRO_SCRIPT = APP_DIR / "pyro.py"

# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def load_params() -> dict:
    """Load parameters from fire.yaml."""
    if not FIRE_YAML.exists():
        raise FileNotFoundError(f"{FIRE_YAML} not found")
    with open(FIRE_YAML, "r") as f:
        return yaml.safe_load(f) or {}

def run_pyro() -> None:
    """Run the Houdini pyro generation script."""
    # Ensure output directory exists
    OUTPUT_BGEO.parent.mkdir(parents=True, exist_ok=True)
    # Run pyro.py inside the same process (subprocess is safer if Houdini needs isolation)
    result = subprocess.run(
        [sys.executable, str(PYRO_SCRIPT)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        print("Pyro generation failed:")
        print(result.stderr)
        raise RuntimeError(f"pyro.py exited with code {result.returncode}")
    print("Fire generation completed successfully.")

# ----------------------------------------------------------------------
# FastAPI App
# ----------------------------------------------------------------------
app = FastAPI(title="Houdini Fire Service", version="1.0.0")

@app.on_event("startup")
async def startup():
    """Ensure the fire geometry is ready when the server starts."""
    if not OUTPUT_BGEO.exists():
        print("Generating initial fire geometry...")
        run_pyro()

@app.get("/fire/bgeo")
async def serve_bgeo() -> StreamingResponse:
    """Serve the baked .bgeo file."""
    if not OUTPUT_BGEO.exists():
        raise HTTPException(status_code=404, detail="Fire geometry not yet generated")
    return StreamingResponse(
        OUTPUT_BGEO.open("rb"),
        media_type="application/octet-stream",
    )

@app.post("/fire/generate")
async def generate_fire() -> dict:
    """Generate the fire simulation and return status."""
    try:
        run_pyro()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
    return {
        "status": "success",
        "file": str(OUTPUT_BGEO),
    }

if __name__ == "__main__":
    import sys
    app.run(host="0.0.0.0", port=8000)
