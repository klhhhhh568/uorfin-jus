import os
import logging
from dotenv import load_dotenv
from openai import OpenAI

config_dir = os.getenv("UORFIN_CONFIG_DIR", os.path.expanduser("~/uorfin_jus"))
dotenv_path = os.path.join(config_dir, ".env")
load_dotenv(dotenv_path)

logger = logging.getLogger(__name__)

class OpenRouterAdapter:
    def __init__(self):
        self.api_key = os.getenv("OPENROUTER_API_KEY")
        self.configured = False
        if not self.api_key:
            logger.error("OPENROUTER_API_KEY не найден в .env")
            return
        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=self.api_key,
            default_headers={
                "HTTP-Referer": "https://github.com/uorfin-jus",
                "X-Title": "Uorfin Jus"
            }
        )
        self.model = os.getenv("OPENROUTER_MODEL", "poolside/laguna-xs.2:free")
        self.max_tokens = int(os.getenv("OPENROUTER_MAX_TOKENS", "600"))
        self.timeout = float(os.getenv("OPENROUTER_TIMEOUT", "30.0"))
        self.configured = True

    def query(self, prompt, system_prompt=None, temperature=0.3):
        if not self.configured:
            return "Ошибка LLM: OpenRouter не настроен"
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=self.max_tokens,
                timeout=self.timeout
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.exception("Ошибка запроса к OpenRouter")
            return f"Ошибка LLM: {e}"

try:
    adapter = OpenRouterAdapter()
except Exception as e:
    adapter = None
    logging.critical(f"Критическая ошибка при создании адаптера: {e}")