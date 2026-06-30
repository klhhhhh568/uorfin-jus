import sys, os, json, threading, re, time, random, math, logging
import shutil
import zipfile
from pathlib import Path
from copy import deepcopy

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'skills'))
from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_socketio import SocketIO, emit
from core_client import send_to_core
import dual_hemisphere_cloud

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

data_lock = threading.RLock()

robots_health = {}
robots_positions = {}
robots_type = {}
robots_team = {}
team_leaders = {'blue': None, 'yellow': None, 'red': None, 'green': None}
active_defend_tasks = {}
scout_targets = {}
battle_states = {}

capture_points = {}
point_counter = 0
MAX_POINTS = 5

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), '..', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

COLOR_MAP = {
    'синий': 'blue', 'синяя': 'blue', 'синие': 'blue',
    'красный': 'red', 'красная': 'red', 'красные': 'red',
    'жёлтый': 'yellow', 'жёлтая': 'yellow', 'жёлтые': 'yellow',
    'зелёный': 'green', 'зелёная': 'green', 'зелёные': 'green',
    'blue': 'blue', 'red': 'red', 'yellow': 'yellow', 'green': 'green'
}

# ---------- Фоновая проверка врагов ----------
def auto_attack_check():
    while True:
        time.sleep(0.5)
        with data_lock:
            positions = deepcopy(robots_positions)
            health = deepcopy(robots_health)
            teams = deepcopy(robots_team)
        for robot_id, pos in positions.items():
            if robot_id not in health or health[robot_id] <= 0:
                continue
            team = teams.get(robot_id)
            if not team:
                continue
            for other_id, other_pos in positions.items():
                if other_id == robot_id or other_id not in health or health[other_id] <= 0:
                    continue
                other_team = teams.get(other_id)
                if other_team == team or not other_team:
                    continue
                dist = math.hypot(pos['x']-other_pos['x'], pos['z']-other_pos['z'])
                if dist < 15:
                    logger.info(f"Авто-атака: {robot_id} стреляет в {other_id}")
                    socketio.emit('robot_animate', {
                        'robot_id': robot_id,
                        'action': 'attack',
                        'value': 1,
                        'target': other_id
                    })
                    with data_lock:
                        if other_id in robots_health and robots_health[other_id] > 0:
                            damage = random.randint(10, 30)
                            robots_health[other_id] = max(0, robots_health[other_id] - damage)
                            socketio.emit('health_update', {'robot_id': other_id, 'health': robots_health[other_id]})
                            if robots_health[other_id] <= 0:
                                socketio.emit('robot_dead', {'robot_id': other_id, 'team': teams.get(other_id)})
                    break

threading.Thread(target=auto_attack_check, daemon=True).start()

# ---------- Плагины ----------
def init_plugins():
    plugins = [
        "charter_skill", "memory_skill", "orchestrator_skill",
        "printer_skill", "picogk_skill", "ros2_skill",
        "dual_hemisphere_cloud", "council_skill", "cerebellum_skill",
        "slicer_skill"
    ]
    for p in plugins:
        try:
            resp = send_to_core({"command": "load_py", "plugin": p})
            logger.info(f"Плагин {p}: {resp.get('text', 'нет ответа')}")
        except Exception as e:
            logger.warning(f"Плагин {p} пропущен: {e}")

threading.Thread(target=init_plugins, daemon=True).start()

# ---------- Маршруты Flask ----------
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/generate', methods=['POST'])
def generate_model():
    data = request.get_json()
    if not data or 'prompt' not in data:
        return jsonify({"error": "Нет промпта"}), 400
    prompt = data['prompt']
    try:
        raw = send_to_core({"skill": "picogk_skill", "text": json.dumps({"command": "generate", "prompt": prompt})})
        inner_text = raw.get("text", "")
        try:
            result = json.loads(inner_text)
        except json.JSONDecodeError:
            result = {"error": "Ошибка обработки запроса в ядре"}
        return jsonify(result)
    except Exception:
        return jsonify({"error": "Внутренняя ошибка сервера"}), 500

@app.route('/model/<filename>')
def get_model(filename):
    return send_from_directory(os.path.join(os.path.dirname(__file__), '..', 'output'), filename, as_attachment=False)

@app.route('/slice', methods=['POST'])
def slice_model():
    data = request.get_json()
    if not data or 'filename' not in data:
        return jsonify({"error": "Нет имени файла"}), 400
    filename = data['filename']
    try:
        raw = send_to_core({"skill": "slicer_skill", "text": json.dumps({"command": "slice", "filename": filename})})
        inner_text = raw.get("text", "")
        try:
            result = json.loads(inner_text)
        except json.JSONDecodeError:
            result = {"error": "Ошибка обработки запроса в ядре"}
        return jsonify(result)
    except Exception:
        return jsonify({"error": "Внутренняя ошибка сервера"}), 500

@app.route('/gcode/<filename>')
def get_gcode(filename):
    gcode_dir = os.path.join(os.path.dirname(__file__), '..', 'gcode')
    return send_from_directory(gcode_dir, filename, as_attachment=True)

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

