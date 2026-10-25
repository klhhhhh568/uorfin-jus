# skills/picogk_worker.py
# -*- coding: utf-8 -*-
"""
Изолированный worker для генерации PicoGK.
Запускается как subprocess. Принимает JSON через stdin,
сохраняет STL по пути из argv[1], возвращает результат в stdout.
"""
import sys
import os

# Автоопределение пути для импорта skills.*
# В PyInstaller все .py файлы лежат в _MEIPASS, а не рядом с worker'ом
if getattr(sys, 'frozen', False):
    _meipass = sys._MEIPASS
    if _meipass not in sys.path:
        sys.path.insert(0, _meipass)
    # Также добавляем папку skills на уровень выше
    _skills_parent = os.path.dirname(_meipass)  # обычно это /tmp
    # _MEIPASS = /tmp/_MEIxxxx/, skills лежат в /tmp/_MEIxxxx/skills/
    # значит для импорта "skills.picogk_binding" нужен /tmp/_MEIxxxx в sys.path
else:
    # Dev-режим
    _worker_dir = os.path.dirname(os.path.abspath(__file__))
    _project_root = os.path.dirname(_worker_dir)
    if _project_root not in sys.path:
        sys.path.insert(0, _project_root)

import json
import base64
import traceback
import resource

# Лимит памяти: 16 ГБ (безопасный на 27 ГБ RAM)
# PyInstaller-frozen worker требует много RAM на распаковку + PicoGK
try:
    soft, hard = resource.getrlimit(resource.RLIMIT_AS)
    # Если hard-лимит не ограничен — ставим 16 ГБ, иначе не трогаем
    if hard == resource.RLIM_INFINITY:
        limit = 16 * 1024 * 1024 * 1024  # 16 ГБ
        resource.setrlimit(resource.RLIMIT_AS, (limit, hard))
except Exception:
    pass

# Проверка: не запускаемся ли мы как run_backend?
# (защита от случайного рекурсивного вызова)


def main(argv=None):
    """
    Точка входа для вызова из web_server.py в режиме --picogk-worker.
    argv: список аргументов после флага.
    """
    if argv is None:
        argv = sys.argv[1:]

    if len(argv) < 1:
        print(json.dumps({"success": False, "error": "Нет выходного пути STL"}))
        return 1

    stl_path = argv[0]
    voxel_size = float(argv[1]) if len(argv) > 1 else 0.4

    try:
        # Всё то же, что и в основном блоке
        raw_input_data = sys.stdin.read()
        payload = json.loads(raw_input_data)
        code_body = payload.get("code", "")

        # Защита: если LLM всё-таки вставил def build(pg): — срезаем.
        # Иначе получим вложенную функцию и внешняя build() вернёт None.
        import re as _re
        m = _re.match(r'\s*def\s+build\s*\(\s*pg\s*\)\s*:\s*\n?(.*)$',
                      code_body, _re.DOTALL)
        if m:
            code_body = m.group(1)
            _lines = code_body.split("\n")
            _non_empty = [l for l in _lines if l.strip()]
            if _non_empty:
                _min = min(len(l) - len(l.lstrip()) for l in _non_empty)
                if _min > 0:
                    _lines = [l[_min:] if len(l) >= _min else l for l in _lines]
            code_body = "\n".join(_lines).strip()
            print("[WORKER] stripped leading 'def build(pg):'", file=sys.stderr)

        if not code_body:
            print(json.dumps({"success": False, "error": "Пустой код"}))
            return 1

        from skills.picogk_binding import get_picogk
        pg = get_picogk(voxel_size_mm=voxel_size)

        # Собираем функцию
        code = "def build(pg):\n"
        for line in code_body.split("\n"):
            code += "    " + line + "\n"

        allowed = {
            "abs": abs, "min": min, "max": max, "round": round,
            "len": len, "range": range, "enumerate": enumerate, "zip": zip,
            "float": float, "int": int, "str": str, "list": list,
            "dict": dict, "tuple": tuple, "set": set, "bool": bool,
            "sum": sum, "pow": pow, "sorted": sorted, "map": map,
            "filter": filter, "any": any, "all": all, "isinstance": isinstance,
            "True": True, "False": False, "None": None,
        }
        print(f"[WORKER] final code:\n{code}", file=sys.stderr)
        namespace = {"__builtins__": allowed}
        exec(code, namespace)
        build = namespace["build"]

        voxels = build(pg)
        if not voxels:
            print(json.dumps({"success": False, "error": "build() вернул None"}))
            return 1

        if not pg.is_valid(voxels):
            print(json.dumps({"success": False, "error": "Voxels невалиден"}))
            return 1

        vol = pg.volume(voxels)
        if vol <= 0:
            print(json.dumps({"success": False, "error": f"Нулевой объём ({vol})"}))
            return 1

        # bbox
        try:
            mesh = pg.to_mesh(voxels)
            bb = pg.bounding_box(mesh)
            bbox_mm = [
                bb.vecMax.x - bb.vecMin.x,
                bb.vecMax.y - bb.vecMin.y,
                bb.vecMax.z - bb.vecMin.z,
            ]
            max_dim = max(bbox_mm)
            if max_dim > 500:
                print(json.dumps({
                    "success": False,
                    "error": f"Модель слишком большая ({max_dim:.0f} мм). Максимум 500 мм."
                }))
                return 1
        except Exception as e:
            bbox_mm = [0, 0, 0]
            mesh = None

        pg.save_stl(voxels, stl_path)

        size_bytes = os.path.getsize(stl_path)

        if mesh is None:
            try:
                mesh = pg.to_mesh(voxels)
            except Exception:
                pass
        n_tris = pg.triangle_count(mesh) if mesh else 0

        result = {
            "success": True,
            "stl_path": stl_path,
            "volume_mm3": vol,
            "bbox_mm": bbox_mm,
            "triangle_count": n_tris,
            "file_size_bytes": size_bytes,
            "voxel_size_mm": voxel_size,
        }
        print(json.dumps(result))
        pg.cleanup()
        return 0

    except MemoryError:
        print(json.dumps({
            "success": False,
            "error": "Недостаточно памяти: модель слишком детальная или большая"
        }))
        return 2
    except Exception as e:
        tb = traceback.format_exc()
        print(json.dumps({
            "success": False,
            "error": f"{type(e).__name__}: {str(e)[:200]}",
            "traceback": tb[-1000:],
        }))
        return 3


if __name__ == "__main__":
    sys.exit(main())