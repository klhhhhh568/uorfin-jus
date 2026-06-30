import json, sys, os
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'core'))
from openrouter_adapter import adapter

def init(name):
    print(f"Двухполушарный ИИ '{name}' готов")

def handle_message(message):
    try:
        msg = json.loads(message)
    except:
        return "Ошибка: ожидается JSON с командой."
    if msg.get("command") == "process_task":
        task = msg.get("task", "")
        if not task:
            return "Ошибка: пустая задача"
        if adapter is None or not adapter.configured:
            return "Ошибка: OpenRouter не настроен"
        try:
            code = adapter.query(
                f"Ты — инженер-разработчик. Напиши решение для задачи: {task}",
                temperature=0.3
            )
            review = adapter.query(
                f"Ты — критик. Проверь решение: {code}\nЗадача: {task}\nНайди ошибки, если всё ок — напиши 'OK'.",
                temperature=0.1
            )
            if "OK" in review.upper():
                return f"✅ Решение принято:\n{code}"
            else:
                return f"⚠️ Замечания:\n{review}\n\nИсходный код:\n{code}"
        except Exception as e:
            return f"Ошибка при запросе к LLM: {str(e)}"
    return "Неизвестная команда dual_hemisphere."

def analyze(task):
    """Прямой вызов для веб-сервера"""
    payload = json.dumps({"command": "process_task", "task": task})
    return handle_message(payload)

def shutdown(name=None):
    print("Двухполушарный ИИ выгружен")