# ---------- Чат ----------
@socketio.on('user_message')
def handle_user_message(data):
    user_text = data.get('text', '').strip()
    try:
        send_to_core({"skill": "memory_skill", "text": f"add|user|{user_text}"})
    except:
        pass
    greetings = ["привет", "здравствуй", "hello", "hi", "кто ты", "что ты умеешь", "помощь"]
    if any(g in user_text.lower() for g in greetings):
        greeting_text = (
            "Я Урфин Джус, версия 0.9. Специализация: робототехника и промышленная автоматизация.\n"
            "Активные инструменты: printer_skill, picogk_skill, ros2_skill, memory_skill, charter_skill, dual_hemisphere_cloud, council_skill, cerebellum_skill, slicer_skill."
        )
        emit('assistant_message', {'text': greeting_text})
        return
    modeling_keywords = ['pico', 'gk', 'смоделировать', 'сгенерировать', 'модель', 'stl', 'деталь', 'сделай 3d']
    if any(kw in user_text.lower() for kw in modeling_keywords):
        emit('assistant_message', {'text': '⏳ Генерирую модель...'})
        threading.Thread(target=handle_modeling_command, args=(user_text,)).start()
        return
    emit('assistant_message', {'text': '⏳ Анализирую...'})
    threading.Thread(target=process_dual, args=(user_text,)).start()

def extract_final_answer(full_response):
    match = re.search(r'\*\*Исправленный вариант ответа:\*\*\s*>\s*(.*?)(?:\n\*\*Статус:|$)', full_response, re.DOTALL)
    if match: return match.group(1).strip()
    if full_response.startswith("✅ Решение принято:"): return full_response.replace("✅ Решение принято:", "").strip()
    return full_response[:300] + ("..." if len(full_response) > 300 else "")

def process_dual(user_text):
    try:
        ctx_resp = send_to_core({"skill": "memory_skill", "text": "/get_context"})
        context = ctx_resp.get("text", "")
        task = f"Пользователь спросил: {user_text}\nКонтекст диалога: {context}\nПроанализируй и дай ответ."
        full_result = dual_hemisphere_cloud.analyze(task)
        chat_answer = extract_final_answer(full_result)
        
        # ======== ИЗМЕНЕНИЕ ЗДЕСЬ ========
        # Меняем местами отправку данных:
        socketio.emit('dual_opinions', {"text": chat_answer})   # В правую панель отправляем краткий ответ
        socketio.emit('assistant_message', {'text': full_result}) # В основной чат отправляем полный разбор
        # ==================================
        
    except Exception:
        socketio.emit('assistant_message', {'text': 'Ошибка анализа'})
def handle_modeling_command(prompt):
    try:
        raw = send_to_core({"skill": "picogk_skill", "text": json.dumps({"command": "generate", "prompt": prompt})})
        inner = raw.get("text", "")
        try:
            result = json.loads(inner)
        except:
            socketio.emit('assistant_message', {'text': 'Ошибка генерации: внутренний сбой'})
            return
        if result.get('status') == 'ok':
            filename = result['filename']
            socketio.emit('generation_result', {'filename': filename, 'prompt': prompt})
            socketio.emit('assistant_message', {'text': f'✅ Модель создана: {filename}'})
        else:
            socketio.emit('assistant_message', {'text': f'Ошибка: {result.get("error", "неизвестная ошибка")}'})
    except Exception:
        socketio.emit('assistant_message', {'text': 'Ошибка связи с ядром'})

# ---------- Регистрация роботов ----------
@socketio.on('register_robot')
def handle_register_robot(data):
    robot_id = data.get('id')
    with data_lock:
        robots_health[robot_id] = 100
        robots_type[robot_id] = data.get('type', 'unknown')
        robots_positions[robot_id] = data.get('pos', {'x':0,'y':0,'z':0})

@socketio.on('unregister_robot')
def handle_unregister_robot(data):
    robot_id = data.get('id')
    with data_lock:
        robots_health.pop(robot_id, None)
        robots_type.pop(robot_id, None)
        robots_positions.pop(robot_id, None)
        robots_team.pop(robot_id, None)
        active_defend_tasks.pop(robot_id, None)
        scout_targets.pop(robot_id, None)

@socketio.on('assign_team')
def handle_assign_team(data):
    robot_id = data.get('robot_id')
    team = data.get('team')
    if robot_id and team:
        with data_lock:
            robots_team[robot_id] = team

@socketio.on('set_leader')
def handle_set_leader(data):
    team = data.get('team')
    robot_id = data.get('robot_id')
    if team in team_leaders:
        with data_lock:
            team_leaders[team] = robot_id

@socketio.on('update_position')
def handle_update_position(data):
    robot_id = data.get('robot_id')
    pos = data.get('pos')
    if robot_id and pos:
        with data_lock:
            if robot_id in robots_positions:
                robots_positions[robot_id] = pos

# ---------- Точки ----------
@socketio.on('add_point')
def handle_add_point(data):
    global point_counter
    with data_lock:
        if len(capture_points) >= MAX_POINTS:
            socketio.emit('robot_response', {'text': f'🤖 Достигнуто максимальное количество точек ({MAX_POINTS}).'})
            return
        x = data.get('x', 0)
        z = data.get('z', 0)
        point_counter += 1
        capture_points[point_counter] = {
            'x': x, 'z': z,
            'color': 'white',
            'captured_by': None
        }
        socketio.emit('point_added', {'point_id': point_counter, 'x': x, 'z': z})

@socketio.on('remove_point')
def handle_remove_point(data):
    point_id = data.get('point_id')
    with data_lock:
        if point_id in capture_points:
            del capture_points[point_id]
            socketio.emit('point_removed', {'point_id': point_id})

