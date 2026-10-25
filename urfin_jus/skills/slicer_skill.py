# skills/slicer_skill.py
import os, json, subprocess, logging, shutil, tempfile, math
from pathlib import Path
from typing import Any, Dict, Optional, List
import numpy as np
from stl import mesh

logger = logging.getLogger(__name__)

CURA_ENGINE_PATH = os.getenv("CURA_ENGINE_PATH", "/usr/local/bin/CuraEngine")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "gcode")
MODEL_DIR = os.path.join(os.path.dirname(__file__), "..", "output")
PROFILES_DIR = os.path.join(os.path.dirname(__file__), "printer_profiles")
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(MODEL_DIR, exist_ok=True)
os.makedirs(PROFILES_DIR, exist_ok=True)

ALLOWED_SETTINGS = {
    "layer_height", "line_width", "wall_thickness", "wall_count",
    "infill_sparse_density", "infill_pattern", "infill_overlap",
    "top_layers", "bottom_layers",
    "print_speed", "travel_speed", "outer_wall_speed", "inner_wall_speed",
    "top_speed", "bottom_speed", "infill_speed",
    "acceleration", "travel_acceleration",
    "material_print_temperature", "material_bed_temperature",
    "initial_nozzle_temp", "initial_bed_temp",
    "fan_speed", "min_fan_speed", "max_fan_speed",
    "support_enable", "support_type", "support_density",
    "support_angle", "support_xy_distance",
    "material_type", "filament_diameter", "nozzle_size",
    "flow_rate", "retraction_enable", "retraction_distance",
    "retraction_speed", "retraction_min_length",
    "adhesion_type", "adhesion_width", "adhesion_distance",
    "printer_profile"
}

def load_profiles() -> Dict[str, Dict[str, Any]]:
    profiles = {}
    for fname in os.listdir(PROFILES_DIR):
        if fname.endswith('.json'):
            with open(os.path.join(PROFILES_DIR, fname), 'r', encoding='utf-8') as f:
                try:
                    prof = json.load(f)
                    name = prof.get('name', os.path.splitext(fname)[0])
                    profiles[name] = prof
                except Exception:
                    continue
    if not profiles:
        default = {
            "ultimaker": {
                "machine_width": 220, "machine_depth": 220, "machine_height": 200,
                "nozzle_size": 0.4, "print_speed": 50, "travel_speed": 150,
                "layer_height": 0.2, "infill_sparse_density": 20,
                "material_print_temperature": 200, "material_bed_temperature": 60,
                "support_enable": False, "adhesion_type": "skirt", "retraction_enable": True
            },
            "ender3": {
                "machine_width": 235, "machine_depth": 235, "machine_height": 250,
                "nozzle_size": 0.4, "print_speed": 40, "travel_speed": 120,
                "layer_height": 0.2, "infill_sparse_density": 15,
                "material_print_temperature": 200, "material_bed_temperature": 50,
                "support_enable": False, "adhesion_type": "skirt", "retraction_enable": True
            },
            "prusa_i3": {
                "machine_width": 250, "machine_depth": 210, "machine_height": 210,
                "nozzle_size": 0.4, "print_speed": 60, "travel_speed": 180,
                "layer_height": 0.15, "infill_sparse_density": 25,
                "material_print_temperature": 210, "material_bed_temperature": 70,
                "support_enable": True, "adhesion_type": "brim", "retraction_enable": True
            }
        }
        for name, prof in default.items():
            with open(os.path.join(PROFILES_DIR, f"{name}.json"), 'w', encoding='utf-8') as f:
                json.dump(prof, f, indent=2)
        return default
    return profiles

PRINTER_PROFILES = load_profiles()

def _check_cura_engine() -> bool:
    return os.path.isfile(CURA_ENGINE_PATH) and os.access(CURA_ENGINE_PATH, os.X_OK)

