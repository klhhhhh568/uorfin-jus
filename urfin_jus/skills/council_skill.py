# skills/council_skill.py
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

MAX_PROBLEM_LENGTH = 2000


def init(name: str) -> None:
    logger.info("Совет '%s' инициализирован", name)
    try:
        from skills import llm_skill
        if not hasattr(llm_skill, '_llm') or llm_skill._llm is None:
            llm_skill.init("CouncilLLM")
    except Exception as e:
        logger.warning("Не удалось инициализировать llm_skill: %s", e)


def handle_message(message: str) -> str:
    try:
        data = json.loads(message)
    except json.JSONDecodeError:
        return json.dumps({"error": "Неверный формат JSON"})

    command = data.get("command")
    if command != "advise":
        return json.dumps({"error": f"Неизвестная команда: {command}"})

    problem = data.get("problem", "")
    if not problem or not isinstance(problem, str):
        return json.dumps({"error": "Проблема не указана или некорректна"})

    if len(problem) > MAX_PROBLEM_LENGTH:
        problem = problem[:MAX_PROBLEM_LENGTH] + "..."
        logger.info("Проблема обрезана до %d символов", MAX_PROBLEM_LENGTH)

    prompt = (
        "Ты — совет экспертов, состоящий из инженера, учёного и стратега. "
        "Проанализируй проблему, предложи взвешенное решение и, если возможно, дай несколько вариантов.\n\n"
        f"Проблема: {problem}"
    )

    try:
        from skills import llm_skill
        response = llm_skill.handle_message(
            prompt,
            system_prompt="Ты — мудрый советник, объединяющий мнения нескольких экспертов."
        )
    except Exception as e:
        logger.exception("Ошибка при обращении к LLM")
        return json.dumps({"error": "Внутренняя ошибка при генерации совета"})

    if not response:
        logger.warning("Пустой ответ от LLM")
        return json.dumps({"advice": "Совет не смог выработать решение по данному вопросу."})

    logger.info("Совет сгенерирован (%d символов)", len(response))
    return json.dumps({"advice": response})


def shutdown(name: Optional[str] = None) -> None:
    logger.info("Совет выгружен")