def start_capture_timer(point_id, robot_id):
    def capture():
        time.sleep(5)
        with data_lock:
            pt = capture_points.get(point_id)
            if not pt or robot_id not in robots_positions:
                return
            pos = robots_positions[robot_id]
            dist = math.hypot(pos['x']-pt['x'], pos['z']-pt['z'])
            if dist <= 5.5:
                team = robots_team.get(robot_id)
                if team:
                    pt['captured_by'] = team
                    socketio.emit('point_captured', {'point_id': point_id, 'team': team})
    threading.Thread(target=capture).start()

# ---------- Парсер команд ----------
def parse_single_command(cleaned):
    actions = []
    numbers = re.findall(r'\d+', cleaned)
    multiplier = int(numbers[0]) if numbers else 1
    target_team = None
    for color_ru, color_en in COLOR_MAP.items():
        if f'лидеру {color_ru}' in cleaned or f'к лидеру {color_ru}' in cleaned:
            target_team = color_en
            break

    if 'сесть' in cleaned:
        actions.append({'action': 'sit'})
        return actions
    if 'встать' in cleaned:
        actions.append({'action': 'stand'})
        return actions
    if 'идти за лидером' in cleaned or 'следовать за лидером' in cleaned:
        actions.append({'action': 'follow_leader', 'value': multiplier})
        return actions
    if 'штурм точки' in cleaned:
        m = re.search(r'штурм точки\s+(\d)', cleaned)
        if m:
            point = int(m.group(1))
            actions.append({'action': 'assault_point', 'point': point})
        else:
            actions.append({'action': 'unknown', 'reason': 'Укажите номер точки'})
        return actions
    if 'окружение точки' in cleaned or 'окружить точку' in cleaned:
        m = re.search(r'окружение точки\s+(\d)', cleaned)
        if m:
            point = int(m.group(1))
            actions.append({'action': 'encircle_point', 'point': point})
        else:
            actions.append({'action': 'unknown', 'reason': 'Укажите номер точки'})
        return actions
    if 'окружение команды' in cleaned or 'окружить команду' in cleaned:
        for color_ru, color_en in COLOR_MAP.items():
            if color_ru in cleaned:
                actions.append({'action': 'encircle_team', 'target_team': color_en})
                return actions
        actions.append({'action': 'unknown', 'reason': 'Укажите цвет команды'})
        return actions
    if 'захват всех точек' in cleaned or 'захватить все точки' in cleaned:
        actions.append({'action': 'capture_all_points'})
        return actions
    if 'захват лидера' in cleaned or 'захватить лидера' in cleaned:
        for color_ru, color_en in COLOR_MAP.items():
            if color_ru in cleaned:
                actions.append({'action': 'capture_leader', 'target_team': color_en})
                return actions
        actions.append({'action': 'unknown', 'reason': 'Укажите цвет лидера'})
        return actions
    if 'атака команды' in cleaned or 'атаковать команду' in cleaned:
        for color_ru, color_en in COLOR_MAP.items():
            if color_ru in cleaned:
                actions.append({'action': 'attack_team', 'target_team': color_en})
                return actions
        actions.append({'action': 'unknown', 'reason': 'Укажите цвет команды'})
        return actions
    if 'штурм' in cleaned and 'точки' not in cleaned:
        actions.append({'action': 'assault'})
        return actions
    if 'захват' in cleaned:
        actions.append({'action': 'capture'})
        return actions
    if 'отступить' in cleaned:
        actions.append({'action': 'retreat'})
        return actions
    if 'к лидеру' in cleaned or 'подойти к лидеру' in cleaned:
        actions.append({'action': 'goto_leader', 'target_team': target_team})
        return actions

    point = None
    m = re.search(r'точку\s+(\d)', cleaned)
    if m:
        point = int(m.group(1))
    else:
        if 'красную точку' in cleaned or 'красная точка' in cleaned: point = 1
        elif 'зелёную точку' in cleaned or 'зелёная точка' in cleaned: point = 2
        elif 'синюю точку' in cleaned or 'синяя точка' in cleaned: point = 3
    if point is not None:
        actions.append({'action': 'capture_point', 'point': point})
        return actions

    if 'в линию' in cleaned or 'в шеренгу' in cleaned:
        actions.append({'action': 'form_line'})
        return actions
    if 'в круг' in cleaned:
        actions.append({'action': 'form_circle'})
        return actions
    if 'защищать лидера' in cleaned or 'защита лидера' in cleaned:
        actions.append({'action': 'defend_leader'})
        return actions
    if 'атаковать' in cleaned or 'атакуй' in cleaned:
        target_match = re.search(r'атаковать\s+([\w]+)', cleaned)
        target_id = target_match.group(1) if target_match else None
        if target_id:
            actions.append({'action': 'attack', 'target': target_id})
        else:
            actions.append({'action': 'unknown', 'reason': 'Цель не указана'})
        return actions
    if any(w in cleaned for w in ['патруль', 'охрана', 'патрулировать']):
        actions.append({'action': 'walk', 'value': 3})
        actions.append({'action': 'turn_left', 'value': 2})
        actions.append({'action': 'walk', 'value': 3})
        actions.append({'action': 'turn_right', 'value': 2})
        return actions
    if 'вперёд' in cleaned or 'вперед' in cleaned:
        actions.append({'action': 'walk', 'value': multiplier})
    elif 'назад' in cleaned:
        actions.append({'action': 'walk_backward', 'value': multiplier})
    elif 'налево' in cleaned or 'влево' in cleaned:
        actions.append({'action': 'turn_left', 'value': multiplier})
    elif 'направо' in cleaned or 'вправо' in cleaned:
        actions.append({'action': 'turn_right', 'value': multiplier})
    else:
        actions.append({'action': 'unknown', 'reason': 'неизвестная команда'})
    return actions

