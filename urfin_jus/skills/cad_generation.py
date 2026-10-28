# skills/cad_generation.py
# -*- coding: utf-8 -*-
"""
CAD-генерация через PicoGK (воксельный движок).
LLM пишет функцию build(pg) — pipeline выполняет её в sandbox.
"""
import io
import os
import re
import json
import base64
import logging
import tempfile
import traceback
from pathlib import Path
from typing import Dict, Any, Optional, List, Callable

logger = logging.getLogger(__name__)

# Разрешённые модели
CAD_MODEL_DEFAULT = "qwen2.5-coder:7b"

# Жёсткие лимиты (защита от взрыва памяти)
MAX_VOXEL_SIZE_MM = 5.0
MIN_VOXEL_SIZE_MM = 0.15
MAX_BBOX_MM = 2000.0
MAX_STL_SIZE_MB = 50.0


# ============================================================
# SYSTEM PROMPT — учим LLM писать код для нашего binding
# ============================================================
BUILD_SYSTEM_PROMPT = """Ты — инженер-программист PicoGK. Пишешь функцию `build(pg)`, которая создаёт 3D-деталь и возвращает воксельный объект.

ФОРМАТ ОТВЕТА (только код, без markdown, без ```):
def build(pg):
    # ... код ...
    return voxels_handle

ДОСТУПНЫЙ API (объект `pg`):

=== Примитивы (возвращают voxels) ===
pg.sphere(center=(x,y,z), radius=r)              # r > 0 !!!
pg.capsule(start=(x,y,z), stop=(x,y,z), r1=r_start, r2=r_stop)  # r1, r2 > 0 !!!

=== Копирование ===
pg.copy(voxels)

=== Булевы (НЕ мутируют, возвращают НОВЫЙ voxels) ===
pg.add(a, b)          # объединение
pg.subtract(a, b)     # вычитание a - b
pg.intersect(a, b)    # пересечение

=== Офсет (утолщение/утоньшение стенки) ===
pg.offset(voxels, distance)   # distance > 0 = утолстить, distance < 0 = утоньшить

=== Решётки (латтис) ===
lat = pg.lattice_create()
pg.lattice_add_sphere(lat, center=(x,y,z), radius=r)   # r > 0
pg.lattice_add_beam(lat, p1=(x,y,z), p2=(x,y,z), r1=..., r2=...)  # r1, r2 > 0
voxels = pg.render_lattice(lat)

=== Импилицит (SDF-функции) — для цилиндров, конусов, шестерён ===
voxels = pg.render_implicit(
    lambda x, y, z: <расстояние со знаком>,
    bbox_min=(x0, y0, z0),
    bbox_max=(x1, y1, z1),
)

=== Утилиты ===
pg.volume(voxels)         # объём в мм³

КРИТИЧЕСКИЕ ПРАВИЛА:
1. Всё в миллиметрах.
2. ВСЕ РАДИУСЫ И РАЗМЕРЫ СТРОГО > 0. Отрицательный радиус у pg.sphere
   или pg.capsule вернёт None, и вся деталь развалится.
3. НЕ выдумывай методов, которых нет в списке API. Если нужен цилиндр —
   делай его через render_implicit, а не через несуществующий pg.cylinder.
4. Если задача сложная — УПРОЩАЙ. Лучше простая корректная деталь, чем
   набор из 20 галлюцинированных вызовов.
5. НЕ вызывай pg.save_stl, pg.cleanup — это сделает pipeline.
6. НЕ импортируй ничего — только `pg` доступен.
7. НЕ пиши def build — она уже дана. Только тело функции с return в конце.
8. Без комментариев в коде, если не критично.

ПРИМЕРЫ:

Запрос: "сфера радиусом 10"
def build(pg):
    return pg.sphere((0, 0, 0), 10.0)

Запрос: "полая сфера, внешний радиус 15, толщина стенки 2"
def build(pg):
    outer = pg.sphere((0, 0, 0), 15.0)
    inner = pg.sphere((0, 0, 0), 13.0)
    return pg.subtract(outer, inner)

Запрос: "сфера на ножке (шар радиус 10 вверху, стойка 30 мм высоты)"
def build(pg):
    ball = pg.sphere((0, 0, 40), 10.0)
    leg = pg.capsule((0, 0, 0), (0, 0, 30), 4.0, 4.0)
    return pg.add(ball, leg)

Запрос: "цилиндр радиусом 10, высотой 30"
def build(pg):
    r, h = 10.0, 30.0
    return pg.render_implicit(
        lambda x, y, z: max((x*x + y*y)**0.5 - r, abs(z) - h/2),
        (-r-1, -r-1, -h/2-1),
        (r+1, r+1, h/2+1),
    )

Запрос: "труба: внешний радиус 15, внутренний 12, высота 30"
def build(pg):
    r_out, r_in, h = 15.0, 12.0, 30.0
    outer = pg.render_implicit(
        lambda x, y, z: max((x*x + y*y)**0.5 - r_out, abs(z) - h/2),
        (-r_out-1, -r_out-1, -h/2-1),
        (r_out+1, r_out+1, h/2+1),
    )
    inner = pg.render_implicit(
        lambda x, y, z: max((x*x + y*y)**0.5 - r_in, abs(z) - h/2 - 1),
        (-r_in-1, -r_in-1, -h/2-2),
        (r_in+1, r_in+1, h/2+2),
    )
    return pg.subtract(outer, inner)

Запрос: "куб 40x40x40 с полостью внутри (стенка 3 мм)"
def build(pg):
    outer = pg.render_implicit(
        lambda x, y, z: max(abs(x)-20, abs(y)-20, abs(z)-20),
        (-21, -21, -21), (21, 21, 21),
    )
    inner = pg.render_implicit(
        lambda x, y, z: max(abs(x)-17, abs(y)-17, abs(z)-17),
        (-18, -18, -18), (18, 18, 18),
    )
    return pg.subtract(outer, inner)

Запрос: "диск радиусом 20, толщиной 5, с центральным отверстием радиусом 5"
def build(pg):
    r_out, r_hole, h = 20.0, 5.0, 5.0
    disc = pg.render_implicit(
        lambda x, y, z: max((x*x + y*y)**0.5 - r_out, abs(z) - h/2),
        (-r_out-1, -r_out-1, -h/2-1),
        (r_out+1, r_out+1, h/2+1),
    )
    hole = pg.render_implicit(
        lambda x, y, z: max((x*x + y*y)**0.5 - r_hole, abs(z) - h/2 - 1),
        (-r_hole-1, -r_hole-1, -h/2-2),
        (r_hole+1, r_hole+1, h/2+2),
    )
    return pg.subtract(disc, hole)

Запрос: "электродвигатель: статор-труба, ротор-цилиндр внутри"
def build(pg):
    h = 30.0
    r_stator_out = 25.0
    r_stator_in = 20.0
    r_rotor = 17.0
    stator = pg.render_implicit(
        lambda x, y, z: max((x*x + y*y)**0.5 - r_stator_out, abs(z) - h/2),
        (-r_stator_out-1, -r_stator_out-1, -h/2-1),
        (r_stator_out+1, r_stator_out+1, h/2+1),
    )
    stator_hole = pg.render_implicit(
        lambda x, y, z: max((x*x + y*y)**0.5 - r_stator_in, abs(z) - h/2 - 1),
        (-r_stator_in-1, -r_stator_in-1, -h/2-2),
        (r_stator_in+1, r_stator_in+1, h/2+2),
    )
    stator = pg.subtract(stator, stator_hole)
    rotor = pg.render_implicit(
        lambda x, y, z: max((x*x + y*y)**0.5 - r_rotor, abs(z) - (h/2 - 1)),
        (-r_rotor-1, -r_rotor-1, -h/2),
        (r_rotor+1, r_rotor+1, h/2),
    )
    return pg.add(stator, rotor)
"""