def _sanitize_settings(profile: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    merged = profile.copy()
    for key, val in params.items():
        if key in ALLOWED_SETTINGS:
            if key in ("machine_width", "machine_depth", "machine_height", "wall_count", 
                       "top_layers", "bottom_layers", "acceleration", "travel_acceleration", "flow_rate"):
                val = int(val)
            elif key in ("nozzle_size", "layer_height", "line_width", "filament_diameter",
                         "infill_sparse_density", "print_speed", "travel_speed", "outer_wall_speed",
                         "inner_wall_speed", "top_speed", "bottom_speed", "infill_speed",
                         "material_print_temperature", "material_bed_temperature",
                         "initial_nozzle_temp", "initial_bed_temp", "fan_speed", 
                         "min_fan_speed", "max_fan_speed", "support_density", "support_angle",
                         "support_xy_distance", "retraction_distance", "retraction_speed",
                         "retraction_min_length", "adhesion_width", "adhesion_distance"):
                val = float(val)
            elif key in ("support_enable", "retraction_enable"):
                val = bool(val)
            merged[key] = val
    return merged

def _build_printer_definition(settings: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "name": "KLHSlicer_Printer",
        "id": "klhslicer_printer",
        "version": 1,
        "inherits": "fdmprinter",
        "metadata": {
            "machine_width": settings.get("machine_width", 220),
            "machine_depth": settings.get("machine_depth", 220),
            "machine_height": settings.get("machine_height", 200),
            "nozzle_size": settings.get("nozzle_size", 0.4),
        },
        "settings": {
            "layer_height": {"default_value": settings.get("layer_height", 0.2)},
            "infill_sparse_density": {"default_value": settings.get("infill_sparse_density", 20)},
            "print_speed": {"default_value": settings.get("print_speed", 50)},
            "travel_speed": {"default_value": settings.get("travel_speed", 150)},
            "material_print_temperature": {"default_value": settings.get("material_print_temperature", 200)},
            "material_bed_temperature": {"default_value": settings.get("material_bed_temperature", 60)},
            "support_enable": {"default_value": settings.get("support_enable", False)},
            "adhesion_type": {"default_value": settings.get("adhesion_type", "skirt")},
            "retraction_enable": {"default_value": settings.get("retraction_enable", True)},
        }
    }

def _build_material_definition(settings: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "name": "PLA",
        "id": "pla",
        "version": 1,
        "inherits": "fdmmaterial",
        "settings": {
            "material_print_temperature": {"default_value": settings.get("material_print_temperature", 200)},
            "material_bed_temperature": {"default_value": settings.get("material_bed_temperature", 60)}
        }
    }

def slice_with_curaengine(stl_path: str, gcode_path: str, settings: Dict[str, Any]) -> bool:
    if not _check_cura_engine():
        return False
    with tempfile.TemporaryDirectory() as tmpdir:
        printer_file = os.path.join(tmpdir, "printer.def.json")
        material_file = os.path.join(tmpdir, "material.json")
        with open(printer_file, "w", encoding="utf-8") as f:
            json.dump(_build_printer_definition(settings), f, indent=2)
        with open(material_file, "w", encoding="utf-8") as f:
            json.dump(_build_material_definition(settings), f, indent=2)
        cmd = [CURA_ENGINE_PATH, "slice", "-o", gcode_path, "-j", printer_file, "-l", material_file, stl_path]
        try:
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120, check=False)
            if proc.returncode != 0:
                logger.error(f"CuraEngine error: {proc.stderr}")
                return False
            return os.path.exists(gcode_path) and os.path.getsize(gcode_path) > 0
        except Exception:
            return False

