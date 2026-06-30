import json, time, sys, os, re, logging

# Безопасный импорт адаптера
try:
    sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'core'))
    from openrouter_adapter import adapter
except ImportError:
    adapter = None

logger = logging.getLogger(__name__)

def plan(goal_text):
    """
    Строит план действий на основе текстовой цели.
    Возвращает список строк-команд, совместимых с execute_plan в web_server.py.
    Формат команд: действие_параметр (например, 'goto_point_2') или действие_число ('walk_3').
    """
    goal_lower = goal_text.lower()

    # ---------- 1. Простые правила ----------
    # Захват точки
    m = re.search(r'захватить\s+точку\s+(\d)', goal_lower)
    if m:
        point = int(m.group(1))
        return [f'goto_point_{point}', 'sit']

    # Охрана / патрулирование
    if any(w in goal_lower for w in ['охранять', 'патрулировать', 'патруль']):
        return ['walk_3', 'turn_left_2', 'walk_3', 'turn_right_2']

    # Атака (временно без реализации attack, просто подойти)
    if any(w in goal_lower for w in ['атаковать', 'уничтожить', 'штурм']):
        # Извлекаем цель, если указана
        target = None
        m = re.search(r'атаковать\s+(\S+)', goal_lower)
        if m:
            target = m.group(1)
        # Пока только идём вперёд, attack будет проигнорирован сервером
        return ['walk_5'] if not target else [f'walk_5']  # можно добавить target, но сервер не поддерживает

    # Подойти к лидеру (с цветом или без)
    target_team = None
    for color_ru, color_en in {
        'синий':'blue','синяя':'blue','синие':'blue',
        'красный':'red','красная':'red','красные':'red',
        'жёлтый':'yellow','жёлтая':'yellow','жёлтые':'yellow',
        'зелёный':'green','зелёная':'green','зелёные':'green'
    }.items():
        if f'лидеру {color_ru}' in goal_lower or f'к лидеру {color_ru}' in goal_lower:
            target_team = color_en
            break
    if 'к лидеру' in goal_lower:
        if target_team:
            return [f'goto_leader_{target_team}']   # сервер распарсит как action='goto_leader', target=target_team
        else:
            return ['goto_leader']

    # Явные движения
    m = re.search(r'(\d+)\s*(шагов|шага|шаг)\s*(вперёд|вперед)', goal_lower)
    if m:
        value = int(m.group(1))
        return [f'walk_{value}']
    m = re.search(r'(\d+)\s*(шагов|шага|шаг)\s*(назад)', goal_lower)
    if m:
        value = int(m.group(1))
        return [f'walk_backward_{value}']
    if 'поворот налево' in goal_lower or 'повернуть налево' in goal_lower:
        return ['turn_left_1']
    if 'поворот направо' in goal_lower or 'повернуть направо' in goal_lower:
        return ['turn_right_1']
    if 'сесть' in goal_lower:
        return ['sit']
    if 'встать' in goal_lower:
        return ['stand']

    # ---------- 2. LLM (если доступен) ----------
    if adapter and getattr(adapter, 'configured', False):
        system_prompt = (
            "Ты — планировщик роботов. Получив цель на русском языке, "
            "верни ТОЛЬКО JSON-массив строк с командами. "
            "Доступные команды: walk_N (N шагов вперёд), walk_backward_N, "
            "turn_left_N (поворот налево на N*30°), turn_right_N, "
            "goto_point_N (идти к точке N), goto_leader (к лидеру, опционально с цветом: goto_leader_red), "
            "sit, stand. Команда attack временно недоступна. "
            "Каждая строка должна быть в формате 'действие_параметр' или 'действие'. "
            "Используй СТРОГО двойные кавычки для JSON. "
            "Пример: [\"walk_3\", \"turn_left_2\", \"goto_point_1\", \"sit\"]. "
            "Не добавляй пояснений."
        )
        try:
            response = adapter.query(goal_text, system_prompt=system_prompt, temperature=0.2)
            if not response:
                return ["План не найден"]

            # Извлекаем массив строк
            # Ищем что-то похожее на JSON-массив
            match = re.search(r'\[(?:[^\[\]]*)\](?=\s*$|\n)', response, re.DOTALL)
            json_str = match.group(0) if match else response.strip()

            # Заменяем одинарные кавычки на двойные (если они не внутри строк)
            if json_str.startswith('['):
                # Простая эвристика: если вся строка в одинарных кавычках, меняем
                if json_str.count('"') < 2 and "'" in json_str:
                    json_str = json_str.replace("'", '"')
                try:
                    plan_result = json.loads(json_str)
                    if isinstance(plan_result, list) and all(isinstance(s, str) for s in plan_result):
                        return plan_result
                except json.JSONDecodeError:
                    logger.error(f"Некорректный JSON от LLM: {json_str}")
            return ["План не найден"]
        except Exception as e:
            logger.error(f"Ошибка при LLM-планировании: {e}")

    return ["План не найден"]

def init(name):
    logger.info(f"Плагин '{name}' (GOAP) инициализирован")

def handle_message(message):
    """Обработчик прямых команд ядра."""
    try:
        msg = json.loads(message)
    except:
        return "Ошибка JSON"
    cmd = msg.get("command", "")
    if cmd == "execute_goal":
        goal = msg.get("goal", "")
        plan_result = plan(goal)
        return json.dumps({"plan": plan_result})
    elif cmd == "status":
        return "GOAP-мозжечок активен."
    return "Неизвестная команда GOAP"

def shutdown(name=None):
    logger.info("GOAP-мозжечок выгружен")