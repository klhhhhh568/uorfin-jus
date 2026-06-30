import sys, os
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'core'))
from openrouter_adapter import adapter

def init(name):
    print(f"LLM-плагин '{name}' готов")

def handle_message(prompt):
    if adapter is None:
        return "Ошибка: LLM не настроен"
    return adapter.query(prompt, temperature=0.7)

def shutdown(name=None):
    print("LLM-плагин выгружен")