def parse_command_to_actions(text):
    text_lower = text.strip()
    if not text_lower:
        return [{'action': 'unknown', 'reason': 'пустая команда'}]
    cleaned = text_lower
    for phrase in ['красная команда', 'синяя команда', 'зелёная команда', 'жёлтая команда',
                   'красные', 'синие', 'зелёные', 'жёлтые',
                   'красной команде', 'синей команде', 'зелёной команде', 'жёлтой команде']:
        if cleaned.startswith(phrase):
            cleaned = cleaned[len(phrase):].strip(', ')
            break
    parts = [p.strip() for p in cleaned.split(',') if p.strip()]
    if not parts:
        return [{'action': 'unknown', 'reason': 'пустая команда'}]
    all_actions = []
    for part in parts:
        all_actions.extend(parse_single_command(part))
    return all_actions

# ---------- Вспомогательные функции ----------
def find_leader_position(team):
    if team and team_leaders.get(team):
        leader_id = team_leaders[team]
        if leader_id in robots_positions:
            return robots_positions[leader_id].copy()
    return None

def calculate_defend_positions(leader_pos, team_color):
    leader_id = team_leaders.get(team_color)
    team_members = [rid for rid, t in robots_team.items() if t == team_color and rid != leader_id and robots_health.get(rid, 0) > 0]
    count = len(team_members)
    if count == 0:
        return []
    positions = []
    if count == 1:
        positions.append({'robot_id': team_members[0], 'x': leader_pos['x'] - 3, 'z': leader_pos['z'] - 3})
    elif count == 2:
        positions.append({'robot_id': team_members[0], 'x': leader_pos['x'] - 5, 'z': leader_pos['z']})
        positions.append({'robot_id': team_members[1], 'x': leader_pos['x'] + 5, 'z': leader_pos['z']})
    elif count == 3:
        radius = 5
        angles = [0, 2*math.pi/3, 4*math.pi/3]
        for i, rid in enumerate(team_members):
            x = leader_pos['x'] + radius * math.cos(angles[i])
            z = leader_pos['z'] + radius * math.sin(angles[i])
            positions.append({'robot_id': rid, 'x': x, 'z': z})
    elif count == 4:
        radius = 5
        angles = [math.pi/4, 3*math.pi/4, 5*math.pi/4, 7*math.pi/4]
        for i, rid in enumerate(team_members):
            x = leader_pos['x'] + radius * math.cos(angles[i])
            z = leader_pos['z'] + radius * math.sin(angles[i])
            positions.append({'robot_id': rid, 'x': x, 'z': z})
    else:
        radius = 5
        for i, rid in enumerate(team_members):
            angle = 2 * math.pi * i / count
            x = leader_pos['x'] + radius * math.cos(angle)
            z = leader_pos['z'] + radius * math.sin(angle)
            positions.append({'robot_id': rid, 'x': x, 'z': z})
    return positions

def calculate_formation_positions(center_pos, team_color, formation='line', radius=5.5):
    leader_id = team_leaders.get(team_color)
    team_members = [rid for rid, t in robots_team.items() if t == team_color and rid != leader_id and robots_health.get(rid, 0) > 0]
    if not team_members:
        return []
    positions = []
    count = len(team_members)
    if formation == 'line':
        offset = 2.0
        for i, rid in enumerate(team_members):
            x = center_pos['x'] + (i - count/2 + 0.5) * offset
            z = center_pos['z'] + 3.0
            positions.append({'robot_id': rid, 'x': x, 'z': z})
    elif formation == 'circle':
        for i, rid in enumerate(team_members):
            angle = 2 * math.pi * i / count
            x = center_pos['x'] + radius * math.cos(angle)
            z = center_pos['z'] + radius * math.sin(angle)
            positions.append({'robot_id': rid, 'x': x, 'z': z})
    return positions

