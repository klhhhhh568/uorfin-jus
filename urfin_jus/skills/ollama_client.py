import requests
import logging
import json

logger = logging.getLogger(__name__)

class OllamaClient:
    def __init__(self, base_url="http://localhost:11434", model="deepseek-r1:1.5b"):
        self.base_url = base_url
        self.model = model

    def is_available(self):
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=3)
            return response.status_code == 200
        except Exception:
            return False

    def ask(self, prompt, system_prompt=None):
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt or ""},
                {"role": "user", "content": prompt}
            ],
            "stream": False
        }
        try:
            response = requests.post(url, json=payload, timeout=60)
            response.raise_for_status()
            return response.json()["message"]["content"]
        except Exception as e:
            logger.error(f"Ollama error: {e}")
            return f"Ошибка: {e}"

# Глобальный экземпляр для использования в качестве навыка
_ollama_client = None

def init(name: str):
    """Инициализация навыка."""
    global _ollama_client
    _ollama_client = OllamaClient()
    logger.info(f"OllamaClient инициализирован как {name}")

def handle_message(message: str) -> str:
    """
    Обработчик сообщений для совместимости с оркестратором.
    Возвращает JSON-ответ.
    """
    if _ollama_client is None:
        return json.dumps({"error": "Навык не инициализирован"})
    try:
        data = json.loads(message)
        command = data.get("command")
        if command == "ask":
            prompt = data.get("params", {}).get("prompt", "")
            system_prompt = data.get("params", {}).get("system_prompt", None)
            if not prompt:
                return json.dumps({"error": "Нет промпта"})
            answer = _ollama_client.ask(prompt, system_prompt)
            return json.dumps({"status": "ok", "response": answer})
        else:
            return json.dumps({"error": f"Неизвестная команда: {command}"})
    except Exception as e:
        return json.dumps({"error": str(e)})

def shutdown():
    """Завершение работы навыка."""
    global _ollama_client
    _ollama_client = None
    logger.info("OllamaClient выгружен")