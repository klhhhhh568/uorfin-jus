#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Навык работы с LLM через Ollama.
Использует системный промпт из uorfin_charter.yaml.
"""

import json
import logging
import requests
import os
import yaml

logger = logging.getLogger(__name__)

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'uorfin_charter.yaml')

class LLMSkill:
    def __init__(self):
        self.ollama_url = "http://localhost:11434/api/generate"
        self.model = "deepseek-r1:1.5b"  # можно переопределить в конфиге
        self.system_prompt = self._load_system_prompt()
        self.language = "ru"  # по умолчанию

    def _load_system_prompt(self) -> str:
        """Загружает system_prompt из uorfin_charter.yaml."""
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
                return config.get('system_prompt', '')
        except Exception as e:
            logger.error(f"Не удалось загрузить system_prompt: {e}")
            return "Ты — полезный ассистент."

    def set_language(self, lang: str):
        self.language = lang

    def ask(self, question: str, history: list = None) -> str:
        """
        Отправляет запрос в Ollama с учётом системного промпта и истории.
        history – список словарей с ключами 'role' и 'content'.
        """
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        if history:
            for msg in history:
                messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})
        messages.append({"role": "user", "content": question})

        # Формируем промпт для Ollama (она не поддерживает messages, поэтому конкатенируем)
        prompt = ""
        for m in messages:
            if m["role"] == "system":
                prompt += f"System: {m['content']}\n"
            elif m["role"] == "user":
                prompt += f"User: {m['content']}\n"
            elif m["role"] == "assistant":
                prompt += f"Assistant: {m['content']}\n"
        prompt += "Assistant:"

        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.7,
                "top_p": 0.9
            }
        }

        try:
            resp = requests.post(self.ollama_url, json=payload, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            return data.get("response", "").strip()
        except Exception as e:
            logger.exception("Ошибка вызова Ollama")
            return f"Извините, произошла ошибка при обращении к LLM: {e}"

    def handle_message(self, message: str) -> str:
        """Обрабатывает команду 'ask'."""
        try:
            data = json.loads(message)
            command = data.get("command")
            if command == "ask":
                question = data.get("params", {}).get("question", "")
                history = data.get("params", {}).get("history", [])
                if not question:
                    return json.dumps({"error": "Нет вопроса"})
                answer = self.ask(question, history)
                return json.dumps({"status": "ok", "response": answer})
            else:
                return json.dumps({"error": f"Неизвестная команда: {command}"})
        except Exception as e:
            logger.exception("Ошибка в llm_skill")
            return json.dumps({"error": str(e)})

# Глобальный экземпляр
_skill = None

def init(name: str):
    global _skill
    _skill = LLMSkill()
    logger.info(f"LLMSkill инициализирован как {name}")

def set_language(lang: str):
    if _skill:
        _skill.set_language(lang)

def handle_message(message: str) -> str:
    if _skill is None:
        return json.dumps({"error": "Навык не инициализирован"})
    return _skill.handle_message(message)

def shutdown():
    global _skill
    _skill = None