# ---------- Выполнение действий ----------
def execute_actions(robot_id, actions):
    for act in actions:
        action = act.get('action', 'unknown')
        if action == 'unknown':
            reason = act.get('reason', '')
            with data_lock:
                team = robots_team.get(robot_id)
            socketio.emit('robot_response', {'text': f'🤖 Не удалось выполнить: {reason or "команда не распознана"}', 'team': team})
            continue
        value = act.get('value', 1)
        target_team = act.get('target_team')
        point_num = act.get('point')
        target_id = act.get('target')

        with data_lock:
            if robot_id not in robots_health or robots_health[robot_id] <= 0:
                team = robots_team.get(robot_id)
                socketio.emit('robot_response', {'text': '🤖 Робот уничтожен.', 'team': team})
                return
            socketio.emit('robot_animate', {
                'robot_id': robot_id,
                'action': action,
                'value': value,
                'target': target_id
            })

        time.sleep(0.6 * value)

        with data_lock:
            if robot_id not in robots_health or robots_health[robot_id] <= 0:
                return
            team = robots_team.get(robot_id)

            if action == 'sit' or action == 'stand':
                pass
            elif action == 'follow_leader':
                if not team:
                    socketio.emit('robot_response', {'text': '🤖 Робот не в команде.', 'team': team})
                    continue
                leader_pos = find_leader_position(team)
                if not leader_pos:
                    socketio.emit('robot_response', {'text': '🤖 Лидер не найден.', 'team': team})
                    continuesocketio.emit('move_to', {
                    'robot_id': robot_id,
                    'target': {'x': leader_pos['x'], 'y': 1.5, 'z': leader_pos['z']},
                    'minDistance': 5.0
                })
            elif action == 'assault_point':
                if not team:
                    socketio.emit('robot_response', {'text': '🤖 Робот не в команде.', 'team': team})
                    continue
                if team_leaders.get(team) != robot_id:
                    socketio.emit('robot_response', {'text': '🤖 Только лидер может отдавать приказ на штурм.', 'team': team})
                    continue
                if point_num not in capture_points:
                    socketio.emit('robot_response', {'text': '🤖 Точка не существует.', 'team': team})
                    continue
                pt = capture_points[point_num]
                if pt['captured_by'] == team:
                    socketio.emit('robot_response', {'text': f'🤖 Точка {point_num} уже принадлежит команде {team}.', 'team': team})
                    continue

                defender_team = pt['captured_by']
                attackers = [rid for rid, t in robots_team.items() if t == team and robots_health.get(rid, 0) > 0]
                defenders = [rid for rid, t in robots_team.items() if t == defender_team and robots_health.get(rid, 0) > 0] if defender_team else []

                scouts = [rid for rid in attackers if rid != robot_id]
                if not scouts:
                    socketio.emit('robot_response', {'text': '🤖 Нет других роботов для разведки.', 'team': team})
                    continue
                scout_id = scouts[0]
                angle = random.uniform(0, 2*math.pi)
                scout_x = pt['x'] + 20 * math.cos(angle)
                scout_z = pt['z'] + 20 * math.sin(angle)
                socketio.emit('move_to', {
                    'robot_id': scout_id,
                    'target': {'x': scout_x, 'y': 1.5, 'z': scout_z},
                    'minDistance': 1.0
                })
                socketio.emit('scout_assigned', {'robot_id': scout_id})
                time.sleep(3)

                with data_lock:
                    attacker_count = len(attackers)
                    defender_count = len(defenders)
                    base = 50 + (attacker_count - defender_count) * 10
                    probability = max(5, min(95, base))
                    probability += random.randint(-10, 10)
                    probability = max(5, min(95, probability))

                    battle_states[point_num] = {
                        'attacker_team': team,
                        'defender_team': defender_team,
                        'state': 'waiting_decision',
                        'attacker_count': attacker_count,
                        'defender_count': defender_count,
                        'probability': probability
                    }
                    socketio.emit('assault_decision', {
                        'team': team,
                        'point': point_num,
                        'probability': probability,
                        'attacker_count': attacker_count,
                        'defender_count': defender_count
                    })
            elif action == 'encircle_point':
                if not team:
                    socketio.emit('robot_response', {'text': '🤖 Робот не в команде.', 'team': team})
                    continue
                if point_num not in capture_points:
                    socketio.emit('robot_response', {'text': '🤖 Точка не существует.', 'team': team})
                    continue
                pt = capture_points[point_num]
                center_pos = {'x': pt['x'], 'z': pt['z']}
                all_members = [rid for rid, t in robots_team.items() if t == team and robots_health.get(rid, 0) > 0]
                count = len(all_members)
                if count > 0:
                    for i,rid in enumerate(all_members):
                        angle = 2 * math.pi * i / count
                        x = center_pos['x'] + 5.5 * math.cos(angle)
                        z = center_pos['z'] + 5.5 * math.sin(angle)
                        socketio.emit('move_to', {
                            'robot_id': rid,
                            'target': {'x': x, 'y': 1.5, 'z': z},
                            'minDistance': 1.0
                        })
                socketio.emit('robot_response', {'text': f'🤖 Команда {team} окружила точку {point_num}. Ожидание команд: "захват" или "отступить".', 'team': team})
            elif action == 'encircle_team':
                if not team:
                    socketio.emit('robot_response', {'text': '🤖 Робот не в команде.', 'team': team})
                    continue
                if not target_team:
                    socketio.emit('robot_response', {'text': '🤖 Укажите цвет команды для окружения.', 'team': team})
                    continue
                enemy_leader_id = team_leaders.get(target_team)
                if not enemy_leader_id or enemy_leader_id not in robots_positions:
                    socketio.emit('robot_response', {'text': '🤖 Лидер вражеской команды не найден.', 'team': team})
                    continue
                enemy_pos = robots_positions[enemy_leader_id]
                center_pos = {'x': enemy_pos['x'], 'z': enemy_pos['z']}
                all_members = [rid for rid, t in robots_team.items() if t == team and robots_health.get(rid, 0) > 0]
                count = len(all_members)
                if count == 0:
                    socketio.emit('robot_response', {'text': '🤖 В вашей команде нет роботов.', 'team': team})
                    continue
                for i, rid in enumerate(all_members):
                    angle = 2 * math.pi * i / count
                    x = center_pos['x'] + 5.5 * math.cos(angle)
                    z = center_pos['z'] + 5.5 * math.sin(angle)
                    socketio.emit('move_to', {
                        'robot_id': rid,
                        'target': {'x': x, 'y': 1.5, 'z': z},
                        'minDistance': 1.0
                    })
                socketio.emit('robot_response', {'text': f'🤖 Команда {team} окружила команду {target_team}. Ожидание команд: "захват" или "отступить".', 'team': team})
            elif action == 'capture':
                captured_any = False
                for pid, pt in capture_points.items():
                    if pt['captured_by'] == team:
                        continue
                    if robot_id in robots_positions:
                        pos = robots_positions[robot_id]
                        dist = math.hypot(pos['x']-pt['x'], pos['z']-pt['z'])
                        if dist <= 5.5:
                            start_capture_timer(pid, robot_id)
                            captured_any = True
                            break
                if captured_any:
                    socketio.emit('robot_response', {'text': '🤖 Захват начат.', 'team': team})
                else:
                    socketio.emit('robot_response', {'text': '🤖 Нет точек поблизости для захвата.', 'team': team})
            elif action == 'retreat':
                if not team:
                    socketio.emit('robot_response', {'text': '🤖 Робот не в команде.', 'team': team})
                    continue
                leader_pos = find_leader_position(team)
                if not leader_pos:
                    socketio.emit('robot_response', {'text': '🤖 Лидер не найден.', 'team': team})
                    continue
                all_members = [rid for rid, t in robots_team.items() if t == team and robots_health.get(rid, 0) > 0]
                for rid in all_members:
                    socketio.emit('move_to', {
                        'robot_id': rid,
                        'target': {'x': leader_pos['x'] + random.uniform(-5,5), 'y': 1.5, 'z': leader_pos['z'] + random.uniform(-5,5)},
                        'minDistance': 1.0
                    })
            elif action == 'capture_point':
                if point_num not in capture_points:
                    socketio.emit('robot_response', {'text': '🤖 Точка не существует.', 'team': team})
                    continue
                pt = capture_points[point_num]
                if pt['captured_by'] == team:
                    socketio.emit('robot_response', {'text': f'🤖 Точка {point_num} уже принадлежит команде {team}.', 'team': team})
                    continue
                center_pos = {'x': pt['x'], 'z': pt['z']}
                if team_leaders.get(team) == robot_id:
                    target_pos = {'x': pt['x'], 'y': 1.5, 'z': pt['z']}
                    socketio.emit('move_to', {
                        'robot_id': robot_id,
                        'target': target_pos,
                        'minDistance': 1.0
                    })
                    start_capture_timer(point_num, robot_id)
                else:
                    targets = calculate_formation_positions(center_pos, team, 'circle')
                    for t in targets:
                        if t['robot_id'] == robot_id:
                            socketio.emit('move_to', {
                                'robot_id': robot_id,
                                'target': {'x': t['x'], 'y': 1.5, 'z': t['z']},
                                'minDistance': 1.0
                            })
                            break
            elif action == 'defend_leader':
                if not team:
                    socketio.emit('robot_response', {'text': '🤖 Робот не в команде.', 'team': team})
                    continue
                leader_pos = find_leader_position(team)
                if not leader_pos:
                    socketio.emit('robot_response', {'text': '🤖 Лидер не найден.', 'team': team})
                    continue
                if robot_id in active_defend_tasks:
                    active_defend_tasks[robot_id]['active'] = False
                targets = calculate_defend_positions(leader_pos, team)
                for t in targets:
                    if t['robot_id'] == robot_id:
                        socketio.emit('move_to', {
                            'robot_id': robot_id,
                            'target': {'x': t['x'], 'y': 1.5, 'z': t['z']},
                            'minDistance': 1.0
                        })
                        break
                def follow_leader(rid):
                    active_defend_tasks[rid] = {'active': True}
                    while True:
                        time.sleep(1)
                        with data_lock:
                            if rid not in active_defend_tasks or not active_defend_tasks[rid].get('active'):
                                break
                            if rid not in robots_health or robots_health[rid] <= 0:
                                break
                            team = robots_team.get(rid)
                            if not team:
                                break
                            leader_pos = find_leader_position(team)
                            if not leader_pos:
                                break
                            targets = calculate_defend_positions(leader_pos, team)
                            for t in targets:
                                if t['robot_id'] == rid:
                                    socketio.emit('move_to', {
                                        'robot_id': rid,
                                        'target': {'x': t['x'], 'y': 1.5, 'z': t['z']},
                                        'minDistance': 1.0
                                    })
                                    break
                threading.Thread(target=follow_leader, args=(robot_id,), daemon=True).start()
            elif action == 'goto_leader':
                if not team:
                    socketio.emit('robot_response', {'text': '🤖 Робот не в команде.', 'team': team})
                    continue
                leader_pos = find_leader_position(team)
                if not leader_pos:
                    socketio.emit('robot_response', {'text': '🤖 Лидер не найден.', 'team': team})
                    continue
                # Отправляем всех членов команды к лидеру, включая отправителя
                all_members = [rid for rid, t in robots_team.items() if t == team and robots_health.get(rid, 0) > 0]
                for rid in all_members:
                    if rid == robot_id and team_leaders.get(team) == robot_id:
                        # Если отправитель — лидер, просто выводим сообщение
                        socketio.emit('robot_response', {'text': '🤖 Я уже на месте, я и есть лидер.', 'team': team})
                    else:
                        socketio.emit('move_to', {
                            'robot_id': rid,
                            'target': {'x': leader_pos['x'], 'y': 1.5, 'z': leader_pos['z']},
                            'minDistance': 5.0
                        })
            elif action == 'attack':
                if not target_id or target_id not in robots_health:
                    socketio.emit('robot_response', {'text': '🤖 Цель не указана или не существует.', 'team': team})
                elif target_id == robot_id:
                    socketio.emit('robot_response', {'text': '🤖 Нельзя атаковать самого себя.', 'team': team})
                else:
                    if robots_health[target_id] > 0:
                        damage = random.randint(10, 30)
                        robots_health[target_id] = max(0, robots_health[target_id] - damage)
                        socketio.emit('health_update', {'robot_id': target_id, 'health': robots_health[target_id]})
                        if robots_health[target_id] <= 0:
                            socketio.emit('robot_dead', {'robot_id': target_id, 'team': robots_team.get(target_id)})
            elif action in ('form_line', 'form_circle'):
                if not team:
                    socketio.emit('robot_response', {'text': '🤖 Робот не в команде.', 'team': team})
                    continue
                leader_pos = find_leader_position(team)
                if not leader_pos:
                    socketio.emit('robot_response', {'text': '🤖 Лидер не найден.', 'team': team})
                    continue
                formation = 'line' if action == 'form_line' else 'circle'
                center_pos = {'x': leader_pos['x'], 'z': leader_pos['z']}
                targets = calculate_formation_positions(center_pos, team, formation)
                for t in targets:
                    socketio.emit('move_to', {
                        'robot_id': t['robot_id'],
                        'target': {'x': t['x'], 'y': 1.5, 'z': t['z']},
                        'minDistance': 1.0
                    })
            elif action == 'capture_all_points':
                if not team:
                    socketio.emit('robot_response', {'text': '🤖 Робот не в команде.', 'team': team})
                    continue
                members = [rid for rid, t in robots_team.items() if t == team and robots_health.get(rid, 0) > 0]
                points = list(capture_points.keys())
                for i, rid in enumerate(members):
                    if i < len(points):
                        pt = capture_points[points[i]]
                        socketio.emit('move_to', {
                            'robot_id': rid,
                            'target': {'x': pt['x'], 'y': 1.5, 'z': pt['z']},
                            'minDistance': 1.0
                        })
                        if rid == robot_id:
                            start_capture_timer(points[i], rid)
                socketio.emit('robot_response', {'text': '🤖 Захват всех точек инициирован.', 'team': team})
            elif action == 'capture_leader':socketio.emit('robot_response', {'text': f'🤖 Операция "Захват лидера {target_team}" (заглушка).', 'team': team})
            elif action == 'attack_team':
                socketio.emit('robot_response', {'text': f'🤖 Атака на команду {target_team} (заглушка).', 'team': team})
            elif action == 'assault':
                socketio.emit('robot_response', {'text': '🤖 Штурмовая операция (заглушка).', 'team': team})

