import json
import threading

MAX_RECENT = 10
memory = []
summary = ""
lock = threading.Lock()

def init(name):
    print(f"Память '{name}' инициализирована")

def add_message(role, text):
    if len(text) > 2000:
        text = text[:2000] + "..."
    with lock:
        memory.append({"role": role, "text": text})
        total_len = sum(len(m["text"]) for m in memory)
        while total_len > 10000:
            removed = memory.pop(0)
            total_len -= len(removed["text"])
        while len(memory) > MAX_RECENT:
            memory.pop(0)

def get_context():
    with lock:
        parts = []
        if summary:
            parts.append(f"[Сжатая история]: {summary}")
        for msg in memory:
            prefix = "Человек" if msg["role"] == "user" else "Урфин"
            parts.append(f"{prefix}: {msg['text']}")
        return "\n".join(parts)

def clear():
    global memory, summary
    with lock:
        memory = []
        summary = ""
    return "Память очищена"

def handle_message(message):
    # Попытка разобрать JSON
    cmd = None
    try:
        data = json.loads(message)
        if isinstance(data, dict) and "command" in data:
            cmd = data["command"].strip()
    except:
        # не JSON — используем строку как есть
        cmd = message.strip()

    # Команды
    if cmd == "/clear":
        return clear()
    if cmd == "/get_context":
        return get_context()
    if message.startswith("add|"):
        parts = message.split("|", 2)
        if len(parts) == 3:
            role, text = parts[1], parts[2]
            if role not in ("user", "assistant", "system"):
                return "Ошибка: недопустимая роль"
            add_message(role, text)
            return "Записано"
        return "Ошибка: неверный формат add"

    return "неизвестная команда"

def shutdown(name=None):
    print("Память выгружена")