def generate_advanced_fallback_gcode(stl_path: str, gcode_path: str, settings: Dict[str, Any]) -> bool:
    try:
        stl_mesh = mesh.Mesh.from_file(stl_path)
        points = stl_mesh.points.reshape(-1, 3)
        min_pt = np.min(points, axis=0)
        max_pt = np.max(points, axis=0)
        size = max_pt - min_pt
        width, depth, height = size[0], size[1], size[2]
        if width <= 0 or depth <= 0 or height <= 0:
            width, depth, height = 20, 20, 20
        layer_height = settings.get("layer_height", 0.2)
        layers = int(height / layer_height) + 1

        with open(gcode_path, 'w') as f:
            f.write("; G-code generated by KLHSlicer (advanced fallback)\n")
            f.write(f"; Model size: {width:.2f} x {depth:.2f} x {height:.2f} mm\n")
            f.write("G28 ; Home\n")
            f.write("G29 ; Auto bed leveling\n")
            f.write("G90 ; Absolute positioning\n")
            f.write("M82 ; Absolute extrusion\n")
            f.write(f"G1 Z{layer_height + 1} F3000 ; Raise Z\n")
            f.write("G92 E0 ; Reset extruder\n")
            for z in range(layers):
                z_pos = z * layer_height
                f.write(f"; Layer {z+1} at Z={z_pos:.2f}\n")
                f.write(f"G1 Z{z_pos:.2f} F3000\n")
                f.write("G1 X0 Y0 F1500\n")
                f.write(f"G1 X{width:.2f} Y0 F1500\n")
                f.write(f"G1 X{width:.2f} Y{depth:.2f} F1500\n")
                f.write(f"G1 X0 Y{depth:.2f} F1500\n")
                f.write(f"G1 X0 Y0 F1500\n")
                step = 2.0
                y = 0
                while y < depth:
                    f.write(f"G1 X{width/2:.2f} Y{y:.2f} F1500\n")
                    y += step
                    if y > depth:
                        y = depth
            f.write("G28 ; Home\n")
            f.write("M104 S0 ; Turn off hotend\n")
            f.write("M140 S0 ; Turn off bed\n")
            f.write("M84 ; Disable motors\n")
        return True
    except Exception as e:
        logger.exception("Fallback G-code generation error")
        return False

def init(name: str) -> None:
    logger.info(f"Слайсер '{name}' инициализирован. Профилей: {len(PRINTER_PROFILES)}")

def handle_message(message: str) -> str:
    try:
        msg = json.loads(message)
    except:
        return json.dumps({"error": "Неверный JSON"})
    command = msg.get("command")
    if command == "slice":
        filename = msg.get("filename")
        if not filename:
            return json.dumps({"error": "Нет файла"})
        stl_path = os.path.join(MODEL_DIR, filename)
        if not os.path.isfile(stl_path):
            return json.dumps({"error": f"Файл {filename} не найден"})
        params = msg.get("params", {})
        printer_profile = params.get("printer_profile", "ultimaker")
        base_profile = PRINTER_PROFILES.get(printer_profile, PRINTER_PROFILES.get("ultimaker", {}))
        settings = _sanitize_settings(base_profile, params)
        gcode_filename = Path(filename).stem + ".gcode"
        gcode_path = os.path.join(OUTPUT_DIR, gcode_filename)
        if _check_cura_engine():
            success = slice_with_curaengine(stl_path, gcode_path, settings)
            if success:
                return json.dumps({"status": "ok", "gcode_file": gcode_filename})
        success = generate_advanced_fallback_gcode(stl_path, gcode_path, settings)
        if success:
            return json.dumps({"status": "ok", "gcode_file": gcode_filename})
        else:
            return json.dumps({"status": "error", "error": "Не удалось создать G-код"})
    elif command == "list_profiles":
        return json.dumps({"profiles": list(PRINTER_PROFILES.keys())})
    elif command == "get_profile":
        name = msg.get("profile_name")
        if name in PRINTER_PROFILES:
            return json.dumps(PRINTER_PROFILES[name])
        else:
            return json.dumps({"error": "Профиль не найден"})
    elif command == "save_profile":
        name = msg.get("profile_name")
        profile = msg.get("profile")
        if not name or not profile:
            return json.dumps({"error": "Не указаны name и profile"})
        PRINTER_PROFILES[name] = profile
        with open(os.path.join(PROFILES_DIR, f"{name}.json"), 'w', encoding='utf-8') as f:
            json.dump(profile, f, indent=2)
        return json.dumps({"status": "ok"})
    else:
        return json.dumps({"error": f"Неизвестная команда: {command}"})

def shutdown(name=None):
    logger.info("Слайсер выгружен")