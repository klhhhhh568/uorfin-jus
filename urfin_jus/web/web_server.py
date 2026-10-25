# web/web_server.py
import sys
import os

# ==========================================================================
# PICO GK WORKER MODE — перехватываем ДО всех импортов Flask
# ==========================================================================
if len(sys.argv) > 1 and sys.argv[1] == "--picogk-worker":
    try:
        # Убираем флаг из argv
        _worker_args = sys.argv[2:]
        sys.argv = [sys.argv[0]]

        # Настраиваем путь для импорта skills.*
        if getattr(sys, 'frozen', False):
            # PyInstaller — всё в _MEIPASS
            sys.path.insert(0, sys._MEIPASS)
        else:
            # Dev-режим
            _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            sys.path.insert(0, _root)

        # Импортируем и запускаем worker
        from skills.picogk_worker import main as worker_main
        exit_code = worker_main(_worker_args)
        sys.exit(exit_code)
    except Exception as e:
        import traceback
        print(f"Worker error: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(99)

if getattr(sys, 'frozen', False):
    os.chdir(sys._MEIPASS)

# Добавляем корневую папку проекта в sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)

import json
import threading
import re
import time
import random
import math
import logging
import shutil
import zipfile
import base64
import io
from copy import deepcopy

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

from flask import Flask, render_template, request, jsonify, send_from_directory, send_file
from flask_socketio import SocketIO, emit
from flask_cors import CORS

# ==========================================================================
# OPENKLHCAD — только безопасные модули
# ==========================================================================
# cadquery, geometry_engine, mesh, code_generator ОТКЛЮЧЕНЫ
# Используем PicoGK (воксельное ядро на Linux).
OPENKLHCAD_PARTIAL = False
logger.info("CAD-ядро: PicoGK (воксельное ядро на Linux)")

# ==========================================================================
# ИНИЦИАЛИЗАЦИЯ ОРКЕСТРАТОРА
# ==========================================================================
import skills.orchestrator_skill as orchestrator_skill
orchestrator_skill.init("UrfinJusOrchestrator")
logger.info("Оркестратор инициализирован")

# ==========================================================================
# ОПЦИОНАЛЬНЫЕ НАВЫКИ (могут быть недоступны)
# ==========================================================================

# printer_skill — требует pyserial
try:
    import skills.printer_skill as printer_skill
    PRINTER_SKILL_AVAILABLE = True
    logger.info("✅ printer_skill загружен")
except Exception as e:
    logger.warning(f"⚠️ printer_skill недоступен: {e}")
    printer_skill = None
    PRINTER_SKILL_AVAILABLE = False

# ros2_skill — управление роботами
try:
    import skills.ros2_skill as ros2_skill
    ROS2_SKILL_AVAILABLE = True
    logger.info("✅ ros2_skill загружен")
except Exception as e:
    logger.warning(f"⚠️ ros2_skill недоступен: {e}")
    ros2_skill = None
    ROS2_SKILL_AVAILABLE = False

# cad_generation — новый модуль через PicoGK
try:
    import skills.cad_generation as cad_generation
    cad_generation_AVAILABLE = True
    logger.info("✅ cad_generation загружен")
except Exception as e:
    logger.warning(f"⚠️ cad_generation недоступен: {e}")
    cad_generation = None
    cad_generation_AVAILABLE = False

# cad_skill — устаревший, отключаем полностью
cad_skill = None
logger.info("cad_skill отключён (используем cad_generation + PicoGK)")

# ==========================================================================
# FLASK + SOCKETIO
# ==========================================================================
app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key'
CORS(app)

socketio = SocketIO(app, async_mode='threading', cors_allowed_origins="*")

data_lock = threading.RLock()

# Состояние точек захвата
capture_points = {}
point_counter = 0
MAX_POINTS = 5

UPLOAD_FOLDER = os.path.join(project_root, 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ==========================================================================
# ФОНОВАЯ ПРОВЕРКА ВРАГОВ (для авто-атак в симуляции)
# ==========================================================================
def auto_attack_check():
    while True:
        time.sleep(0.5)
        if ros2_skill is None:
            continue
        try:
            robots_json = ros2_skill.handle_message(json.dumps({"command": "get_all_robots"}))
            robots_data = json.loads(robots_json)
            for robot in robots_data:
                if robot.get('health', 0) <= 0:
                    continue
                team = robot.get('team')
                if not team:
                    continue
                pos = robot.get('position', {})
                for other in robots_data:
                    if other['id'] == robot['id'] or other.get('health', 0) <= 0:
                        continue
                    if other.get('team') == team:
                        continue
                    other_pos = other.get('position', {})
                    dist = math.hypot(pos.get('x', 0) - other_pos.get('x', 0),
                                      pos.get('z', 0) - other_pos.get('z', 0))
                    if dist < 15:
                        logger.info(f"Авто-атака: {robot['id']} стреляет в {other['id']}")
                        socketio.emit('robot_animate', {
                            'robot_id': robot['id'],
                            'action': 'attack',
                            'value': 1,
                            'target': other['id']
                        })
                        damage = random.randint(10, 30)
                        ros2_skill.handle_message(json.dumps({
                            "command": "damage_robot",
                            "robot_id": other['id'],
                            "params": {"damage": damage}
                        }))
                        break
        except Exception as e:
            logger.error(f"Ошибка в auto_attack_check: {e}")
        time.sleep(0.5)

threading.Thread(target=auto_attack_check, daemon=True).start()

# ==========================================================================
# СОЗДАНИЕ ПЕРВОГО ЧАТА
# ==========================================================================
try:
    import skills.memory_skill as memory_skill
    sessions = memory_skill._skill.get_all_sessions()
    if not sessions:
        memory_skill._skill.new_session("Чат 1")
        logger.info("Создан первый чат: Чат 1")
except Exception as e:
    logger.error(f"Ошибка создания первого чата: {e}")

# ==========================================================================
# CAD GENERATOR (ленивая инициализация)
# ==========================================================================
_cad_generator = None

def _get_cad_generator():
    global _cad_generator
    if _cad_generator is None:
        try:
            import skills.dual_hemisphere_cloud as dh
            from skills.cad_generation import CADGenerator
            dual = dh.get_skill()
            if not dual:
                logger.error("CADGenerator: dual_hemisphere_cloud не инициализирован")
                return None
            _cad_generator = CADGenerator(dual)
            logger.info("✅ CADGenerator инициализирован")
        except Exception as e:
            logger.exception(f"CADGenerator init: {e}")
            return None
    return _cad_generator

# ==========================================================================
# МАРШРУТЫ FLASK
# ==========================================================================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/slicer')
def slicer():
    return render_template('slicer.html')

@app.route('/set_language', methods=['POST'])
def set_language():
    data = request.get_json()
    lang = data.get('language', 'ru')
    try:
        import skills.llm_skill as llm_skill
        llm_skill.set_language(lang)
        return jsonify({"status": "ok", "language": lang})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/sessions', methods=['GET'])
def get_sessions():
    try:
        import skills.memory_skill as memory_skill
        sessions = memory_skill._skill.get_all_sessions()
        return jsonify({"sessions": sessions})
    except Exception as e:
        logger.error(f"Ошибка получения сессий: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/load_session', methods=['POST'])
def load_session():
    data = request.get_json()
    session_id = data.get('session_id')
    if not session_id:
        return jsonify({"error": "session_id required"}), 400
    try:
        import skills.memory_skill as memory_skill
        resp = memory_skill.handle_message(f"/switch {session_id}")
        name = memory_skill._skill.get_session_name(session_id)
        return jsonify({"status": "ok", "message": resp, "name": name})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/new_session', methods=['POST'])
def new_session_route():
    data = request.get_json()
    name = data.get('name', None) if data else None
    try:
        import skills.memory_skill as memory_skill
        session_id = memory_skill._skill.new_session(name=name)
        session_name = memory_skill._skill.get_session_name(session_id)
        return jsonify({"status": "ok", "session_id": session_id, "name": session_name})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/delete_session', methods=['POST'])
def delete_session():
    data = request.get_json()
    session_id = data.get('session_id')
    if not session_id:
        return jsonify({"error": "session_id required"}), 400
    try:
        import skills.memory_skill as memory_skill
        resp = memory_skill.handle_message(f"/delete {session_id}")
        return jsonify({"status": "ok", "message": resp})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/model/<filename>')
def get_model(filename):
    return send_from_directory(os.path.join(project_root, 'output'), filename, as_attachment=False)

@app.route('/gcode/<filename>')
def get_gcode(filename):
    gcode_dir = os.path.join(project_root, 'gcode')
    return send_from_directory(gcode_dir, filename, as_attachment=True)

@app.route('/slice', methods=['POST'])
def slice_model():
    data = request.get_json()
    if not data or 'filename' not in data:
        return jsonify({"error": "Нет имени файла"}), 400
    filename = data['filename']
    try:
        import skills.slicer_skill as slicer_skill
        result = slicer_skill.handle_message(json.dumps({"command": "slice", "filename": filename}))
        try:
            return jsonify(json.loads(result))
        except:
            return jsonify({"error": result})
    except Exception:
        return jsonify({"error": "Внутренняя ошибка сервера"}), 500

@app.route('/upload_model', methods=['POST'])
def upload_model():
    if 'model' not in request.files:
        return jsonify({"error": "Файл не найден"}), 400
    file = request.files['model']
    if file.filename == '':
        return jsonify({"error": "Имя файла не указано"}), 400
    if file and file.filename.endswith('.zip'):
        zip_path = os.path.join(UPLOAD_FOLDER, file.filename)
        file.save(zip_path)
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(UPLOAD_FOLDER)
        model_file = None
        for root, dirs, files in os.walk(UPLOAD_FOLDER):
            for f in files:
                if f.endswith(('.glb', '.gltf')):
                    model_file = os.path.relpath(os.path.join(root, f), UPLOAD_FOLDER)
                    break
        if model_file:
            dest = os.path.join(os.path.dirname(__file__), 'static', 'models', 'custom_model.glb')
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy(os.path.join(UPLOAD_FOLDER, model_file), dest)
            return jsonify({"status": "ok", "filename": "custom_model.glb"})
        else:
            return jsonify({"error": "Модель не найдена в архиве"}), 400
    else:
        return jsonify({"error": "Поддерживаются только .zip архивы"}), 400

@app.route('/upload_stl', methods=['POST'])
def upload_stl():
    if 'file' not in request.files:
        return jsonify({"error": "Нет файла"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "Имя файла не указано"}), 400
    if not file.filename.lower().endswith('.stl'):
        return jsonify({"error": "Только STL файлы"}), 400
    filename = file.filename
    safe_name = os.path.basename(filename)
    filepath = os.path.join(project_root, 'output', safe_name)
    file.save(filepath)
    logger.info(f"Загружен STL: {safe_name}")
    return jsonify({"status": "ok", "filename": safe_name})

# ==========================================================================
# API ДЛЯ ДВУПОЛУШАРНОГО МОЗГА
# ==========================================================================
@app.route('/api/brain/state', methods=['GET'])
def brain_state():
    try:
        import skills.dual_hemisphere_cloud as dh
        skill = dh.get_skill()
        if not skill:
            return jsonify({"error": "Мозг не инициализирован"}), 500
        return jsonify(skill.get_brain_state())
    except Exception as e:
        logger.exception("Ошибка состояния мозга")
        return jsonify({"error": str(e)}), 500

@app.route('/api/brain/hemisphere/<hemisphere>', methods=['GET'])
def brain_hemisphere(hemisphere):
    try:
        import skills.dual_hemisphere_cloud as dh
        skill = dh.get_skill()
        if not skill:
            return jsonify({"error": "Мозг не инициализирован"}), 500
        return jsonify(skill.get_hemisphere_details(hemisphere))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/brain/cross_talk', methods=['POST'])
def brain_cross_talk():
    try:
        import skills.dual_hemisphere_cloud as dh
        skill = dh.get_skill()
        if not skill:
            return jsonify({"error": "Мозг не инициализирован"}), 500
        result = skill.manual_cross_talk()
        return jsonify({"status": "ok", **result})
    except Exception as e:
        logger.exception("Ошибка cross-talk")
        return jsonify({"error": str(e)}), 500

@app.route('/api/brain/resources', methods=['GET'])
def brain_resources():
    try:
        import skills.dual_hemisphere_cloud as dh
        skill = dh.get_skill()
        if not skill:
            return jsonify({"error": "Мозг не инициализирован"}), 500
        return jsonify(skill.guard.status())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/brain/hemisphere/<hemisphere>/code', methods=['GET'])
def brain_hemisphere_code_get(hemisphere):
    if hemisphere not in ('left', 'right'):
        return jsonify({"error": "Неверное полушарие"}), 400
    try:
        import skills.dual_hemisphere_cloud as dh
        skill = dh.get_skill()
        if not skill:
            return jsonify({"error": "Мозг не инициализирован"}), 500
        code = skill.get_hemisphere_python_code(hemisphere)
        return jsonify({"status": "ok", "hemisphere": hemisphere, "code": code})
    except Exception as e:
        logger.exception("Ошибка экспорта кода")
        return jsonify({"error": str(e)}), 500

@app.route('/api/brain/hemisphere/<hemisphere>/code', methods=['POST'])
def brain_hemisphere_code_save(hemisphere):
    if hemisphere not in ('left', 'right'):
        return jsonify({"error": "Неверное полушарие"}), 400
    data = request.get_json(silent=True) or {}
    code = data.get('code', '')
    if not code.strip():
        return jsonify({"error": "Пустой код"}), 400
    try:
        import skills.dual_hemisphere_cloud as dh
        skill = dh.get_skill()
        if not skill:
            return jsonify({"error": "Мозг не инициализирован"}), 500
        result = skill.save_hemisphere_python_code(hemisphere, code)
        if "error" in result:
            return jsonify(result), 400
        try:
            socketio.emit('brain_reset', {'hemisphere': hemisphere})
        except Exception:
            pass
        return jsonify({"status": "ok", "hemisphere": hemisphere, **result})
    except Exception as e:
        logger.exception("Ошибка импорта кода")
        return jsonify({"error": str(e)}), 500

@app.route('/api/brain/activate', methods=['POST'])
def brain_activate():
    data = request.get_json(silent=True) or {}
    hemi = data.get('hemisphere', 'left')
    name = data.get('name')
    strength = float(data.get('strength', 0.8))
    if not name:
        return jsonify({"error": "name обязателен"}), 400
    try:
        import skills.dual_hemisphere_cloud as dh
        skill = dh.get_skill()
        if not skill:
            return jsonify({"error": "Мозг не инициализирован"}), 500
        result = skill.engine.activate_by_name(hemi, name, strength, create=True, spread=True)
        return jsonify({"status": "ok", **result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/brain/process/start', methods=['POST'])
def brain_process_start():
    data = request.get_json(silent=True) or {}
    try:
        import skills.dual_hemisphere_cloud as dh
        skill = dh.get_skill()
        if not skill:
            return jsonify({"error": "Мозг не инициализирован"}), 500
        pid = skill.engine.track_process(
            data.get('process_type', 'general'),
            data.get('context', {}),
            data.get('hemisphere', 'left')
        )
        return jsonify({"status": "ok", "process_id": pid})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/brain/process/end', methods=['POST'])
def brain_process_end():
    data = request.get_json(silent=True) or {}
    pid = data.get('process_id')
    if not pid:
        return jsonify({"error": "process_id обязателен"}), 400
    try:
        import skills.dual_hemisphere_cloud as dh
        skill = dh.get_skill()
        if skill:
            skill.engine.end_process(pid)
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/brain/decay', methods=['POST'])
def brain_decay():
    try:
        import skills.dual_hemisphere_cloud as dh
        skill = dh.get_skill()
        if not skill:
            return jsonify({"error": "Мозг не инициализирован"}), 500
        skill.engine.decay_all()
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/brain/prune', methods=['POST'])
def brain_prune():
    try:
        import skills.dual_hemisphere_cloud as dh
        skill = dh.get_skill()
        if not skill:
            return jsonify({"error": "Мозг не инициализирован"}), 500
        result = skill.engine.prune()
        return jsonify({"status": "ok", **result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/brain/bootstrap', methods=['POST'])
def brain_bootstrap_route():
    data = request.get_json(silent=True) or {}
    hemi = data.get('hemisphere', 'left')
    try:
        import skills.dual_hemisphere_cloud as dh
        from skills.brain_bootstrap import bootstrap_hemisphere
        skill = dh.get_skill()
        if not skill:
            return jsonify({"error": "Мозг не инициализирован"}), 500
        model = skill.left_model if hemi == 'left' else skill.right_model
        result = bootstrap_hemisphere(skill.engine, hemi, model)
        try:
            socketio.emit('brain_reset', {'hemisphere': hemi})
        except Exception:
            pass
        return jsonify({"status": "ok", **result})
    except Exception as e:
        logger.exception("Bootstrap ошибка")
        return jsonify({"error": str(e)}), 500

def _hook_neural_engine_emit():
    """Подключает Socket.IO к NeuralEngine для трансляции активаций."""
    try:
        import skills.dual_hemisphere_cloud as dh
        skill = dh.get_skill()
        if not skill:
            return
        def _emit(event_name: str, payload: dict):
            try:
                socketio.emit(event_name, payload)
            except Exception as e:
                logger.debug(f"socketio emit {event_name}: {e}")
        skill.engine.set_emit_callback(_emit)
        logger.info("NeuralEngine ↔ Socket.IO подключение установлено")
    except Exception as e:
        logger.warning(f"Не удалось подключить Socket.IO к NeuralEngine: {e}")

def _preload_picogk():
    """Прогреваем PicoGK при старте — первая генерация будет быстрее."""
    # Указываем Python для worker'а (важно для PyInstaller)
    real_python = "/home/klhhhhh/urfin-jus/urfin_env/bin/python3"
    if os.path.exists(real_python):
        os.environ["URFIN_CAD_PYTHON"] = real_python
        logger.info(f"✅ URFIN_CAD_PYTHON установлен: {real_python}")
    
    try:
        from skills.picogk_binding import get_picogk
        pg = get_picogk(voxel_size_mm=0.5)
        v = pg.version()
        logger.info(f"✅ PicoGK предзагружен: v{v}")
        # Не вызываем cleanup — оставляем инстанс живым
    except Exception as e:
        logger.warning(f"⚠️ PicoGK не предзагрузился: {e}")

# ==========================================================================
# УТИЛИТЫ
# ==========================================================================
def _strip_thinking(text: str) -> str:
    """Убирает reasoning-блоки DeepSeek-R1 из ответа."""
    if not text:
        return ""
    text = re.sub(r'<think(?:ing)?>.*?</think(?:ing)?>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<think(?:ing)?>.*$', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

# ==========================================================================
# ЧАТ (основной)
# ==========================================================================
@socketio.on('user_message')
def handle_user_message(data):
    user_text = data.get('text', '').strip()
    if not user_text:
        return

    try:
        resp_json = orchestrator_skill.handle_message(
            json.dumps({"command": "process", "input": user_text})
        )
        resp_data = json.loads(resp_json)

        if "error" in resp_data:
            emit('assistant_message', {'text': f"Ошибка: {resp_data['error']}"})
            return

        response_text = (
            resp_data.get("final_answer")
            or resp_data.get("response")
            or ""
        ).strip()

        response_text = _strip_thinking(response_text)

        if not response_text:
            logger.warning(f"Пустой ответ от LLM. keys: {list(resp_data.keys())}")
            emit('assistant_message', {
                'text': "⚠️ Модель вернула пустой ответ. Проверь Ollama (ollama ps)."
            })
            return

        if "filename" in resp_data:
            filename = resp_data["filename"]
            emit('generation_result', {'filename': filename, 'prompt': user_text})
            emit('assistant_message', {'text': response_text})
            return

        if "solutions" in resp_data:
            solutions = resp_data["solutions"]
            if solutions:
                dual_text = "🧠 Предложенные решения:\n" + "\n".join(
                    [f"{i+1}. {s}" for i, s in enumerate(solutions)]
                )
                emit('dual_opinions', {"text": dual_text})

        emit('assistant_message', {'text': response_text})

    except Exception as e:
        logger.exception("Ошибка обработки сообщения")
        emit('assistant_message', {'text': f'Извините, произошла ошибка: {str(e)}'})

# ==========================================================================
# НОВЫЙ ГЕНЕРАТОР CAD (через PicoGK)
# ==========================================================================
@socketio.on('generate_model_advanced')
def handle_generate_model_advanced(data):
    """
    Полный pipeline: промпт → LLM → PicoGK (subprocess) → STL.
    """
    prompt = (data.get('prompt') or '').strip()
    num_variants = int(data.get('num_variants', 1))
    if not prompt:
        emit('model_error', {'error': 'Пустой промпт'})
        return

    gen = _get_cad_generator()
    if not gen:
        emit('model_error', {'error': 'CADGenerator не инициализирован'})
        return

    emit('cad_progress', {'stage': 'analysis', 'text': 'PicoGK анализирует запрос...'})

    try:
        result = gen.generate(prompt, num_variants)

        if result.get("error"):
            emit('model_error', {'error': result["error"]})
            return

        emit('cad_progress', {
            'stage': 'variants',
            'text': f'Готово: {len(result["variants"])} вариант(ов)'
        })

        best_idx = result.get("best_index", 0)
        best = result["variants"][best_idx] if result["variants"] else {}

        emit('model_generated_advanced', {
            'prompt': prompt,
            'variants': result["variants"],
            'best_index': best_idx,
            'analysis': result.get("analysis", {}),
            'triz': result.get("triz", {}),
            'logs': result.get("logs", []),
            'stl_base64': best.get("stl_base64", ""),
            'vertices': best.get("vertices", []),
            'faces': best.get("faces", []),
            'code': best.get("code", ""),
        })

    except Exception as e:
        logger.exception("generate_model_advanced упал")
        emit('model_error', {'error': str(e)})

# ==========================================================================
# EXPLODE — РАЗБОР МОДЕЛИ НА ЧАСТИ
# ==========================================================================
@socketio.on('explode_model')
def handle_explode_model(data):
    try:
        import trimesh
        import numpy as np
        import io
        import base64 as b64

        stl_data = data.get('stl_base64', '')
        filename = data.get('filename', '')

        if stl_data:
            raw = b64.b64decode(stl_data)
            mesh = trimesh.load(io.BytesIO(raw), file_type='stl')
        elif filename:
            filepath = os.path.join(project_root, 'output', filename)
            mesh = trimesh.load(filepath)
        else:
            emit('explode_error', {'error': 'Не передан stl_base64 или filename'})
            return

        try:
            components = mesh.split(only_watertight=False)
        except Exception as e:
            logger.warning(f"trimesh.split не сработал ({e}), fallback")
            components = _split_mesh_fallback(mesh)

        if not components or len(components) == 0:
            emit('explode_error', {'error': 'Не удалось разбить модель'})
            return

        parts = []
        for i, comp in enumerate(components):
            try:
                buf = io.BytesIO()
                comp.export(buf, file_type='stl')
                b64_str = b64.b64encode(buf.getvalue()).decode('utf-8')
                center = comp.centroid.tolist()
                bounds = comp.bounds
                parts.append({
                    "index": i,
                    "stl_base64": b64_str,
                    "vertices": comp.vertices.tolist(),
                    "faces": comp.faces.tolist(),
                    "center": center,
                    "volume": float(comp.volume) if comp.is_watertight else 0.0,
                    "bbox": {"min": bounds[0].tolist(), "max": bounds[1].tolist()},
                })
            except Exception as e:
                logger.warning(f"Часть {i} пропущена: {e}")
                continue

        if not parts:
            emit('explode_error', {'error': 'Ни одной части не удалось извлечь'})
            return

        emit('model_exploded', {'parts': parts, 'total': len(parts)})

    except Exception as e:
        logger.exception("explode_model упал")
        emit('explode_error', {'error': str(e)})

def _split_mesh_fallback(mesh):
    """Разбор модели без graph engine — через scipy.sparse.csgraph."""
    try:
        import numpy as np
        import trimesh
        from scipy.sparse import coo_matrix
        from scipy.sparse.csgraph import connected_components

        faces = mesh.faces
        n_verts = len(mesh.vertices)
        edges = np.vstack([
            faces[:, [0, 1]],
            faces[:, [1, 2]],
            faces[:, [2, 0]],
        ])
        data = np.ones(len(edges), dtype=np.int8)
        adj = coo_matrix((data, (edges[:, 0], edges[:, 1])), shape=(n_verts, n_verts))
        n_comp, labels = connected_components(adj, directed=False)

        components = []
        for label in range(n_comp):
            vert_indices = np.where(labels == label)[0]
            if len(vert_indices) < 3:
                continue
            mask = np.isin(faces[:, 0], vert_indices)
            sub_faces = faces[mask]
            if len(sub_faces) == 0:
                continue
            sub_mesh = trimesh.Trimesh(vertices=mesh.vertices, faces=sub_faces, process=False)
            sub_mesh.remove_unreferenced_vertices()
            components.append(sub_mesh)
        return components
    except Exception as e:
        logger.error(f"fallback split тоже упал: {e}")
        return [mesh]

# ==========================================================================
# ОБРАБОТЧИКИ РОБОТОВ (ROS2)
# ==========================================================================
@socketio.on('register_robot')
def handle_register_robot(data):
    if ros2_skill is None:
        return
    robot_id = data.get('id')
    robot_type = data.get('type', 'unknown')
    pos = data.get('pos', {'x':0,'y':0,'z':0})
    urdf_path = data.get('urdf_path', None)
    try:
        ros2_skill.handle_message(json.dumps({
            "command": "register_robot",
            "robot_id": robot_id,
            "params": {"type": robot_type, "position": pos, "urdf_path": urdf_path}
        }))
    except Exception as e:
        logger.error(f"Ошибка регистрации: {e}")

@socketio.on('unregister_robot')
def handle_unregister_robot(data):
    if ros2_skill is None:
        return
    try:
        ros2_skill.handle_message(json.dumps({
            "command": "unregister_robot",
            "robot_id": data.get('id')
        }))
    except Exception as e:
        logger.error(f"Ошибка удаления: {e}")

@socketio.on('assign_team')
def handle_assign_team(data):
    if ros2_skill is None:
        return
    robot_id = data.get('robot_id')
    team = data.get('team')
    if robot_id and team:
        try:
            ros2_skill.handle_message(json.dumps({
                "command": "assign_team",
                "robot_id": robot_id,
                "params": {"team": team}
            }))
        except Exception as e:
            logger.error(f"Ошибка команды: {e}")

@socketio.on('set_leader')
def handle_set_leader(data):
    if ros2_skill is None:
        return
    team = data.get('team')
    robot_id = data.get('robot_id')
    if team and robot_id:
        try:
            ros2_skill.handle_message(json.dumps({
                "command": "set_leader",
                "robot_id": robot_id,
                "params": {"team": team}
            }))
        except Exception as e:
            logger.error(f"Ошибка лидера: {e}")

@socketio.on('update_position')
def handle_update_position(data):
    if ros2_skill is None:
        return
    robot_id = data.get('robot_id')
    pos = data.get('pos')
    if robot_id and pos:
        try:
            ros2_skill.handle_message(json.dumps({
                "command": "update_position",
                "robot_id": robot_id,
                "params": {"position": pos}
            }))
        except Exception as e:
            logger.error(f"Ошибка позиции: {e}")

@socketio.on('robot_command')
def handle_robot_command(data):
    if ros2_skill is None:
        emit('robot_response', {'text': '❌ ros2_skill недоступен'})
        return
    robot_id = data.get('robot_id')
    command = data.get('command')
    params = data.get('params', {})
    if not robot_id or not command:
        emit('assistant_message', {'text': 'Ошибка: не указан robot_id или команда'})
        return
    try:
        resp = ros2_skill.handle_message(json.dumps({
            "command": command,
            "robot_id": robot_id,
            "params": params
        }))
        try:
            resp_data = json.loads(resp)
            if resp_data.get('status') == 'ok':
                emit('robot_response', {'robot_id': robot_id, 'text': f'✅ {command}'})
            else:
                emit('robot_response', {'robot_id': robot_id, 'text': f'❌ {resp_data.get("error", "unknown")}'})
        except:
            emit('robot_response', {'robot_id': robot_id, 'text': resp})
    except Exception as e:
        logger.exception(f"Ошибка команды {command}")
        emit('robot_response', {'robot_id': robot_id, 'text': f'Ошибка: {str(e)}'})

# ==========================================================================
# ТОЧКИ СИМУЛЯЦИИ
# ==========================================================================
@socketio.on('add_point')
def handle_add_point(data):
    global point_counter
    with data_lock:
        if len(capture_points) >= MAX_POINTS:
            socketio.emit('robot_response', {'text': f'🤖 Достигнут максимум ({MAX_POINTS})'})
            return
        x = data.get('x', 0)
        z = data.get('z', 0)
        point_counter += 1
        capture_points[point_counter] = {'x': x, 'z': z, 'color': 'white', 'captured_by': None}
        socketio.emit('point_added', {'point_id': point_counter, 'x': x, 'z': z})

@socketio.on('remove_point')
def handle_remove_point(data):
    point_id = data.get('point_id')
    with data_lock:
        if point_id in capture_points:
            del capture_points[point_id]
            socketio.emit('point_removed', {'point_id': point_id})

# ==========================================================================
# ПРЯМЫЕ КОМАНДЫ
# ==========================================================================
@socketio.on('direct_command')
def handle_direct_command(data):
    skill = data.get("skill")
    command = data.get("command")
    params = data.get("params", {})
    if not skill or not command:
        emit('assistant_message', {'text': "Ошибка: не указан навык или команда"})
        return
    payload = {"command": command, "params": params}
    try:
        mod = __import__("skills." + skill, fromlist=["handle_message"])
        if hasattr(mod, "handle_message"):
            resp = mod.handle_message(json.dumps(payload))
            emit('assistant_message', {'text': f"[{skill}]: {resp}"})
        else:
            emit('assistant_message', {'text': f"Навык {skill} без handle_message"})
    except Exception as e:
        emit('assistant_message', {'text': f'Ошибка: {e}'})

# ==========================================================================
# ПРИНТЕР
# ==========================================================================
@socketio.on('printer_connect')
def handle_printer_connect(data):
    if printer_skill is None:
        socketio.emit('printer_log', {'text': '❌ printer_skill недоступен (pyserial)', 'type': 'error'})
        return
    printer_type = data.get('printer_type', 'unknown')
    address = data.get('address')
    port = data.get('port')
    protocol = data.get('protocol', 'tcp')
    connection_type = data.get('connection_type', 'usb')
    api_key = data.get('api_key', None)
    http_gcode_url = data.get('http_gcode_url', None)

    if not address:
        socketio.emit('printer_log', {'text': '❌ Не указан адрес'})
        return

    if connection_type == 'usb':
        cmd = {"command": "connect", "params": {
            "printer_type": printer_type, "address": address, "connection_type": "usb"}}
    else:
        cmd = {"command": "connect", "params": {
            "printer_type": printer_type, "address": address, "port": port,
            "protocol": protocol, "api_key": api_key,
            "connection_type": connection_type, "http_gcode_url": http_gcode_url}}

    try:
        result = printer_skill.handle_message(json.dumps(cmd))
        data_res = json.loads(result)
        if data_res.get('status') == 'ok':
            socketio.emit('printer_log', {'text': f'✅ {address}', 'type': 'ok'})
        else:
            socketio.emit('printer_log', {'text': f'❌ {data_res.get("message", "error")}', 'type': 'error'})
    except Exception as e:
        logger.exception("Ошибка подключения принтера")
        socketio.emit('printer_log', {'text': f'❌ {e}', 'type': 'error'})

@socketio.on('printer_disconnect')
def handle_printer_disconnect():
    if printer_skill is None:
        return
    try:
        printer_skill.handle_message(json.dumps({"command": "disconnect"}))
        socketio.emit('printer_log', {'text': '🔌 Отключено', 'type': 'warn'})
        socketio.emit('printer_status', {'status': 'disconnected'})
    except Exception as e:
        socketio.emit('printer_log', {'text': f'❌ {e}', 'type': 'error'})

@socketio.on('discover_printers')
def handle_discover_printers():
    try:
        from printer_discovery import discover_printers
        def on_printer_found(printer_data):
            socketio.emit('printer_discovered', printer_data)
        def on_discovery_complete():
            socketio.emit('printer_discovery_complete')
        def discovery_worker():
            discovery = discover_printers(on_printer_found, duration=15)
            on_discovery_complete()
        threading.Thread(target=discovery_worker, daemon=True).start()
        socketio.emit('printer_log', {'text': '🔍 Поиск принтеров...', 'type': 'info'})
    except ImportError:
        socketio.emit('printer_log', {'text': '❌ printer_discovery не найден', 'type': 'error'})
    except Exception as e:
        socketio.emit('printer_log', {'text': f'❌ {e}', 'type': 'error'})

@socketio.on('printer_start')
def handle_printer_start():
    if printer_skill is None:
        return
    try:
        result = printer_skill.handle_message(json.dumps({"command": "start"}))
        data = json.loads(result)
        if data.get('status') == 'ok':
            socketio.emit('printer_log', {'text': '▶ Печать запущена', 'type': 'ok'})
        else:
            socketio.emit('printer_log', {'text': f'❌ {data.get("error")}', 'type': 'error'})
    except Exception as e:
        socketio.emit('printer_log', {'text': f'❌ {e}', 'type': 'error'})

@socketio.on('printer_pause')
def handle_printer_pause():
    if printer_skill is None:
        return
    try:
        printer_skill.handle_message(json.dumps({"command": "pause"}))
        socketio.emit('printer_log', {'text': '⏸ Пауза', 'type': 'warn'})
    except Exception as e:
        socketio.emit('printer_log', {'text': f'❌ {e}', 'type': 'error'})

@socketio.on('printer_resume')
def handle_printer_resume():
    if printer_skill is None:
        return
    try:
        printer_skill.handle_message(json.dumps({"command": "resume"}))
        socketio.emit('printer_log', {'text': '▶ Возобновлено', 'type': 'ok'})
    except Exception as e:
        socketio.emit('printer_log', {'text': f'❌ {e}', 'type': 'error'})

@socketio.on('printer_stop')
def handle_printer_stop():
    if printer_skill is None:
        return
    try:
        printer_skill.handle_message(json.dumps({"command": "stop"}))
        socketio.emit('printer_log', {'text': '⏹ Остановлено', 'type': 'error'})
    except Exception as e:
        socketio.emit('printer_log', {'text': f'❌ {e}', 'type': 'error'})

@socketio.on('printer_clear_bed')
def handle_printer_clear_bed():
    if printer_skill is None:
        return
    try:
        printer_skill.handle_message(json.dumps({"command": "clear"}))
        socketio.emit('printer_log', {'text': '🧹 Очищено', 'type': 'info'})
    except Exception as e:
        socketio.emit('printer_log', {'text': f'❌ {e}', 'type': 'error'})

@socketio.on('printer_load_model')
def handle_printer_load_model(data):
    model_name = data.get('model_name', '')
    socketio.emit('printer_log', {'text': f'📦 Модель: {model_name}', 'type': 'info'})

@socketio.on('printer_slice')
def handle_printer_slice(data):
    settings = data.get('settings', {})
    filename = data.get('filename')
    if not filename:
        global last_generated_model
        if last_generated_model:
            filename = last_generated_model
        else:
            socketio.emit('printer_log', {'text': '❌ Нет файла', 'type': 'error'})
            return
    try:
        import skills.slicer_skill as slicer_skill
        payload = {"command": "slice", "filename": filename, "params": settings}
        result = slicer_skill.handle_message(json.dumps(payload))
        try:
            data_res = json.loads(result)
            if data_res.get('status') == 'ok':
                gcode_file = data_res.get('gcode_file')
                socketio.emit('printer_log', {'text': f'✅ G-code: {gcode_file}', 'type': 'ok'})
                socketio.emit('printer_status', {'status': 'sliced', 'gcode': gcode_file})
            else:
                socketio.emit('printer_log', {'text': f'❌ {data_res.get("error")}', 'type': 'error'})
        except Exception as e:
            socketio.emit('printer_log', {'text': f'❌ {e}', 'type': 'error'})
    except Exception as e:
        socketio.emit('printer_log', {'text': f'❌ {e}', 'type': 'error'})

last_generated_model = None

@socketio.on('generation_result')
def handle_generation_result(data):
    global last_generated_model
    if data.get('filename'):
        last_generated_model = data['filename']

# ==========================================================================
# КАЛИБРОВКА
# ==========================================================================
@socketio.on('calibration_start')
def handle_calibration_start(data):
    if printer_skill is None:
        return
    try:
        if not printer_skill.printer.connected:
            socketio.emit('printer_log', {'text': '❌ Принтер не подключён', 'type': 'error'})
            return
        cal_type = data.get('type', 'unknown')
        socketio.emit('printer_log', {'text': f'🔧 Калибровка: {cal_type}', 'type': 'info'})
        for i in range(0, 101, 10):
            time.sleep(0.5)
            socketio.emit('printer_log', {
                'text': f'Калибровка: {i}%', 'type': 'calibration', 'progress': i
            })
        socketio.emit('printer_log', {'text': '✅ Калибровка завершена', 'type': 'ok'})
        socketio.emit('printer_status', {'status': 'idle', 'progress': 0})
    except Exception as e:
        logger.error(f"Ошибка калибровки: {e}")
        socketio.emit('printer_log', {'text': f'❌ {e}', 'type': 'error'})

@socketio.on('calibration_abort')
def handle_calibration_abort():
    socketio.emit('printer_log', {'text': '⏹ Калибровка прервана', 'type': 'warn'})

# ==========================================================================
# ФИЗИЧЕСКАЯ СИМУЛЯЦИЯ
# ==========================================================================
@socketio.on('physics_simulate')
def handle_physics_simulate(data):
    """
    Простая физика: модель падает с высоты и отскакивает от пола.
    Работает на фронтенде (Three.js), бэкенд только подтверждает запрос.
    """
    filename = data.get('filename')
    if not filename:
        socketio.emit('physics_error', {'error': 'Не указан файл'})
        return

    stl_path = os.path.join(project_root, 'output', filename)
    if not os.path.exists(stl_path):
        socketio.emit('physics_error', {'error': f'Файл {filename} не найден'})
        return

    logger.info(f"Физика запущена для {filename}")
    socketio.emit('physics_started', {'status': 'ok', 'filename': filename})

# ==========================================================================
# ЗАПУСК
# ==========================================================================
if __name__ == '__main__':
    print("Запуск сервера на http://localhost:5000")
    _preload_picogk()                # ← НОВАЯ СТРОКА
    _hook_neural_engine_emit()
    socketio.run(app, host='0.0.0.0', port=5000, debug=False, allow_unsafe_werkzeug=True)