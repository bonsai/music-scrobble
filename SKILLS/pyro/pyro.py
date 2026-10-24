"""
pyro.py - Houdini Python script that builds the fire (pyro) network,
reads fire.yaml, cooks the simulation, and exports baked geometry as .bgeo.

Run inside Houdini via Python Shell or import into a HDA.
If Houdini (hou module) is not available, creates an empty placeholder
so the FastAPI service can still start (you must replace with real .bgeo later).
"""

import os
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

HOUDINI_AVAILABLE = False
try:
    import hou
    HOUDINI_AVAILABLE = True
except ImportError:
    print("WARNING: 'hou' module not found - Houdini Engine not installed.")
    print("         Creating placeholder fire.bgeo for FastAPI service only.")
    HOUDINI_AVAILABLE = False


def load_fire_params(path="fire.yaml"):
    """Load parameters from fire.yaml. Falls back to defaults if YAML isn't available."""
    defaults = {
        "temperature": {"scale": 1.0, "value": 1.0},
        "density":     {"scale": 0.1, "value": 1.0},
        "fuel":        {"concentration": 0.5, "scale": 1.0},
        "smoke":       {"scale": 0.5, "value": 1.0},
        "gravity":     {"x": 0.0, "y": -9.81, "z": 0.0},
        "fire":        {"enable": True, "temperature_multiplier": 2.0, "density_multiplier": 1.5},
        "time":        {"start_frame": 1, "end_frame": 120},
    }

    if yaml is None:
        print("PyYAML not installed - using default parameters.")
        return defaults

    # Resolve relative to this script's directory
    script_dir = Path(__file__).parent.resolve()
    full_path = script_dir / path

    if not full_path.exists():
        print(f"{full_path} not found - using default parameters.")
        return defaults

    try:
        with open(full_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        for section in defaults:
            if section not in data:
                data[section] = defaults[section]
            else:
                for key in defaults[section]:
                    if key not in data[section]:
                        data[section][key] = defaults[section][key]
        return data
    except Exception as e:
        print(f"Failed to load {full_path}: {e}. Using default parameters.")
        return defaults


def create_placeholder_bgeo(path):
    """Create an empty .bgeo placeholder so the service doesn't crash."""
    with open(path, "wb") as f:
        # Minimal placeholder - not a real .bgeo, just enough to exist
        f.write(b"# Houdini Engine placeholder .bgeo file\n")
    print(f"Placeholder created at: {path}")


def create_fire():
    """Build the pyro fire setup, cook, and export to fire.bgeo."""
    params = load_fire_params("fire.yaml")
    out_path = os.path.abspath("fire.bgeo")

    if not HOUDINI_AVAILABLE:
        create_placeholder_bgeo(out_path)
        return None, out_path

    # ------------------------------------------------------------
    # 1. Geometry container
    # ------------------------------------------------------------
    geo = hou.node("/root").createNode("geo", node_type="Geometry")
    geo.setName("fire")
    geo.setDisplayFlag(True)

    # ------------------------------------------------------------
    # 2. DOP Network with source + pyro solver
    # ------------------------------------------------------------
    dopnet = geo.createNode("dopnet", node_type="DopNetwork")
    dopnet.setName("fire_dopnet")

    source_geo = dopnet.createNode("geo", node_name="source_geo")
    box = source_geo.createNode("box", node_name="box1")
    box.parm("sizex").set(2.0)
    box.parm("sizey").set(2.0)
    box.parm("sizez").set(2.0)

    solver = dopnet.createNode("pyro", node_name="pyro_solver")
    solver.setInput(0, source_geo)

    # ------------------------------------------------------------
    # 3. Apply parameters from fire.yaml
    # ------------------------------------------------------------
    temp = params["temperature"]
    solver.setParmTuple("temperature", (temp["scale"], temp["value"], 0.0))

    dens = params["density"]
    solver.setParmTuple("density", (dens["scale"], dens["value"], 0.0))

    fuel = params["fuel"]
    solver.setParm("fuel_concentration", fuel["concentration"])
    solver.setParm("fuel_scale", fuel["scale"])

    smoke = params["smoke"]
    solver.setParmTuple("smoke", (smoke["scale"], smoke["value"], 0.0))

    grav = params["gravity"]
    solver.setParmTuple("gravity", (grav["x"], grav["y"], grav["z"]))

    fire_cfg = params["fire"]
    solver.setParm("fire_enable", 1 if fire_cfg["enable"] else 0)
    solver.setParm("fire_temperature_multiplier", fire_cfg["temperature_multiplier"])
    solver.setParm("fire_density_multiplier", fire_cfg["density_multiplier"])

    time_cfg = params["time"]
    solver.setParm("start_frame", time_cfg["start_frame"])
    solver.setParm("end_frame", time_cfg["end_frame"])

    # ------------------------------------------------------------
    # 4. Cook and export
    # ------------------------------------------------------------
    solver.cook()
    geo_node = solver.outputs()[0] if solver.outputs() else solver
    geo_node.geometry().save(out_path)
    print(f"Exported fire geometry to: {out_path}")

    return solver, out_path


if __name__ == "__main__":
    create_fire()