import json
import os
import subprocess
import re
import sys
import time

sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'core'))
from openrouter_adapter import adapter

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

def generate_openscad_code(prompt: str) -> str | None:
    """
    Просит LLM создать код OpenSCAD по текстовому описанию.
    Возвращает строку с кодом или None при ошибке.
    """
    system_prompt = (
        "Ты — инженер-конструктор, работающий в OpenSCAD. "
        "Пользователь описывает 3D-модель на естественном языке. "
        "Создай корректный код OpenSCAD (только код, без пояснений), который создаёт эту модель. "
        "Используй модули, если необходимо. "
        "Размеры указывай в миллиметрах. Если пользователь указал сантиметры, переведи в мм. "
        "Для резьбы используй модуль thread, например: module thread() { ... }. "
        "Для полых объектов используй difference() { внешний_объект(); внутренний_объект(); }. "
        "Код должен быть готов для рендеринга. Ответ должен содержать ТОЛЬКО код OpenSCAD."
    )
    try:
        response = adapter.query(prompt, system_prompt=system_prompt, temperature=0.2)
        # Очищаем возможные обрамления markdown
        code = re.sub(r'```(?:openscad|scad)?\s*', '', response)
        code = re.sub(r'```\s*$', '', code)
        return code.strip()
    except Exception as e:
        print(f"LLM error: {e}")
        return None

def render_stl(scad_code: str, stl_filename: str) -> bool:
    """
    Сохраняет код во временный .scad файл и вызывает openscad для рендеринга STL.
    Возвращает True при успехе.
    """
    scad_path = os.path.join(OUTPUT_DIR, "temp.scad")
    stl_path = os.path.join(OUTPUT_DIR, stl_filename)
    try:
        with open(scad_path, 'w', encoding='utf-8') as f:
            f.write(scad_code)
        cmd = ["openscad", "-o", stl_path, scad_path]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            print(f"OpenSCAD error: {result.stderr}")
            return False
        return True
    except Exception as e:
        print(f"Render error: {e}")
        return False

def init(name):
    print(f"[PicoGK] Плагин '{name}' инициализирован (OpenSCAD backend)")
    if adapter is None or not adapter.configured:
        print("⚠ LLM не настроен – генерация сложных моделей будет недоступна")

def handle_message(message):
    try:
        msg = json.loads(message)
    except:
        return "Ошибка: ожидается JSON"
    cmd = msg.get("command", "")
    if cmd == "generate":
        prompt = msg.get("prompt", "").strip()
        if not prompt:
            return "Ошибка: пустой промпт"

        # 1. Получаем код OpenSCAD от LLM
        if adapter and adapter.configured:
            scad_code = generate_openscad_code(prompt)
        else:
            return "LLM не настроен – не могу обработать сложный запрос"

        if not scad_code:
            return "Не удалось сгенерировать код OpenSCAD"

        # 2. Рендерим STL
        filename = f"gen_{abs(hash(prompt))}.stl"
        success = render_stl(scad_code, filename)
        if success:
            return json.dumps({"status": "ok", "filename": filename})
        else:
            return "Ошибка рендеринга OpenSCAD. Проверьте установку или сложность модели."

    elif cmd == "status":
        return "PicoGK (OpenSCAD backend v4) активен."
    else:
        return f"Неизвестная команда: {cmd}"

def shutdown(name=None):
    print("PicoGK выгружен")