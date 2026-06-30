import json
import threading
import time
import logging

logger = logging.getLogger(__name__)

state = {
    "status": "idle",          # idle, printing, paused, error
    "progress": 0.0,
    "temperature": 0,
    "bed_temp": 0,
    "model_name": "",
    "gcode": [],
    "current_layer": 0,
    "total_layers": 0,
    "print_time_elapsed": 0,
    "print_time_remaining": 0,
    "connection": None         # объект подключения (например, сокет или serial)
}
state_lock = threading.Lock()
_connection_thread = None
_connection_lock = threading.Lock()

# ------ Подключение к принтеру (заглушки для примера) ------
def connect_printer(printer_type, address=None):
    """Подключается к принтеру. Возвращает строку с результатом."""
    with state_lock:
        if state["connection"] is not None:
            return "❌ Принтер уже подключён."
        # Здесь реально реализовать подключение (например, через OctoPrint API или serial)
        # Для заглушки просто имитируем подключение
        state["connection"] = {"type": printer_type, "address": address or "localhost"}
        state["status"] = "idle"
    logger.info(f"Подключено к {printer_type} на {address}")
    return f"✅ Подключено к {printer_type} (адрес: {address or 'локальный'})"

def disconnect_printer():
    with state_lock:
        state["connection"] = None
        state["status"] = "idle"
    logger.info("Принтер отключён")
    return "🔌 Принтер отключён."

def get_status():
    with state_lock:
        s = state.copy()
    return f"Статус: {s['status']}\nПрогресс: {s['progress']:.1f}%\nТемпература: {s['temperature']}°C\nСтол: {s['bed_temp']}°C"

# ------ Загрузка модели и слайсинг (если слайсер на сервере) ------
def load_model(model_filename, model_data=None):
    """Загружает модель для печати."""
    with state_lock:
        state["model_name"] = model_filename
        state["progress"] = 0.0
        state["status"] = "idle"
        state["gcode"] = []   # здесь можно сгенерировать G-код или загрузить из файла
    return f"📦 Модель {model_filename} загружена."

def slice_model(settings):
    """Выполняет слайсинг модели (заглушка)"""
    # Реально можно вызвать внешний слайсер (CuraEngine, Slic3r) через subprocess
    with state_lock:
        state["gcode"] = ["G28", "G1 Z10 F1000", "G1 X0 Y0 F3000", "G1 X100 Y100 F3000"] # пример
        state["total_layers"] = 100
        state["status"] = "idle"
    return "✅ Слайсинг завершён. G-код готов."

# ------ Управление печатью ------
def start_print():
    with state_lock:
        if state["status"] != "idle":
            return "❌ Принтер не готов (занят)."
        if not state["gcode"]:
            return "❌ Нет G-кода для печати. Сначала выполните слайсинг."
        state["status"] = "printing"
        state["progress"] = 0.0
    # Здесь запустить поток отправки G-кода на принтер
    threading.Thread(target=_print_worker, daemon=True).start()
    return "▶️ Печать запущена."

def stop_print():
    with state_lock:
        if state["status"] not in ("printing", "paused"):
            return "❌ Печать не активна."
        state["status"] = "idle"
        state["progress"] = 0.0
    return "⏹️ Печать остановлена."

def pause_print():
    with state_lock:
        if state["status"] != "printing":
            return "❌ Печать не активна."
        state["status"] = "paused"
    return "⏸️ Печать приостановлена."

def resume_print():
    with state_lock:
        if state["status"] != "paused":
            return "❌ Печать не на паузе."
        state["status"] = "printing"
    return "▶️ Печать возобновлена."

def _print_worker():
    """Фоновый поток, имитирующий отправку G-кода."""
    gcode = []
    with state_lock:
        gcode = state["gcode"].copy()
        total = len(gcode)
    for i, line in enumerate(gcode):
        with state_lock:
            if state["status"] != "printing":
                break
            state["progress"] = (i / total) * 100
            state["current_layer"] = i // 10  # пример
            state["print_time_elapsed"] += 1  # секунда
        # Здесь реальная отправка команды на принтер (например, через сокет)
        # ...
        time.sleep(0.5)  # имитация задержки
    with state_lock:
        state["status"] = "idle" if state["status"] == "printing" else state["status"]
        state["progress"] = 100 if state["status"] == "idle" else state["progress"]

# ------ Обработка сообщений из ядра ------
def handle_message(message):
    try:
        msg = json.loads(message)
    except:
        msg = {"command": message.strip()}
    cmd = msg.get("command", "").lower()
    params = msg.get("params", {})
    if cmd == "status":
        return get_status()
    elif cmd == "connect":
        printer_type = params.get("printer_type", "unknown")
        address = params.get("address", None)
        return connect_printer(printer_type, address)
    elif cmd == "disconnect":
        return disconnect_printer()
    elif cmd == "load_model":
        model_name = params.get("model_name", "")
        return load_model(model_name)
    elif cmd == "slice":
        settings = params.get("settings", {})
        return slice_model(settings)
    elif cmd == "start":
        return start_print()
    elif cmd == "stop":
        return stop_print()
    elif cmd == "pause":
        return pause_print()
    elif cmd == "resume":
        return resume_print()
    elif cmd == "clear":
        with state_lock:
            state["gcode"] = []
            state["model_name"] = ""
            state["progress"] = 0
        return "🧹 Стол очищен."
    else:
        return f"Неизвестная команда принтера: {cmd}"

def init(name):
    print(f"Плагин принтера '{name}' инициализирован")

def shutdown(name=None):
    print("Принтер выгружен")