# ---------- Обработчик команд ----------
@socketio.on('robot_command')
def handle_robot_command(data):
    robot_id = data.get('robot_id')
    robot_type = data.get('robot_type', 'неизвестный')
    command = data.get('command')
    if not robot_id or not command:
        with data_lock:
            team = robots_team.get(robot_id)
        emit('robot_response', {'text': 'Ошибка', 'team': team})
        return
    actions = parse_command_to_actions(command)
    if not actions or all(a.get('action') == 'unknown' for a in actions):
        with data_lock:
            team = robots_team.get(robot_id)
        emit('robot_response', {'text': f'🤖 Команда не распознана: {command}', 'team': team})
        return
    logger.info(f"[{robot_id}] Выполняю: {command} -> {actions}")
    threading.Thread(target=execute_actions, args=(robot_id, actions)).start()

# ---------- Решение о штурме ----------
@socketio.on('assault_decision_response')
def handle_assault_decision_response(data):
    team = data.get('team')
    point = data.get('point')
    decision = data.get('decision')
    with data_lock:
        if point not in battle_states:
            return
        state = battle_states[point]
        if state['attacker_team'] != team:
            return
        if decision == 'attack':
            state['state'] = 'assault'
            leader_id = team_leaders.get(team)
            if leader_id:
                socketio.emit('move_to', {
                    'robot_id': leader_id,
                    'target': {'x': capture_points[point]['x'], 'y': 1.5, 'z': capture_points[point]['z']},
                    'minDistance': 1.0
                })
                center_pos = {'x': capture_points[point]['x'], 'z': capture_points[point]['z']}
                members = [rid for rid, t in robots_team.items() if t == team and robots_health.get(rid, 0) > 0 and rid != leader_id]
                count = len(members)
                if count > 0:
                    radius = 5.5
                    for i, rid in enumerate(members):
                        angle = 2 * math.pi * i / count
                        x = center_pos['x'] + radius * math.cos(angle)
                        z = center_pos['z'] + radius * math.sin(angle)
                        socketio.emit('move_to', {
                            'robot_id': rid,
                            'target': {'x': x, 'y': 1.5, 'z': z},
                            'minDistance': 1.0
                        })
                start_capture_timer(point, leader_id)
            socketio.emit('robot_response', {'text': f'🤖 Команда {team} начала штурм точки {point}.', 'team': team})
            del battle_states[point]
        elif decision == 'retreat':
            state['state'] = 'retreat'
            leader_id = team_leaders.get(team)
            if leader_id:
                leader_pos = robots_positions.get(leader_id)
                if leader_pos:
                    members = [rid for rid, t in robots_team.items() if t == team and robots_health.get(rid, 0) > 0]
                    for rid in members:
                        socketio.emit('move_to', {
                            'robot_id': rid,
                            'target': {'x': leader_pos['x'] + random.uniform(-5,5), 'y': 1.5, 'z': leader_pos['z'] + random.uniform(-5,5)},
                            'minDistance': 1.0
                        })
            socketio.emit('robot_response', {'text': f'🤖 Команда {team} отступила от точки {point}.', 'team': team})
            del battle_states[point]

