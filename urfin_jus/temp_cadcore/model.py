# CadCore Auto-generated Script
import sys
from pathlib import Path
output_dir = Path(r"/home/klhhhhh/urfin-jus/urfin_jus/temp_cadcore")
output_dir.mkdir(parents=True, exist_ok=True)

from build123d import *
from pathlib import Path

# output_dir configured by CadCore
output_dir.mkdir(parents=True, exist_ok=True)

with BuildPart() as cylinder_part:
    # Create a cylinder with radius 5 and height 20
    Cylinder(radius=5, height=20)

result_part = cylinder_part.part

# Export formats
export_step(result_part, str(output_dir / "model.step"))
export_stl(result_part, str(output_dir / "model.stl"))

# 2D Technical Drawing SVG
visible, hidden = result_part.project_to_viewport((1, 1, 1))
exporter = ExportSVG(scale=2.0)
exporter.add_layer("Visible", fill_color=Color("white"), line_color=Color("black"), line_weight=0.35)
exporter.add_layer("Hidden", fill_color=Color("white"), line_color=Color("gray"), line_weight=0.25, line_type=LineType.DASHED)
exporter.add_shape(visible, layer="Visible")
exporter.add_shape(hidden, layer="Hidden")
exporter.write(str(output_dir / "drawing.svg"))

# CadCore Automatic Export Fallback
try:
    if 'result_part' in locals() and result_part is not None:
        target_solid = result_part
    elif 'part' in locals() and hasattr(part, 'part'):
        target_solid = part.part
    elif 'bracket' in locals() and hasattr(bracket, 'part'):
        target_solid = bracket.part
    elif 'flange' in locals() and hasattr(flange, 'part'):
        target_solid = flange.part
    else:
        # Search for any Compound/Solid in locals
        from build123d import Compound, Solid, Part
        candidates = [v for v in locals().values() if isinstance(v, (Compound, Solid, Part))]
        target_solid = candidates[-1] if candidates else None

    if target_solid is not None:
        step_path = output_dir / "model.step"
        stl_path = output_dir / "model.stl"
        svg_path = output_dir / "drawing.svg"

        if not step_path.exists() or False:
            export_step(target_solid, str(step_path))
        if not stl_path.exists() or False:
            export_stl(target_solid, str(stl_path))
        if not svg_path.exists() or False:
            try:
                visible, hidden = target_solid.project_to_viewport((1, 1, 1))
                exporter = ExportSVG(scale=2.0)
                exporter.add_layer("Visible", fill_color=Color("white"), line_color=Color("black"), line_weight=0.35)
                exporter.add_shape(visible, layer="Visible")
                exporter.write(str(svg_path))
            except Exception as svg_err:
                print(f"[Warning] SVG export failed: {svg_err}")
        print(f"[CadCore] Successfully exported CAD artifacts to {output_dir}")
    else:
        raise RuntimeError("No valid 3D Solid or Compound was created in the script namespace. Ensure you build a solid (e.g. using BuildPart) and assign result_part = ...")
except Exception as export_err:
    raise export_err
