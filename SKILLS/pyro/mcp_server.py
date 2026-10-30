"""
FastMCP server that provides Houdini fire generation tools.

This server wraps the pyro.py script and exposes it as MCP tools
that can be called by MCP clients (like pi, Claude Desktop, etc.).

Usage:
    python mcp_server.py
"""

import os
import sys
import subprocess
import json
from pathlib import Path
from typing import Optional

import yaml
from mcp.server.fastmcp import FastMCP

# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------
APP_DIR = Path(__file__).parent.resolve()
FIRE_YAML = APP_DIR / "fire.yaml"
OUTPUT_BGEO = APP_DIR / "fire.bgeo"
PYRO_SCRIPT = APP_DIR / "pyro.py"

# ----------------------------------------------------------------------
# FastMCP server
# ----------------------------------------------------------------------
mcp = FastMCP("Houdini Fire Generator")


@mcp.tool()
def get_fire_parameters() -> dict:
    """Get the current fire simulation parameters from fire.yaml."""
    if not FIRE_YAML.exists():
        return {"error": "fire.yaml not found"}
    with open(FIRE_YAML, "r") as f:
        return yaml.safe_load(f) or {}


@mcp.tool()
def update_fire_parameters(params: dict) -> dict:
    """Update fire simulation parameters and save to fire.yaml.

    Args:
        params: Dictionary with keys like temperature, density, fuel, smoke, gravity, fire, time.
    """
    # Load existing params
    if FIRE_YAML.exists():
        with open(FIRE_YAML, "r") as f:
            existing = yaml.safe_load(f) or {}
    else:
        existing = {}

    # Merge new params
    for key, value in params.items():
        if isinstance(value, dict) and key in existing:
            existing[key].update(value)
        else:
            existing[key] = value

    with open(FIRE_YAML, "w") as f:
        yaml.dump(existing, f, default_flow_style=False)

    return {"status": "success", "updated": params}


@mcp.tool()
def generate_fire() -> dict:
    """Generate the fire simulation by running pyro.py.

    Returns:
        Dictionary with status and path to the generated .bgeo file.
    """
    try:
        result = subprocess.run(
            [sys.executable, str(PYRO_SCRIPT)],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(APP_DIR),
        )
        if result.returncode != 0:
            return {
                "status": "error",
                "message": result.stderr or result.stdout,
                "returncode": result.returncode,
            }
        return {
            "status": "success",
            "file": str(OUTPUT_BGEO),
            "output": result.stdout,
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "Fire generation timed out"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@mcp.tool()
def get_fire_file_path() -> str:
    """Get the path to the generated fire.bgeo file."""
    return str(OUTPUT_BGEO)


@mcp.tool()
def fire_file_exists() -> bool:
    """Check if the fire.bgeo file exists."""
    return OUTPUT_BGEO.exists()


@mcp.tool()
def delete_fire_file() -> dict:
    """Delete the generated fire.bgeo file."""
    if OUTPUT_BGEO.exists():
        OUTPUT_BGEO.unlink()
        return {"status": "success", "message": "Deleted fire.bgeo"}
    return {"status": "info", "message": "fire.bgeo does not exist"}


if __name__ == "__main__":
    mcp.run()