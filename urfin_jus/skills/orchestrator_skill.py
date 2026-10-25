#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Оркестратор навыков Urfin Jus.
Маршрутизирует запросы к соответствующим навыкам.
"""

import json
import logging
import importlib
import os
import sys

# Добавляем путь к проекту для импорта модулей
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger(__name__)

# Список навыков (по умолчанию загружаются все из папки skills, кроме этого файла)
SKILLS = {}

# Навыки, которые следует игнорировать (устаревшие или конфликтующие)
IGNORED_SKILLS = {
    # Старые навыки
    "opencad_skill",
    "openklhcad_skill",
    "cad_skill",
    # PicoGK-модули (не скиллы — вызываются из cad_generation)
    "picogk_binding",
    "picogk_worker",
    "cad_generation",
    # Нейросеть (инициализируется через dual_hemisphere_cloud)
    "brain_db",
    "neural_engine",
    "brain_bootstrap",
    # Извлечение промптов (вспомогательный модуль)
    "prompt_extractor",
    # Прочее
    "ollama_client",
}

def init(name: str = "Orchestrator"):
    """Инициализация оркестратора: загружает все навыки из папки skills."""
    global SKILLS
    logger.info(f"Инициализация оркестратора {name}...")
    skills_dir = os.path.join(os.path.dirname(__file__))
    for file in os.listdir(skills_dir):
        if file.endswith(".py") and file not in ["orchestrator_skill.py", "__init__.py"]:
            module_name = file[:-3]
            # Пропускаем игнорируемые навыки
            if module_name in IGNORED_SKILLS:
                logger.info(f"Навык {module_name} пропущен (устаревший)")
                continue
            try:
                module = importlib.import_module(f"skills.{module_name}")
                if hasattr(module, "init"):
                    module.init(module_name)
                    SKILLS[module_name] = module
                    logger.info(f"Навык {module_name} загружен")
                else:
                    logger.warning(f"Модуль {module_name} не имеет init(), пропускаем")
            except Exception as e:
                logger.error(f"Ошибка загрузки навыка {module_name}: {e}")
    logger.info(f"Оркестратор готов. Загружено навыков: {len(SKILLS)}")

def handle_message(message: str) -> str:
    """
    Обрабатывает входящее сообщение (JSON).
    Поддерживает команды:
      - {"command": "process", "input": "текст"} – запускает двуполушарный анализ
      - {"command": "direct", "skill": "имя", "payload": {...}} – прямой вызов навыка
      - {"command": "list_skills"} – возвращает список доступных навыков
    """
    try:
        data = json.loads(message)
        command = data.get("command")

        if command == "process":
            user_input = data.get("input", "").strip()
            if not user_input:
                return json.dumps({"error": "Нет текста для обработки"})

            # Запускаем двуполушарный анализ через dual_hemisphere_cloud
            if "dual_hemisphere_cloud" in SKILLS:
                try:
                    resp = SKILLS["dual_hemisphere_cloud"].handle_message(json.dumps({
                        "command": "process_task",
                        "params": {"task": user_input}
                    }))
                    # Проверяем, не вернулась ли ошибка
                    resp_data = json.loads(resp)
                    if "error" in resp_data:
                        # Если ошибка – пробуем передать в llm_skill как fallback
                        return fallback_to_llm(user_input)
                    return resp
                except Exception as e:
                    logger.exception("Ошибка в dual_hemisphere_cloud, переключаемся на llm_skill")
                    return fallback_to_llm(user_input)
            else:
                logger.warning("dual_hemisphere_cloud не загружен, используем llm_skill")
                return fallback_to_llm(user_input)

        elif command == "direct":
            skill_name = data.get("skill")
            payload = data.get("payload", {})
            if skill_name in SKILLS:
                return SKILLS[skill_name].handle_message(json.dumps(payload))
            else:
                return json.dumps({"error": f"Навык {skill_name} не найден"})

        elif command == "list_skills":
            return json.dumps({"skills": list(SKILLS.keys())})

        else:
            return json.dumps({"error": f"Неизвестная команда: {command}"})

    except json.JSONDecodeError:
        logger.error(f"Невалидный JSON: {message}")
        return json.dumps({"error": "Невалидный JSON"})
    except Exception as e:
        logger.exception("Ошибка в оркестраторе")
        return json.dumps({"error": str(e)})

def fallback_to_llm(user_input: str) -> str:
    """Фолбэк: использует llm_skill для простого ответа."""
    if "llm_skill" in SKILLS:
        try:
            resp = SKILLS["llm_skill"].handle_message(json.dumps({
                "command": "ask",
                "params": {"question": user_input}
            }))
            return resp
        except Exception as e:
            return json.dumps({"error": f"Ошибка LLM: {e}"})
    else:
        return json.dumps({"error": "Нет доступных навыков для обработки запроса"})

def shutdown():
    """Завершение работы оркестратора: вызывает shutdown у всех навыков."""
    for name, module in SKILLS.items():
        if hasattr(module, "shutdown"):
            try:
                module.shutdown()
            except Exception as e:
                logger.error(f"Ошибка shutdown {name}: {e}")
    SKILLS.clear()

# Если файл запущен как самостоятельный скрипт – инициализируем и запускаем тест
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    init()
    # Тест: отправляем сообщение
    test_msg = json.dumps({"command": "process", "input": "Привет, что ты умеешь?"})
    print("Ответ:", handle_message(test_msg))