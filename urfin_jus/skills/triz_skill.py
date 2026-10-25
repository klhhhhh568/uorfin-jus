#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Навык ТРИЗ (Теория решения изобретательских задач).
Содержит встроенную таблицу 40 принципов и генератор идей.
Не зависит от OpenKLHCAD.
"""

import json
import logging
import random
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

# ===================== Таблица 40 принципов ТРИЗ =====================
TRIZ_PRINCIPLES = {
    1: {
        'name': 'Дробление',
        'description': 'Разделить объект на независимые части или сделать объект разборным.',
        'examples': ['Разделение корабля на отсеки', 'Складная мебель']
    },
    2: {
        'name': 'Вынесение',
        'description': 'Отделить от объекта "мешающую" часть или, наоборот, выделить единственную нужную часть.',
        'examples': ['Вынос кондиционера наружу', 'Внешний блок компьютера']
    },
    3: {
        'name': 'Местное качество',
        'description': 'Перейти от однородной структуры к неоднородной, сделать разные части объекта с разными функциями.',
        'examples': ['Ковш экскаватора с разными зубьями', 'Гибкая печатная плата']
    },
    4: {
        'name': 'Асимметрия',
        'description': 'Перейти от симметричной формы к асимметричной.',
        'examples': ['Асимметричный пропеллер', 'Косой срез трубы']
    },
    5: {
        'name': 'Объединение',
        'description': 'Соединить однородные или смежные объекты или операции во времени или пространстве.',
        'examples': ['Многослойная печатная плата', 'Конвейерная сборка']
    },
    6: {
        'name': 'Универсальность',
        'description': 'Сделать объект многофункциональным, способным выполнять несколько разных задач.',
        'examples': ['Швейцарский нож', 'Смартфон']
    },
    7: {
        'name': 'Матрёшка',
        'description': 'Вложить один объект в другой, один проходит через полость другого.',
        'examples': ['Телескопическая антенна', 'Вложенные контейнеры']
    },
    8: {
        'name': 'Антивес',
        'description': 'Компенсировать вес объекта соединением с другим подъёмным объектом или использованием аэродинамических сил.',
        'examples': ['Воздушный шар', 'Гидрофойл']
    },
    9: {
        'name': 'Предварительное противодействие',
        'description': 'Заранее создать напряжение или противодействие, чтобы компенсировать вредное воздействие.',
        'examples': ['Предварительное натяжение арматуры', 'Термообработка']
    },
    10: {
        'name': 'Предварительное действие',
        'description': 'Выполнить заранее необходимое действие или разместить объекты в удобном положении.',
        'examples': ['Предварительная резка бумаги', 'Шаблоны']
    },
    11: {
        'name': 'Заранее подложенная подушка',
        'description': 'Компенсировать низкую надёжность объекта заранее подготовленными средствами.',
        'examples': ['Запасные части', 'Резервное копирование']
    },
    12: {
        'name': 'Эквипотенциальность',
        'description': 'Изменить условия работы так, чтобы не приходилось поднимать или опускать объект.',
        'examples': ['Работа на одном уровне', 'Гидравлический подъёмник']
    },
    13: {
        'name': 'Наоборот',
        'description': 'Сделать действие обратным, перевернуть объект, использовать движение в противоположном направлении.',
        'examples': ['Реверсивный двигатель', 'Перевёрнутый стакан']
    },
    14: {
        'name': 'Сфероидальность',
        'description': 'Перейти от прямолинейных частей к криволинейным, от плоских к сферическим.',
        'examples': ['Куполообразные крыши', 'Сферические подшипники']
    },
    15: {
        'name': 'Динамичность',
        'description': 'Сделать объект изменяемым, адаптируемым к условиям работы.',
        'examples': ['Гибкий шланг', 'Адаптивная подвеска']
    },
    16: {
        'name': 'Частичное или избыточное действие',
        'description': 'Если трудно достичь 100% эффекта, можно сделать чуть больше или чуть меньше.',
        'examples': ['Переливной клапан', 'Допуски в механике']
    },
    17: {
        'name': 'Переход в другое измерение',
        'description': 'Использовать многослойные структуры, наклонять объект, использовать другую сторону.',
        'examples': ['Многослойная печатная плата', 'Наклонные плоскости']
    },
    18: {
        'name': 'Механические колебания',
        'description': 'Использовать колебания, резонанс, ультразвук.',
        'examples': ['Ультразвуковая сварка', 'Вибрационный транспортёр']
    },
    19: {
        'name': 'Периодическое действие',
        'description': 'Заменить непрерывное действие периодическим, изменить частоту.',
        'examples': ['Импульсный режим', 'ШИМ-регулировка']
    },
    20: {
        'name': 'Непрерывность полезного действия',
        'description': 'Организовать непрерывную работу, устранить холостые ходы.',
        'examples': ['Конвейер', 'Поточная линия']
    },
    21: {
        'name': 'Проскок',
        'description': 'Выполнить вредные или опасные операции на большой скорости.',
        'examples': ['Быстрое охлаждение', 'Высокоскоростная резка']
    },
    22: {
        'name': 'Обратить вред в пользу',
        'description': 'Использовать вредные факторы для получения положительного эффекта.',
        'examples': ['Утилизация отходов', 'Использование тепла от двигателя']
    },
    23: {
        'name': 'Обратная связь',
        'description': 'Ввести обратную связь, изменить её параметры.',
        'examples': ['Автопилот', 'Термостат']
    },
    24: {
        'name': 'Посредник',
        'description': 'Использовать промежуточный объект для передачи действия.',
        'examples': ['Трансмиссия', 'Буферная память']
    },
    25: {
        'name': 'Самообслуживание',
        'description': 'Сделать объект самообслуживающимся, использовать отходы.',
        'examples': ['Самоочищающиеся окна', 'Рекуперация энергии']
    },
    26: {
        'name': 'Копирование',
        'description': 'Вместо недоступного объекта использовать его копию или модель.',
        'examples': ['3D-печать', 'Голография']
    },
    27: {
        'name': 'Дешёвая недолговечность',
        'description': 'Заменить дорогой объект на дешёвый с ограниченным сроком службы.',
        'examples': ['Одноразовые инструменты', 'Бумажные фильтры']
    },
    28: {
        'name': 'Замена механической схемы',
        'description': 'Заменить механическую систему на оптическую, акустическую, тепловую и т.д.',
        'examples': ['Оптический датчик', 'Ультразвуковой дальномер']
    },
    29: {
        'name': 'Использование пневматики и гидравлики',
        'description': 'Использовать газообразные или жидкие части вместо твёрдых.',
        'examples': ['Гидравлический пресс', 'Пневматический привод']
    },
    30: {
        'name': 'Гибкие оболочки и тонкие плёнки',
        'description': 'Использовать гибкие оболочки, тонкие плёнки вместо массивных конструкций.',
        'examples': ['Надувные конструкции', 'Мембранные клапаны']
    },
    31: {
        'name': 'Использование пористых материалов',
        'description': 'Сделать объект пористым, использовать пористые вставки.',
        'examples': ['Пористый металл', 'Губчатая резина']
    },
    32: {
        'name': 'Изменение цвета',
        'description': 'Изменить цвет объекта или его прозрачность.',
        'examples': ['Термохромные краски', 'Светофильтры']
    },
    33: {
        'name': 'Однородность',
        'description': 'Объекты, взаимодействующие с данным, должны быть сделаны из одного материала.',
        'examples': ['Сварка однородных металлов', 'Клеевые соединения']
    },
    34: {
        'name': 'Отбраковка и регенерация',
        'description': 'Отбрасывать или восстанавливать части объекта после выполнения функции.',
        'examples': ['Сменные фильтры', 'Регенеративные тормоза']
    },
    35: {
        'name': 'Изменение физико-химических параметров',
        'description': 'Изменить агрегатное состояние, концентрацию, температуру и т.д.',
        'examples': ['Термообработка', 'Легирование']
    },
    36: {
        'name': 'Фазовый переход',
        'description': 'Использовать явления фазового перехода (плавление, испарение и т.д.).',
        'examples': ['Тепловые трубы', 'Паровая турбина']
    },
    37: {
        'name': 'Тепловое расширение',
        'description': 'Использовать тепловое расширение материалов.',
        'examples': ['Термометр', 'Термостат']
    },
    38: {
        'name': 'Использование сильных окислителей',
        'description': 'Использовать обогащённый воздух, кислород, озонированный воздух.',
        'examples': ['Кислородная резка', 'Озонирование воды']
    },
    39: {
        'name': 'Инертная среда',
        'description': 'Заменить обычную среду на инертную, использовать вакуум.',
        'examples': ['Сварка в аргоне', 'Вакуумная упаковка']
    },
    40: {
        'name': 'Композитные материалы',
        'description': 'Использовать композитные материалы для улучшения свойств.',
        'examples': ['Углепластик', 'Стеклопластик']
    }
}


# ===================== Вспомогательные функции =====================

def get_principle(number: int) -> dict:
    """Получить принцип по номеру."""
    return TRIZ_PRINCIPLES.get(number, {})


def get_all_principles() -> dict:
    """Вернуть все принципы."""
    return TRIZ_PRINCIPLES


def search_principles(keyword: str) -> list:
    """Поиск принципов по ключевому слову в названии или описании."""
    results = []
    keyword_lower = keyword.lower()
    for num, princ in TRIZ_PRINCIPLES.items():
        if keyword_lower in princ['name'].lower() or keyword_lower in princ['description'].lower():
            results.append((num, princ))
    return results


def get_principles_for_contradiction(improve: str, worsen: str) -> list:
    """
    Упрощённая матрица противоречий. Возвращает список рекомендуемых принципов.
    """
    # Базовая матрица (неполная, для демонстрации)
    matrix = {
        ('weight', 'strength'): [1, 8, 14, 15],
        ('weight', 'speed'): [1, 8, 15, 34],
        ('strength', 'weight'): [1, 8, 14, 15],
        ('strength', 'complexity'): [1, 8, 14, 15],
        ('speed', 'weight'): [1, 8, 15, 34],
        ('speed', 'accuracy'): [1, 8, 15, 34],
        ('accuracy', 'speed'): [1, 8, 15, 34],
        ('complexity', 'strength'): [1, 8, 14, 15],
    }
    key = (improve.lower(), worsen.lower())
    if key in matrix:
        return [TRIZ_PRINCIPLES.get(num, {}) for num in matrix[key]]
    # Попробуем обратный порядок
    key_rev = (worsen.lower(), improve.lower())
    if key_rev in matrix:
        return [TRIZ_PRINCIPLES.get(num, {}) for num in matrix[key_rev]]
    return []


# ===================== Генератор идей (TrizSolver) =====================

class TrizSolver:
    """Генератор идей на основе ТРИЗ-принципов."""

    def suggest_solutions(self, problem: str, max_suggestions: int = 5) -> List[Dict[str, Any]]:
        """Генерирует идеи для решения проблемы, используя случайные принципы."""
        suggestions = []
        all_keys = list(TRIZ_PRINCIPLES.keys())
        selected = random.sample(all_keys, min(max_suggestions, len(all_keys)))
        for key in selected:
            princ = TRIZ_PRINCIPLES[key]
            suggestions.append({
                'principle': princ['name'],
                'description': princ['description'],
                'example': random.choice(princ['examples']) if princ['examples'] else '',
                'how_to_apply': f"Примените принцип '{princ['name']}' к проблеме: {problem}"
            })
        return suggestions

    def search_by_keyword(self, keyword: str) -> list:
        """Поиск принципов по ключевому слову."""
        return search_principles(keyword)


# ===================== Навык для оркестратора =====================

class TrizSkill:
    def __init__(self):
        self.solver = TrizSolver()
        logger.info("TRIZ-навык инициализирован (локальная таблица)")

    def handle_message(self, message: str) -> str:
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            return json.dumps({"error": "Неверный формат JSON"})

        command = data.get("command")
        params = data.get("params", {})

        try:
            if command == "generate_ideas":
                problem = params.get("problem", "")
                if not problem:
                    return json.dumps({"error": "Не указана проблема"})
                max_suggestions = params.get("max_suggestions", 5)
                suggestions = self.solver.suggest_solutions(problem, max_suggestions)
                return json.dumps({"status": "ok", "suggestions": suggestions})

            elif command == "search_principles":
                keyword = params.get("keyword", "")
                if not keyword:
                    return json.dumps({"error": "Не указано ключевое слово"})
                results = search_principles(keyword)
                return json.dumps({"status": "ok", "results": results})

            elif command == "resolve_contradiction":
                improve = params.get("improve", "")
                worsen = params.get("worsen", "")
                if not improve or not worsen:
                    return json.dumps({"error": "Укажите параметры improve и worsen"})
                principles = get_principles_for_contradiction(improve, worsen)
                return json.dumps({"status": "ok", "principles": principles})

            elif command == "get_principle":
                number = params.get("number")
                if number is None:
                    return json.dumps({"error": "Не указан номер принципа"})
                principle = get_principle(int(number))
                if principle:
                    return json.dumps({"status": "ok", "principle": principle})
                else:
                    return json.dumps({"status": "error", "message": f"Принцип #{number} не найден"})

            elif command == "list_principles":
                all_principles = get_all_principles()
                return json.dumps({"status": "ok", "principles": all_principles})

            else:
                return json.dumps({"error": f"Неизвестная команда: {command}"})

        except Exception as e:
            logger.exception("Ошибка выполнения команды ТРИЗ")
            return json.dumps({"error": str(e)})

    def shutdown(self):
        logger.info("TRIZ-навык выгружен")


# ===================== Глобальные функции для оркестратора =====================

_skill = None


def init(name: str) -> None:
    global _skill
    _skill = TrizSkill()
    logger.info(f"TRIZ-навык '{name}' инициализирован (локальная таблица)")


def handle_message(message: str) -> str:
    if _skill is None:
        return json.dumps({"error": "Навык не инициализирован"})
    return _skill.handle_message(message)


def shutdown(name: Optional[str] = None) -> None:
    global _skill
    if _skill:
        _skill.shutdown()
    _skill = None
    logger.info("TRIZ-навык выгружен")