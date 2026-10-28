#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Навык ТРИЗ (Теория решения изобретательских задач) для CAD-генерации.

Реализует полный цикл:
1. LLM-классификатор: определяет (improve, worsen) из текста запроса
2. Полная матрица 39×39: рекомендованные приёмы
3. PicoGK-маппинг: каждый приём → конкретные pg.* операции
4. picogk_hint: текст для system_prompt CAD-LLM

Источник матрицы: Antropocosmist/triz-engineering-solver (MIT)
"""

import json
import logging
import random
import re
from typing import Optional, List, Dict, Any, Callable

from .triz_data import (
    ENGINEERING_PARAMETERS,
    PRINCIPLE_PICOGK,
    CONTRADICTION_MATRIX,
    get_parameter,
    get_principle as _get_principle_data,
    get_principles_for,
    list_cad_parameters,
)

logger = logging.getLogger(__name__)


# ============================================================
# 40 ПРИНЦИПОВ (сохранены для обратной совместимости)
# ============================================================
TRIZ_PRINCIPLES = {
    1:  {'name': 'Дробление', 'description': 'Разделить объект на независимые части или сделать объект разборным.', 'examples': ['Разделение корабля на отсеки', 'Складная мебель']},
    2:  {'name': 'Вынесение', 'description': 'Отделить от объекта "мешающую" часть или выделить единственную нужную часть.', 'examples': ['Вынос кондиционера наружу', 'Внешний блок компьютера']},
    3:  {'name': 'Местное качество', 'description': 'Перейти от однородной структуры к неоднородной, сделать разные части объекта с разными функциями.', 'examples': ['Ковш экскаватора с разными зубьями', 'Гибкая печатная плата']},
    4:  {'name': 'Асимметрия', 'description': 'Перейти от симметричной формы к асимметричной.', 'examples': ['Асимметричный пропеллер', 'Косой срез трубы']},
    5:  {'name': 'Объединение', 'description': 'Соединить однородные или смежные объекты во времени или пространстве.', 'examples': ['Многослойная печатная плата', 'Конвейерная сборка']},
    6:  {'name': 'Универсальность', 'description': 'Сделать объект многофункциональным.', 'examples': ['Швейцарский нож', 'Смартфон']},
    7:  {'name': 'Матрёшка', 'description': 'Вложить один объект в другой, один проходит через полость другого.', 'examples': ['Телескопическая антенна', 'Вложенные контейнеры']},
    8:  {'name': 'Антивес', 'description': 'Компенсировать вес объекта соединением с подъёмным объектом или аэродинамическими силами.', 'examples': ['Воздушный шар', 'Гидрофойл']},
    9:  {'name': 'Предварительное противодействие', 'description': 'Заранее создать напряжение для компенсации вредного воздействия.', 'examples': ['Предварительное натяжение арматуры', 'Термообработка']},
    10: {'name': 'Предварительное действие', 'description': 'Выполнить заранее необходимое действие или разместить объекты в удобном положении.', 'examples': ['Предварительная резка бумаги', 'Шаблоны']},
    11: {'name': 'Заранее подложенная подушка', 'description': 'Компенсировать низкую надёжность заранее подготовленными средствами.', 'examples': ['Запасные части', 'Резервное копирование']},
    12: {'name': 'Эквипотенциальность', 'description': 'Изменить условия работы так, чтобы не приходилось поднимать или опускать объект.', 'examples': ['Работа на одном уровне', 'Гидравлический подъёмник']},
    13: {'name': 'Наоборот', 'description': 'Сделать действие обратным, перевернуть объект.', 'examples': ['Реверсивный двигатель', 'Перевёрнутый стакан']},
    14: {'name': 'Сфероидальность', 'description': 'Перейти от прямолинейных частей к криволинейным.', 'examples': ['Куполообразные крыши', 'Сферические подшипники']},
    15: {'name': 'Динамичность', 'description': 'Сделать объект изменяемым, адаптируемым к условиям.', 'examples': ['Гибкий шланг', 'Адаптивная подвеска']},
    16: {'name': 'Частичное или избыточное действие', 'description': 'Если трудно достичь 100% эффекта, сделать чуть больше или чуть меньше.', 'examples': ['Переливной клапан', 'Допуски в механике']},
    17: {'name': 'Переход в другое измерение', 'description': 'Использовать многослойные структуры, наклонять объект.', 'examples': ['Многослойная печатная плата', 'Наклонные плоскости']},
    18: {'name': 'Механические колебания', 'description': 'Использовать колебания, резонанс, ультразвук.', 'examples': ['Ультразвуковая сварка', 'Вибрационный транспортёр']},
    19: {'name': 'Периодическое действие', 'description': 'Заменить непрерывное действие периодическим.', 'examples': ['Импульсный режим', 'ШИМ-регулировка']},
    20: {'name': 'Непрерывность полезного действия', 'description': 'Организовать непрерывную работу, устранить холостые ходы.', 'examples': ['Конвейер', 'Поточная линия']},
    21: {'name': 'Проскок', 'description': 'Выполнить вредные операции на большой скорости.', 'examples': ['Быстрое охлаждение', 'Высокоскоростная резка']},
    22: {'name': 'Обратить вред в пользу', 'description': 'Использовать вредные факторы для положительного эффекта.', 'examples': ['Утилизация отходов', 'Использование тепла от двигателя']},
    23: {'name': 'Обратная связь', 'description': 'Ввести обратную связь, изменить её параметры.', 'examples': ['Автопилот', 'Термостат']},
    24: {'name': 'Посредник', 'description': 'Использовать промежуточный объект для передачи действия.', 'examples': ['Трансмиссия', 'Буферная память']},
    25: {'name': 'Самообслуживание', 'description': 'Сделать объект самообслуживающимся, использовать отходы.', 'examples': ['Самоочищающиеся окна', 'Рекуперация энергии']},
    26: {'name': 'Копирование', 'description': 'Вместо недоступного объекта использовать его копию.', 'examples': ['3D-печать', 'Голография']},
    27: {'name': 'Дешёвая недолговечность', 'description': 'Заменить дорогой объект на дешёвый с ограниченным сроком.', 'examples': ['Одноразовые инструменты', 'Бумажные фильтры']},
    28: {'name': 'Замена механической схемы', 'description': 'Заменить механическую систему на оптическую, акустическую, тепловую.', 'examples': ['Оптический датчик', 'Ультразвуковой дальномер']},
    29: {'name': 'Использование пневматики и гидравлики', 'description': 'Использовать газообразные или жидкие части вместо твёрдых.', 'examples': ['Гидравлический пресс', 'Пневматический привод']},
    30: {'name': 'Гибкие оболочки и тонкие плёнки', 'description': 'Использовать гибкие оболочки вместо массивных конструкций.', 'examples': ['Надувные конструкции', 'Мембранные клапаны']},
    31: {'name': 'Использование пористых материалов', 'description': 'Сделать объект пористым, использовать пористые вставки.', 'examples': ['Пористый металл', 'Губчатая резина']},
    32: {'name': 'Изменение цвета', 'description': 'Изменить цвет объекта или его прозрачность.', 'examples': ['Термохромные краски', 'Светофильтры']},
    33: {'name': 'Однородность', 'description': 'Объекты должны быть из одного материала.', 'examples': ['Сварка однородных металлов', 'Клеевые соединения']},
    34: {'name': 'Отбраковка и регенерация', 'description': 'Отбрасывать или восстанавливать части объекта после функции.', 'examples': ['Сменные фильтры', 'Регенеративные тормоза']},
    35: {'name': 'Изменение физико-химических параметров', 'description': 'Изменить агрегатное состояние, концентрацию, температуру.', 'examples': ['Термообработка', 'Легирование']},
    36: {'name': 'Фазовый переход', 'description': 'Использовать явления фазового перехода.', 'examples': ['Тепловые трубы', 'Паровая турбина']},
    37: {'name': 'Тепловое расширение', 'description': 'Использовать тепловое расширение материалов.', 'examples': ['Термометр', 'Термостат']},
    38: {'name': 'Использование сильных окислителей', 'description': 'Использовать обогащённый воздух, кислород, озон.', 'examples': ['Кислородная резка', 'Озонирование воды']},
    39: {'name': 'Инертная среда', 'description': 'Заменить обычную среду на инертную, использовать вакуум.', 'examples': ['Сварка в аргоне', 'Вакуумная упаковка']},
    40: {'name': 'Композитные материалы', 'description': 'Использовать композитные материалы для улучшения свойств.', 'examples': ['Углепластик', 'Стеклопластик']},
}


# ============================================================
# КЛАССИФИКАТОР: ТЕКСТ → (improve, worsen)
# ============================================================

# Ключевые слова для fallback-классификатора (если LLM недоступен)
KEYWORD_HINTS = {
    "вес": 1, "лёгк": 1, "легк": 1, "тонк": 1, "масс": 1, "облегч": 1,
    "размер": 7, "габарит": 7, "объём": 7, "объем": 7, "компакт": 7,
    "прочн": 14, "крепк": 14, "нагруз": 14, "выдерж": 14, "прочност": 14,
    "жёстк": 13, "жестк": 13, "деформ": 13, "устойчив": 13,
    "точн": 28, "прециз": 28, "допуск": 29,
    "быстр": 9, "скорост": 9, "ускор": 9,
    "надёжн": 27, "надежн": 27, "долговеч": 27,
    "дешев": 32, "дешёв": 32, "эконом": 32, "технолог": 32, "производ": 32,
    "сложн": 36, "прост": 36,
    "производит": 39, "скорост": 39,
    "температ": 17, "нагрев": 17,
    "мощн": 21,
    "энерг": 19, "эффектив": 19,
    "удобн": 33, "эргоном": 33,
}

# Что «ухудшится» при улучшении X (по умолчанию — типичное противоречие)
DEFAULT_WORSEN = {
    1: 14,    # вес → прочность
    7: 14,    # объём → прочность
    14: 1,    # прочность → вес
    13: 1,    # жёсткость → вес
    28: 9,    # точность → скорость
    9: 28,    # скорость → точность
    27: 1,    # надёжность → вес
    32: 14,   # дешевизна → прочность
    36: 14,   # простота → прочность
}


def _keyword_classify(prompt: str) -> Dict[str, Any]:
    """Fallback: определяет параметры по ключевым словам."""
    p = prompt.lower()

    improve = None
    worsen = None
    for kw, param in KEYWORD_HINTS.items():
        if kw in p:
            if improve is None:
                improve = param
            elif param != improve:
                worsen = param
                break

    if improve is None:
        improve = 1  # вес — самый частый
    if worsen is None:
        worsen = DEFAULT_WORSEN.get(improve, 14)

    return {"improve": improve, "worsen": worsen, "confidence": 0.5, "source": "keyword"}


def _llm_classify(prompt: str, llm_call: Callable[[str], str]) -> Dict[str, Any]:
    """LLM-классификатор: определяет конфликтующие параметры."""
    params_text = "\n".join(
        f"{n}: {p['name']}" for n, p in ENGINEERING_PARAMETERS.items()
    )
    classify_prompt = f"""Ты — TRIZ-аналитик. Проанализируй запрос на создание 3D-детали.