# ---------- Прямые команды----------
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
        resp = send_to_core({"skill": skill, "text": json.dumps(payload)})
        emit('assistant_message', {'text': f"[{skill}]: {resp['text']}"})
    except Exception:
        emit('assistant_message', {'text': 'Ошибка связи с ядром'})

# ---------- Обработчики команд 3D-принтера ----------
@socketio.on('printer_connect')
def handle_printer_connect(data):
    printer_type = data.get('printer_type', 'unknown')
    address = data.get('address', None)
    # Отправляем команду в printer_skill через send_to_core (если ядро поддерживает)
    # В вашей архитектуре лучше напрямую вызвать функцию из printer_skill, если она доступна.
    # Для простоты используем прямую отправку в ядро:
    try:
        result = send_to_core({"skill": "printer_skill", "text": json.dumps({"command": "connect", "params": {"printer_type": printer_type, "address": address}})})
        text = result.get('text', 'Подключение выполнено')
    except Exception as e:
        text = f'Ошибка подключения: {e}'
    socketio.emit('printer_log', {'text': text})
    socketio.emit('printer_status', {'status': 'connected', 'progress': 0})

@socketio.on('printer_start')
def handle_printer_start():
    try:
        result = send_to_core({"skill": "printer_skill", "text": json.dumps({"command": "start"})})
        text = result.get('text', 'Печать запущена')
    except Exception as e:
        text = f'Ошибка запуска: {e}'
    socketio.emit('printer_log', {'text': text})

