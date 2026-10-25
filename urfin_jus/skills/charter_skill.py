#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Навык проверки команд на соответствие Уставу.
Загружает forbidden_actions из uorfin_charter.yaml.
"""

import json
import logging
import os
import yaml

logger = logging.getLogger(__name__)

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'uorfin_charter.yaml')

class CharterSkill:
    def __init__(self):
        self.forbidden_actions = self._load_forbidden_actions()

    def _load_forbidden_actions(self):
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
                return config.get('forbidden_actions', [])
        except Exception as e:
            logger.error(f"Ошибка загрузки forbidden_actions: {e}")
            return []

    def check(self, command: str) -> bool:
        """Проверяет, не содержит ли команда запрещённых действий."""
        for forbidden in self.forbidden_actions:
            if forbidden.lower() in command.lower():
                logger.warning(f"Обнаружено запрещённое действие: {forbidden}")
                return False
        return True

    def handle_message(self, message: str) -> str:
        try:
            data = json.loads(message)
            command = data.get("command")
            if command == "check":
                text = data.get("params", {}).get("text", "")
                if not text:
                    return json.dumps({"error": "Нет текста для проверки"})
                allowed = self.check(text)
                return json.dumps({"status": "ok", "allowed": allowed})
            else:
                return json.dumps({"error": f"Неизвестная команда: {command}"})
        except Exception as e:
            return json.dumps({"error": str(e)})

_skill = None

def init(name: str):
    global _skill
    _skill = CharterSkill()
    logger.info(f"CharterSkill инициализирован как {name}")

def handle_message(message: str) -> str:
    if _skill is None:
        return json.dumps({"error": "Навык не инициализирован"})
    return _skill.handle_message(message)

def shutdown():
    global _skill
    _skill = None