# ============================================================
# SANDBOX — изолирует выполнение кода от системы
# ============================================================
ALLOWED_BUILTINS = {
    "abs": abs, "min": min, "max": max, "round": round,
    "len": len, "range": range, "enumerate": enumerate, "zip": zip,
    "float": float, "int": int, "str": str, "list": list,
    "dict": dict, "tuple": tuple, "set": set, "bool": bool,
    "sum": sum, "pow": pow, "sorted": sorted, "map": map,
    "filter": filter, "any": any, "all": all, "isinstance": isinstance,
    "True": True, "False": False, "None": None,
}


# ============================================================
# ОСНОВНОЙ КЛАСС
# ============================================================
class CADGenerator:
    MAX_RETRIES = 3

    def __init__(self, dual_skill, engine_cad=None):
        self.dual = dual_skill
        self._current_triz_hint = ""   # TRIZ-хинт для system_prompt CAD-LLM
        self.engine_cad = engine_cad
        self.cad_model = CAD_MODEL_DEFAULT

        # Проверяем binding
        try:
            from skills.picogk_binding import _load_library, get_picogk
            lib = _load_library()
            if lib is None:
                logger.error("❌ PicoGK не загрузился")
            else:
                logger.info("✅ PicoGK binding готов")
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки binding: {e}")

    # ==================== ПОИСК РЕАЛЬНОГО PYTHON ====================
    @staticmethod
    def _find_real_python() -> Optional[str]:
        """
        Ищет настоящий Python (не sys.executable, который в PyInstaller = run_backend).
        Приоритет: env URFIN_CAD_PYTHON → известные пути → venv.
        """
        import shutil

        # 1. Env переменная
        env_py = os.environ.get("URFIN_CAD_PYTHON")
        if env_py and os.path.exists(env_py) and os.access(env_py, os.X_OK):
            logger.info(f"[PicoGK] Python из URFIN_CAD_PYTHON: {env_py}")
            return env_py

        # 2. Стандартные пути
        candidates = [
            "/home/klhhhhh/urfin-jus/urfin_env/bin/python3",
            "/home/klhhhhh/urfin-jus/urfin_env/bin/python",
            str(Path.home() / "urfin-jus" / "urfin_env" / "bin" / "python3"),
            str(Path.home() / "urfin-jus" / "urfin_env" / "bin" / "python"),
            "/usr/bin/python3",
            "/usr/local/bin/python3",
        ]
        for p in candidates:
            if os.path.exists(p) and os.access(p, os.X_OK):
                logger.info(f"[PicoGK] Python найден: {p}")
                return p

        # 3. Через shutil.which
        for name in ["python3", "python"]:
            p = shutil.which(name)
            if p:
                logger.info(f"[PicoGK] Python через which: {p}")
                return p

        return None

    # ==================== ГЛАВНЫЙ МЕТОД ====================
    def generate(self, prompt: str, num_variants: int = 1) -> Dict[str, Any]:
        result = {
            "prompt": prompt,
            "variants": [],
            "best_index": 0,
            "analysis": {"backend": "picogk"},
            "triz": {"suggestions": [], "contradictions": []},
            "logs": [],
            "error": None,
        }

        # === TRIZ-анализ (до CAD-генерации, чтобы хинт попал в system_prompt) ===
        triz_result = self._triz_analyze(prompt)
        result["triz"] = triz_result
        self._current_triz_hint = (
            triz_result.get("picogk_hint", "")
            if self._should_apply_triz(prompt, triz_result)
            else ""
        )
        try:
            if self._current_triz_hint:
                logger.info(
                    f"[TRIZ] хинт применён ({len(triz_result.get('principles', []))} принципов, "
                    f"источник={triz_result.get('source')})"
                )
            else:
                logger.debug("[TRIZ] хинт не применён (простой запрос без противоречия)")
        except Exception:
            pass

        # === LLM генерирует тело build() ===
        body, code, logs = self._generate_code_with_retry(prompt)
        result["logs"] = logs
        result["analysis"]["generated_code"] = code or ""

        if body is None:
            result["error"] = f"LLM не смог сгенерировать код после {self.MAX_RETRIES} попыток"
            return result

        # === Выполняем через subprocess ===
        data, err = self._execute_build(body)
        if data is None:
            result["error"] = err
            return result

        # === Читаем STL, готовим вариант ===
        variant, export_err = self._export_variant_from_result(data, prompt, body)
        if variant is None:
            result["error"] = f"Ошибка экспорта: {export_err}"
            return result

        result["variants"] = [variant]
        # result["triz"] уже установлен в начале generate()

        try:
            self._feed_brain(prompt, body)
        except Exception:
            pass

        return result

    # ==================== ГЕНЕРАЦИЯ КОДА ====================
    def _generate_code_with_retry(self, prompt: str):
        logs = []
        last_error = None
        last_body = None

        for attempt in range(1, self.MAX_RETRIES + 1):
            logger.info(f"[PicoGK] Попытка {attempt}/{self.MAX_RETRIES}")

            if attempt == 1:
                user_msg = f"Запрос: {prompt}\n\nНапиши ТОЛЬКО тело функции build(pg):"
            else:
                user_msg = (
                    f"Запрос: {prompt}\n\n"
                    f"Предыдущий код (упал):\n{last_body[:800]}\n\n"
                    f"Ошибка: {last_error}\n\n"
                    f"Напиши ИСПРАВЛЕННОЕ тело функции build(pg). Только код, без def."
                )

            # Подмешиваем TRIZ-хинт в system_prompt (если установлен выше)
            triz_hint = getattr(self, "_current_triz_hint", "")
            effective_system = BUILD_SYSTEM_PROMPT
            if triz_hint:
                effective_system = BUILD_SYSTEM_PROMPT + "\n\n" + triz_hint

            raw = self.dual._call_ollama(
                self.cad_model, user_msg, effective_system,
                temperature=0.1 + 0.1 * (attempt - 1),
            )
            if not raw:
                last_error = "Пустой ответ"
                continue

            body = self._extract_body(raw)
            if not body or "return" not in body:
                last_error = "Нет return в ответе"
                last_body = body
                logs.append({"role": f"attempt_{attempt}", "text": body or "(пусто)"})
                continue

            logs.append({"role": f"attempt_{attempt}", "text": body})

            # Проверка на опасный код
            if self._is_forbidden(body):
                last_error = "Запрещённая конструкция (import/os/eval)"
                last_body = body
                continue

            # Статическая проверка геометрии (отрицательные радиусы и т.п.)
            geom_err = self._validate_geometry(body)
            if geom_err:
                last_error = f"Геометрическая ошибка: {geom_err}"
                last_body = body
                logs.append({"role": f"geom_error_{attempt}", "text": geom_err})
                continue

            # Проверяем синтаксис
            try:
                full = f"def build(pg):\n"
                for line in body.split("\n"):
                    full += "    " + line + "\n"
                compile(full, "<build>", "exec")
            except SyntaxError as e:
                last_error = f"SyntaxError: {e}"
                last_body = body
                logs.append({"role": f"syntax_error_{attempt}", "text": str(e)})
                continue

            return body, f"def build(pg):\n" + "\n".join("    " + l for l in body.split("\n")), logs

        return None, None, logs

    @staticmethod
    def _extract_body(raw: str) -> str:
        if not raw:
            return ""
        # Убираем reasoning
        raw = re.sub(r'<think(?:ing)?>.*?</think(?:ing)?>', '', raw, flags=re.DOTALL | re.IGNORECASE)
        # Убираем markdown
        raw = re.sub(r'^\s*```(?:python|py)?\s*\n?', '', raw, flags=re.MULTILINE)
        raw = re.sub(r'\n?```\s*$', '', raw)
        raw = raw.replace('```python', '').replace('```py', '').replace('```', '')
        raw = raw.strip()

        # Если LLM всё-таки написал def build(pg): — вырезаем его.
        # re.match не требует trailing newline в отличие от прежнего search.
        m = re.match(r'\s*def\s+build\s*\(\s*pg\s*\)\s*:\s*\n?(.*)$', raw, re.DOTALL)
        if m:
            body = m.group(1)
        else:
            body = raw

        # Убираем общий отступ
        lines = body.split("\n")
        non_empty = [l for l in lines if l.strip()]
        if non_empty:
            min_indent = min(len(l) - len(l.lstrip()) for l in non_empty)
            if min_indent > 0:
                lines = [l[min_indent:] if len(l) >= min_indent else l for l in lines]
        return "\n".join(lines).strip()

    @staticmethod
    def _is_forbidden(code: str) -> bool:
        forbidden = [
            "import ", "__import__", "open(", "exec(", "eval(", "compile(",
            "os.", "sys.", "subprocess", "shutil", "pathlib",
            "__builtins__", "__globals__", "globals()", "locals()",
        ]
        for bad in forbidden:
            if bad in code:
                return True
        return False

    @staticmethod
    def _validate_geometry(body: str):
        """
        Статическая проверка тела build() до запуска worker.
        Возвращает текст ошибки или None.
        Ловит: неположительные радиусы у примитивов (sphere/capsule/lattice).
        """
        import ast
        full = "def build(pg):\n" + "\n".join("    " + l for l in body.split("\n"))
        try:
            tree = ast.parse(full)
        except SyntaxError:
            return None  # ниже поймает compile()

        def _const_val(node):
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                return float(node.value)
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
                if isinstance(node.operand, ast.Constant) and isinstance(node.operand.value, (int, float)):
                    return -float(node.operand.value)
            return None

        def _arg_value(args, kw, name, pos_idx):
            if name in kw:
                return kw[name]
            if len(args) > pos_idx:
                return args[pos_idx]
            return None

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if not (isinstance(fn, ast.Attribute)
                    and isinstance(fn.value, ast.Name)
                    and fn.value.id == "pg"):
                continue
            method = fn.attr
            args = node.args
            kw = {k.arg: k.value for k in node.keywords if k.arg}

            if method == "sphere":
                r = _arg_value(args, kw, "radius", 1)
                v = _const_val(r) if r is not None else None
                if v is not None and v <= 0:
                    return f"pg.sphere: radius={v} <= 0 (недопустимо)"

            elif method == "capsule":
                for key, idx in (("r1", 3), ("r2", 4)):
                    r = _arg_value(args, kw, key, idx)
                    v = _const_val(r) if r is not None else None
                    if v is not None and v <= 0:
                        return f"pg.capsule: {key}={v} <= 0 (недопустимо)"

            elif method == "lattice_add_sphere":
                r = _arg_value(args, kw, "radius", 2)
                v = _const_val(r) if r is not None else None
                if v is not None and v <= 0:
                    return f"pg.lattice_add_sphere: radius={v} <= 0"

            elif method == "lattice_add_beam":
                for key, idx in (("r1", 3), ("r2", 4)):
                    r = _arg_value(args, kw, key, idx)
                    v = _const_val(r) if r is not None else None
                    if v is not None and v <= 0:
                        return f"pg.lattice_add_beam: {key}={v} <= 0"

        return None

    # ==================== ВЫПОЛНЕНИЕ ====================
    def _execute_build(self, body: str):
        """
        Выполняет build(pg) через ИЗОЛИРОВАННЫЙ subprocess.
        Защищает основной бэкенд от падений PicoGK (segfault).
        """
        import subprocess
        import sys
        import tempfile

        try:
            # Путь к worker — ищем правильно и в PyInstaller, и в dev-режиме
            if getattr(sys, 'frozen', False):
                # Собранный PyInstaller
                base = sys._MEIPASS
            else:
                # Dev-режим
                base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            worker_path = os.path.join(base, "skills", "picogk_worker.py")

            # Fallback для нестандартных случаев
            if not os.path.exists(worker_path):
                worker_path = os.path.join(
                    os.path.dirname(os.path.abspath(__file__)),
                    "picogk_worker.py"
                )

            if not os.path.exists(worker_path):
                return None, f"picogk_worker.py не найден. Искали в: {base}/skills/"

            # Создаём временный файл для STL
            tmp = tempfile.NamedTemporaryFile(suffix=".stl", delete=False)
            stl_path = tmp.name
            tmp.close()

            # Логируем код перед запуском — для отладки segfault'ов
            logger.info(f"[PicoGK] === Сгенерированный код ===\n{body}\n=== Конец кода ===")

            # Формируем payload
            payload = json.dumps({"code": body})

            # В PyInstaller запускаем САМ БИНАРНИК с флагом --picogk-worker
            # В dev-режиме — внешний Python + picogk_worker.py
            if getattr(sys, 'frozen', False):
                python_exe = sys.executable
                worker_args = [python_exe, "--picogk-worker", stl_path, "0.4"]
                use_frozen_mode = True
                logger.info(f"[PicoGK] Режим: frozen (worker встроен)")
            else:
                python_exe = self._find_real_python()
                if not python_exe:
                    return None, "Не найден Python для worker. Установи URFIN_CAD_PYTHON env."
                worker_args = [python_exe, worker_path, stl_path, "0.4"]
                use_frozen_mode = False
                logger.info(f"[PicoGK] Режим: dev (python={python_exe})")

            # Корень проекта — чтобы worker нашёл модули
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

            # Передаём PYTHONPATH через env
            env = os.environ.copy()
            env["PYTHONPATH"] = project_root + os.pathsep + env.get("PYTHONPATH", "")

            # Запускаем subprocess с таймаутом 120 секунд
            logger.info(f"[PicoGK subprocess] Запуск worker...")
            proc = subprocess.run(
                worker_args,
                input=payload,
                capture_output=True,
                text=True,
                timeout=120,
                cwd=project_root if not use_frozen_mode else None,
                env=env if not use_frozen_mode else os.environ.copy(),
            )

            # Смотрим stderr (там логи binding) — INFO-уровень
            if proc.stderr:
                for line in proc.stderr.split("\n")[-30:]:
                    if line.strip():
                        logger.info(f"[PicoGK worker] {line.strip()}")

            # Смотрим stdout (включая JSON — иначе теряем причину ошибки)
            if proc.stdout:
                for line in proc.stdout.split("\n")[-5:]:
                    if line.strip():
                        logger.info(f"[PicoGK worker stdout] {line.strip()}")

            # Если упал с segfault — returncode = -11 (SIGSEGV) или -6 (SIGABRT)
            if proc.returncode != 0:
                # Пытаемся извлечь сообщение из stdout
                try:
                    data = json.loads(proc.stdout.strip().split("\n")[-1])
                    err = data.get("error", "неизвестная ошибка")
                except Exception:
                    if proc.returncode == -11:
                        err = "PicoGK упал (segmentation fault). Модель слишком сложная или некорректная."
                    elif proc.returncode == -9:
                        err = "PicoGK убит (OOM). Модель требует слишком много памяти."
                    elif proc.returncode == -6:
                        err = "PicoGK прерван (abort). Невалидные параметры."
                    else:
                        err = f"Worker exit={proc.returncode}"
                # Чистим
                try:
                    os.unlink(stl_path)
                except Exception:
                    pass
                return None, err

            # Парсим результат
            stdout_lines = [l for l in proc.stdout.strip().split("\n") if l.strip().startswith("{")]
            if not stdout_lines:
                try:
                    os.unlink(stl_path)
                except Exception:
                    pass
                return None, "Worker не вернул JSON"

            data = json.loads(stdout_lines[-1])
            if not data.get("success"):
                try:
                    os.unlink(stl_path)
                except Exception:
                    pass
                return None, data.get("error", "Worker failed")

            # Успех
            logger.info(
                f"[PicoGK subprocess] ✅ Объём: {data['volume_mm3']:.2f} мм³, "
                f"bbox: {data['bbox_mm']}, {data['triangle_count']} тр."
            )

            # Возвращаем метаданные + путь к STL
            # ВАЖНО: возвращаем словарь, а не handle
            return data, None

        except subprocess.TimeoutExpired:
            try:
                os.unlink(stl_path)
            except Exception:
                pass
            return None, "Таймаут генерации (>120 сек)"
        except Exception as e:
            logger.exception("_execute_build subprocess")
            try:
                os.unlink(stl_path)
            except Exception:
                pass
            return None, f"{type(e).__name__}: {str(e)[:200]}"

    # ==================== ЭКСПОРТ ====================
    def _export_variant_from_result(self, data: Dict, prompt: str, body: str):
        """Готовит вариант для UI из данных, возвращённых worker'ом."""
        try:
            stl_path = data.get("stl_path")
            if not stl_path or not os.path.exists(stl_path):
                return None, "STL не найден"

            with open(stl_path, "rb") as f:
                stl_bytes = f.read()

            try:
                os.unlink(stl_path)
            except Exception:
                pass

            stl_b64 = base64.b64encode(stl_bytes).decode("utf-8")
            size_mb = len(stl_bytes) / 1024 / 1024

            # Предпросмотр через trimesh
            vertices = []
            faces = []
            try:
                import trimesh
                m = trimesh.load(io.BytesIO(stl_bytes), file_type='stl')
                # Ограничение по количеству треугольников для UI
                if len(m.faces) > 200000:
                    try:
                        m = m.simplify_quadric_decimation(200000)
                    except Exception as e:
                        logger.warning(f"simplify недоступен ({e}), используем как есть")
                vertices = m.vertices.tolist()
                faces = m.faces.tolist()
            except Exception as e:
                logger.warning(f"trimesh preview: {e}")

            bbox_mm = data.get("bbox_mm", [0, 0, 0])

            variant = {
                "shape_type": "picogk",
                "params": {},
                "description": f"PicoGK ({size_mb:.1f} МБ, {data.get('triangle_count', 0)} тр.)",
                "code": f"def build(pg):\n" + "\n".join("    " + l for l in body.split("\n")),
                "stl_base64": stl_b64,
                "vertices": vertices,
                "faces": faces,
                "bbox": {
                    "min": [-bbox_mm[0]/2, -bbox_mm[1]/2, -bbox_mm[2]/2],
                    "max": [bbox_mm[0]/2, bbox_mm[1]/2, bbox_mm[2]/2],
                },
                "metrics": {
                    "is_watertight": True,
                    "volume_mm3": data.get("volume_mm3", 0),
                    "bounding_box_mm": bbox_mm,
                    "triangle_count": data.get("triangle_count", 0),
                    "file_size_mb": size_mb,
                },
                "source": "picogk_subprocess",
                "error": None,
            }
            return variant, None

        except Exception as e:
            logger.exception("_export_variant_from_result")
            return None, str(e)

    # ==================== TRIZ ====================
    def _triz_analyze(self, prompt: str) -> Dict[str, Any]:
        """Полный TRIZ-анализ: матрица 39×39 + PicoGK-маппинг.

        Возвращает структуру:
          - improve_param / worsen_param: параметры противоречия
          - principles: список принципов с ops и hint
          - picogk_hint: текст для system_prompt CAD-LLM
          - suggestions / contradictions: обратная совместимость с UI
        """
        try:
            from .triz_skill import analyze as _triz_analyze_full
            return _triz_analyze_full(prompt, llm_call=None)
        except Exception as e:
            logger.warning(f"[TRIZ] анализ упал: {e}")
            return {
                "improve_param": {}, "worsen_param": {},
                "principles": [], "picogk_hint": "",
                "suggestions": [], "contradictions": [],
                "source": "error", "confidence": 0.0,
            }

    @staticmethod
    def _should_apply_triz(prompt: str, triz: Dict[str, Any]) -> bool:
        """Решает, добавлять ли TRIZ-хинт в system_prompt CAD-LLM.

        Не добавляем, если:
          - нет принципов
          - в промпте нет признаков противоречия (простой запрос типа «сфера R=10»)
        """
        if not triz.get("principles"):
            return False
        p = prompt.lower()
        markers = [
            " но ", " однако ", " при этом ", " одновременно ",
            "лёгк", "легк", "прочн", "точн", "дешёв", "дешев",
            "быстр", "надёжн", "надежн", "оптимальн", "облегч",
            "усилить", "повысить", "уменьшить", "вибраци", "нагруз",
        ]
        return any(m in p for m in markers)

    # ==================== МОЗГ ====================
    def _feed_brain(self, prompt: str, code: str):
        try:
            engine = self.dual.engine
            engine.grow_from_text('left', prompt, process_type='cad', domain='cad')
            keywords = re.findall(r'pg\.(\w+)', code)
            for kw in set(keywords):
                engine.activate_by_name('left', f"picogk_{kw}", strength=0.5,
                                        create=True, process_type='cad', spread=False)
        except Exception as e:
            logger.error(f"feed_brain: {e}")

    def get_clarification_questions(self, prompt: str) -> List[str]:
        return []