@socketio.on('printer_stop')
def handle_printer_stop():
    try:
        result = send_to_core({"skill": "printer_skill", "text": json.dumps({"command": "stop"})})
        text = result.get('text', 'Печать остановлена')
    except Exception as e:
        text = f'Ошибка остановки: {e}'
    socketio.emit('printer_log', {'text': text})

@socketio.on('printer_pause')
def handle_printer_pause():
    try:
        result = send_to_core({"skill": "printer_skill", "text": json.dumps({"command": "pause"})})
        text = result.get('text', 'Печать приостановлена')
    except Exception as e:
        text = f'Ошибка паузы: {e}'
    socketio.emit('printer_log', {'text': text})

@socketio.on('printer_resume')
def handle_printer_resume():
    try:
        result = send_to_core({"skill": "printer_skill", "text": json.dumps({"command": "resume"})})
        text = result.get('text', 'Печать возобновлена')
    except Exception as e:
        text = f'Ошибка возобновления: {e}'
    socketio.emit('printer_log', {'text': text})

@socketio.on('printer_clear_bed')
def handle_printer_clear_bed():
    try:
        result = send_to_core({"skill": "printer_skill", "text": json.dumps({"command": "clear"})})
        text = result.get('text', 'Стол очищен')
    except Exception as e:
        text = f'Ошибка очистки: {e}'
    socketio.emit('printer_log', {'text': text})
    socketio.emit('printer_clear_bed_response', {})  # для очистки сцены

@socketio.on('printer_load_model')
def handle_printer_load_model(data):
    model_name = data.get('model_name', '')
    try:
        result = send_to_core({"skill": "printer_skill", "text": json.dumps({"command": "load_model", "params": {"model_name": model_name}})})
        text = result.get('text', 'Модель загружена')
    except Exception as e:
        text = f'Ошибка загрузки: {e}'
    socketio.emit('printer_log', {'text': text})

@socketio.on('printer_slice')
def handle_printer_slice(data):
    settings = data.get('settings', {})
    try:
        result = send_to_core({"skill": "printer_skill", "text": json.dumps({"command": "slice", "params": {"settings": settings}})})
        text = result.get('text', 'Слайсинг завершён')
    except Exception as e:
        text = f'Ошибка слайсинга: {e}'
    socketio.emit('printer_log', {'text': text})

@socketio.on('printer_disconnect')
def handle_printer_disconnect():
    try:
        result = send_to_core({"skill": "printer_skill", "text": json.dumps({"command": "disconnect"})})
        text = result.get('text', 'Принтер отключён')
    except Exception as e:
        text = f'Ошибка отключения: {e}'
    socketio.emit('printer_log', {'text': text})
    socketio.emit('printer_status', {'status': 'disconnected'})

# ---------- Ответы от ядра можно транслировать клиенту ----------
# Добавьте в соответствующие места отправку событий 'printer_log' и 'printer_@socket.tatus'

if __name__ == '__main__':
    print("Веб-сервер Урфина: http://localhost:5000")
    socketio.run(app, host='127.0.0.1', port=5000)