Определи техническое противоречие:
1. Какой параметр пользователь хочет УЛУЧШИТЬ.
2. Какой параметр при этом УХУДШИТСЯ (это неизбежно при улучшении первого).

Список 39 инженерных параметров:
{params_text}

Запрос: "{prompt}"

Ответь строго в формате JSON, без пояснений:
{{"improve": <номер>, "worsen": <номер>, "confidence": <0.0-1.0>}}"""

    try:
        raw = llm_call(classify_prompt)
        # Извлекаем JSON из ответа (может быть обёрнут в ```json ... ```)
        m = re.search(r'\{[^{}]*"improve"[^{}]*\}', raw, re.DOTALL)
        if not m:
            return _keyword_classify(prompt)
        data = json.loads(m.group(0))
        improve = int(data.get("improve", 1))
        worsen = int(data.get("worsen", 14))
        # Валидация диапазона
        if not (1 <= improve <= 39):
            improve = 1
        if not (1 <= worsen <= 39) or worsen == improve:
            worsen = DEFAULT_WORSEN.get(improve, 14)
        return {
            "improve": improve,
            "worsen": worsen,
            "confidence": float(data.get("confidence", 0.7)),
            "source": "llm",
        }
    except Exception as e:
        logger.warning(f"[TRIZ] LLM-классификатор упал: {e}, fallback на keyword")
        return _keyword_classify(prompt)


# ============================================================
# ПРИМЕНЕНИЕ МАТРИЦЫ + PICO GK-МАППИНГ
# ============================================================
def apply_matrix(improve: int, worsen: int) -> List[Dict[str, Any]]:
    """
    Возвращает список принципов с PicoGK-операциями.
    Каждый элемент: {id, name, description, examples, ops, hint}
    """
    nums = get_principles_for(improve, worsen)
    result = []
    for n in nums:
        base = TRIZ_PRINCIPLES.get(n, {})
        pg_data = PRINCIPLE_PICOGK.get(n, {})
        result.append({
            "id": n,
            "name": base.get("name", f"Принцип {n}"),
            "description": base.get("description", ""),
            "examples": base.get("examples", []),
            "ops": pg_data.get("ops", []),
            "hint": pg_data.get("hint", ""),
        })
    return result


def build_picogk_hint(principles: List[Dict[str, Any]],
                      improve_param: Dict, worsen_param: Dict) -> str:
    """Формирует текст с TRIZ-рекомендациями для system_prompt CAD-LLM."""
    if not principles:
        return ""

    lines = [
        "ТРИЗ-АНАЛИЗ (техническое противоречие):",
        f"  Улучшаем:  {improve_param.get('name', '?')}",
        f"  Ухудшаем:  {worsen_param.get('name', '?')}",
        "",
        "Рекомендуемые изобретательские приёмы:",
    ]
    for i, p in enumerate(principles, 1):
        lines.append(f"  {i}. Принцип {p['id']} «{p['name']}» — {p['hint']}")
        if p['ops']:
            lines.append(f"     PicoGK-операции: {', '.join(p['ops'])}")

    lines.append("")
    lines.append("Примени эти приёмы при проектировании геометрии.")
    return "\n".join(lines)


# ============================================================
# ГЛАВНЫЙ МЕТОД ДЛЯ CAD
# ============================================================
def analyze(prompt: str, llm_call: Optional[Callable[[str], str]] = None) -> Dict[str, Any]:
    """
    Полный TRIZ-анализ текстового запроса.

    Возвращает dict с обратной совместимостью (suggestions, contradictions)
    и новыми полями (improve_param, worsen_param, principles, picogk_hint).

    llm_call — опциональная функция (prompt_str) -> response_str.
    Если None — используется keyword fallback.
    """
    # 1. Определяем противоречие
    if llm_call:
        contradiction = _llm_classify(prompt, llm_call)
    else:
        contradiction = _keyword_classify(prompt)

    improve = contradiction["improve"]
    worsen = contradiction["worsen"]

    # 2. Применяем матрицу
    principles = apply_matrix(improve, worsen)

    # 3. Формируем PicoGK-хинт
    improve_param = ENGINEERING_PARAMETERS.get(improve, {})
    worsen_param = ENGINEERING_PARAMETERS.get(worsen, {})
    picogk_hint = build_picogk_hint(principles, improve_param, worsen_param)

    # 4. Совместимость со старым форматом (UI: data.triz.suggestions)
    suggestions = []
    for p in principles:
        suggestions.append(f"[{p['id']}] {p['name']}: {p['hint']}")

    contradictions_str = []
    if improve_param and worsen_param:
        contradictions_str.append(
            f"{improve_param['name']} ↔ {worsen_param['name']}"
        )

    return {
        # Новые поля
        "improve_param": {"id": improve, **improve_param},
        "worsen_param":  {"id": worsen,  **worsen_param},
        "principles": principles,
        "picogk_hint": picogk_hint,
        "confidence": contradiction["confidence"],
        "source": contradiction["source"],
        # Обратная совместимость
        "suggestions": suggestions,
        "contradictions": contradictions_str,
    }


# ============================================================
# СТАРЫЕ ФУНКЦИИ (для обратной совместимости)
# ============================================================
def get_principle(number: int) -> dict:
    return TRIZ_PRINCIPLES.get(number, {})

def get_all_principles() -> dict:
    return TRIZ_PRINCIPLES

def search_principles(keyword: str) -> list:
    results = []
    kw = keyword.lower()
    for num, princ in TRIZ_PRINCIPLES.items():
        if kw in princ['name'].lower() or kw in princ['description'].lower():
            results.append((num, princ))
    return results

def get_principles_for_contradiction(improve: str, worsen: str) -> list:
    """Устаревший API. Используй apply_matrix(int, int)."""
    return []


# ============================================================
# НАВЫК ДЛЯ ОРКЕСТРАТОРА
# ============================================================
class TrizSolver:
    def suggest_solutions(self, problem: str, max_suggestions: int = 5) -> List[Dict[str, Any]]:
        """Генерирует идеи через полный TRIZ-анализ."""
        result = analyze(problem)
        out = []
        for p in result["principles"][:max_suggestions]:
            out.append({
                'principle': p['name'],
                'description': p['description'],
                'example': random.choice(p['examples']) if p['examples'] else '',
                'how_to_apply': p['hint'],
                'picogk_ops': p['ops'],
            })
        return out

    def search_by_keyword(self, keyword: str) -> list:
        return search_principles(keyword)


class TrizSkill:
    def __init__(self):
        self.solver = TrizSolver()
        logger.info(f"TRIZ-навык инициализирован ({len(CONTRADICTION_MATRIX)} ячеек матрицы)")

    def handle_message(self, message: str) -> str:
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            return json.dumps({"error": "Неверный формат JSON"})

        command = data.get("command")
        params = data.get("params", {})

        try:
            if command == "analyze":
                prompt = params.get("prompt", "")
                if not prompt:
                    return json.dumps({"error": "Не указан prompt"})
                result = analyze(prompt)
                return json.dumps({"status": "ok", **result}, ensure_ascii=False)

            elif command == "generate_ideas":
                problem = params.get("problem", "")
                if not problem:
                    return json.dumps({"error": "Не указана проблема"})
                suggestions = self.solver.suggest_solutions(
                    problem, params.get("max_suggestions", 5)
                )
                return json.dumps({"status": "ok", "suggestions": suggestions}, ensure_ascii=False)

            elif command == "search_principles":
                keyword = params.get("keyword", "")
                if not keyword:
                    return json.dumps({"error": "Не указано ключевое слово"})
                results = search_principles(keyword)
                return json.dumps({"status": "ok", "results": results}, ensure_ascii=False)

            elif command == "resolve_contradiction":
                improve = int(params.get("improve", 1))
                worsen = int(params.get("worsen", 14))
                principles = apply_matrix(improve, worsen)
                return json.dumps({"status": "ok", "principles": principles}, ensure_ascii=False)

            elif command == "get_principle":
                number = params.get("number")
                if number is None:
                    return json.dumps({"error": "Не указан номер принципа"})
                principle = get_principle(int(number))
                if principle:
                    return json.dumps({"status": "ok", "principle": principle}, ensure_ascii=False)
                return json.dumps({"status": "error", "message": f"Принцип #{number} не найден"})

            elif command == "list_principles":
                return json.dumps({"status": "ok", "principles": get_all_principles()}, ensure_ascii=False)

            else:
                return json.dumps({"error": f"Неизвестная команда: {command}"})

        except Exception as e:
            logger.exception("Ошибка выполнения команды ТРИЗ")
            return json.dumps({"error": str(e)})

    def shutdown(self):
        logger.info("TRIZ-навык выгружен")


# ============================================================
# ГЛОБАЛЬНЫЕ ФУНКЦИИ (для оркестратора)
# ============================================================
_skill = None

def init(name: str) -> None:
    global _skill
    _skill = TrizSkill()
    logger.info(f"TRIZ-навык '{name}' инициализирован")

def handle_message(message: str) -> str:
    if _skill is None:
        return json.dumps({"error": "Навык не инициализирован"})
    return _skill.handle_message(message)

def shutdown(name: Optional[str] = None) -> None:
    global _skill
    if _skill:
        _skill.shutdown()
    _skill = None