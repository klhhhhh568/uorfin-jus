# core/ollama_adapter.py
import os
import logging
import requests
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

class OllamaAdapter:
    def __init__(self, base_url: Optional[str] = None, model: Optional[str] = None):
        self.base_url = base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self.model = model or os.getenv("OLLAMA_MODEL", "deepseek-r1:1.5b")  # fallback к проверенной модели
        self.configured = True
        logger.info(f"OllamaAdapter инициализирован: модель {self.model}, URL {self.base_url}")
        # Проверим доступность модели при старте
        self._check_model_availability()

    def _check_model_availability(self):
        """Проверяет, существует ли модель в списке доступных."""
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if resp.status_code == 200:
                models = [m["name"] for m in resp.json().get("models", [])]
                if self.model not in models:
                    logger.warning(f"Модель {self.model} не найдена в списке доступных. Доступны: {models}")
                else:
                    logger.info(f"Модель {self.model} подтверждена.")
            else:
                logger.warning("Не удалось получить список моделей от Ollama")
        except Exception as e:
            logger.warning(f"Ошибка проверки доступности моделей: {e}")

    def query(self, prompt: str, system_prompt: Optional[str] = None, temperature: float = 0.2,
              timeout: int = 120) -> str:
        """
        Отправляет запрос к Ollama API и возвращает ответ.
        В случае ошибки возвращает строку с описанием.
        """
        if not prompt:
            return "Ошибка: пустой запрос."

        url = f"{self.base_url}/api/generate"
        payload: Dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "system": system_prompt or "",
            "options": {
                "temperature": temperature,
                "num_predict": 1024,
                "top_p": 0.9,
                "top_k": 40
            },
            "stream": False
        }
        logger.debug(f"Отправка запроса к Ollama: system_prompt={system_prompt[:100]}... prompt={prompt[:100]}...")
        try:
            response = requests.post(url, json=payload, timeout=timeout)
            response.raise_for_status()
            data = response.json()
            answer = data.get("response", "")
            logger.info(f"Ответ от Ollama получен, длина: {len(answer)} символов")
            logger.debug(f"Сырой ответ: {answer[:500]}{'...' if len(answer)>500 else ''}")
            if not answer:
                return "Ошибка: пустой ответ от модели."
            return answer
        except requests.exceptions.ConnectionError:
            logger.error("Не удалось подключиться к Ollama. Проверьте, запущен ли сервер.")
            return "Ошибка: не удалось подключиться к Ollama. Убедитесь, что сервер запущен (ollama serve)."
        except requests.exceptions.Timeout:
            logger.error("Таймаут при обращении к Ollama")
            return "Ошибка: Ollama не ответил вовремя."
        except Exception as e:
            logger.error(f"Ошибка запроса к Ollama: {e}")
            return f"Ошибка: {e}"

# Глобальный экземпляр
adapter = OllamaAdapter()