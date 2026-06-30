import os
import subprocess
import json
import logging
import shutil
from pathlib import Path

logger = logging.getLogger("slicer_skill")
logger.setLevel(logging.DEBUG)
if not logger.handlers:
    fh = logging.FileHandler('/tmp/slicer_skill.log', encoding='utf-8')
    fh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(fh)

# Папки
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "output")
GCODE_DIR = os.path.join(os.path.dirname(__file__), "..", "gcode")
os.makedirs(GCODE_DIR, exist_ok=True)

# Путь к слайсеру (можно переопределить через .env)
SLICER_PATH = os.getenv("UORFIN_SLICER_PATH", "prusa-slicer")

def init(name):
    print(f"Слайсер '{name}' инициализирован")
    if not shutil.which(SLICER_PATH):
        print(f"⚠ Слайсер не найден: {SLICER_PATH}. Установите его или пропишите путь в UORFIN_SLICER_PATH.")

def handle_message(message):
    try:
        msg = json.loads(message)
    except:
        return "Ошибка: ожидается JSON"

    command = msg.get("command", "")
    if command == "slice":
        filename = msg.get("filename", "")
        if not filename:
            return "Ошибка: не указан файл для слайсинга"
        stl_path = os.path.join(OUTPUT_DIR, filename)
        if not os.path.exists(stl_path):
            return f"Ошибка: файл {filename} не найден в output/"
        # Имя выходного G-code
        gcode_filename = Path(filename).stem + ".gcode"
        gcode_path = os.path.join(GCODE_DIR, gcode_filename)
        # Формируем команду
        cmd = [SLICER_PATH, "--export-gcode", "--output", gcode_path, stl_path]
        logger.debug(f"Запуск: {' '.join(cmd)}")
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=30)
        except subprocess.CalledProcessError as e:
            logger.error(f"Ошибка слайсера: {e.stderr}")
            return f"Ошибка слайсера: {e.stderr.strip()}"
        except subprocess.TimeoutExpired:
            return "Слайсинг занял слишком много времени"
        return json.dumps({"status": "ok", "gcode_file": gcode_filename})
    elif command == "status":
        if shutil.which(SLICER_PATH):
            return f"Слайсер готов: {SLICER_PATH}"
        else:
            return f"Слайсер не найден: {SLICER_PATH}"
    else:
        return "Неизвестная команда слайсера"

def shutdown(name=None):
    print("Слайсер выгружен")