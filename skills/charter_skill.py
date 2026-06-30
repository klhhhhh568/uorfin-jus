import yaml
import os

RULES = None

def init(name):
    global RULES
    path = os.path.join(os.path.dirname(__file__), "..", "uorfin_charter.yaml")
    with open(path, "r", encoding="utf-8") as f:
        RULES = yaml.safe_load(f)
    print(f"Устав загружен. Запретов: {len(RULES['forbidden_actions'])}")

def handle_message(action_text):
    for forbidden in RULES["forbidden_actions"]:
        if forbidden in action_text.lower():
            return f"запрещено: '{forbidden}'"
    return "разрешено"

def shutdown(name=None):
    print("Устав выгружен")