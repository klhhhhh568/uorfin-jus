#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TRIZ: база знаний для CAD-калькулятора.
- 39 инженерных параметров Альтшуллера
- 40 изобретательских приёмов с маппингом на PicoGK-операции
- матрица противоречий 39×39 (загружается из triz_matrix.json)
"""

import json as _json
import os as _os


# ============================================================
# 39 ИНЖЕНЕРНЫХ ПАРАМЕТРОВ
# group — для быстрой фильтрации
# picogk_hint — типовые приёмы и операции PicoGK
# ============================================================
ENGINEERING_PARAMETERS = {
    1:  {"name": "Вес подвижного объекта",      "group": "weight",   "picogk_hint": "облегчить: render_implicit + render_lattice"},
    2:  {"name": "Вес неподвижного объекта",    "group": "weight",   "picogk_hint": "уменьшить объём или использовать латтис"},
    3:  {"name": "Длина подвижного объекта",    "group": "dims",     "picogk_hint": "капсула/цилиндр, если линейно"},
    4:  {"name": "Длина неподвижного объекта",  "group": "dims",     "picogk_hint": "уменьшить offset по оси Z"},
    5:  {"name": "Площадь подвижного объекта",  "group": "dims",     "picogk_hint": "изменить footprint в XY"},
    6:  {"name": "Площадь неподвижного объекта","group": "dims",     "picogk_hint": "изменить footprint в XY"},
    7:  {"name": "Объём подвижного объекта",    "group": "dims",     "picogk_hint": "уменьшить радиус/толщину"},
    8:  {"name": "Объём неподвижного объекта",  "group": "dims",     "picogk_hint": "вычесть полости через pg.subtract"},
    9:  {"name": "Скорость",                    "group": "energy",   "picogk_hint": "для подвижных: облегчить и уменьшить трение"},
    10: {"name": "Сила",                        "group": "energy",   "picogk_hint": "усилить в направлении нагрузки"},
    11: {"name": "Напряжение, давление",        "group": "energy",   "picogk_hint": "усилить в нагруженной зоне: pg.offset(+)"},
    12: {"name": "Форма",                       "group": "geometry", "picogk_hint": "перейти к сфероидальности (principle 14)"},
    13: {"name": "Устойчивость к деформации",   "group": "strength", "picogk_hint": "добавить рёбра/латтис (principle 3, 17, 40)"},
    14: {"name": "Прочность",                   "group": "strength", "picogk_hint": "offset(+) в нагруженных зонах, композиты"},
    15: {"name": "Продолжительность работы",    "group": "energy",   "picogk_hint": "усилить износостойкие участки"},
    16: {"name": "Стойкость к внешнему воздействию", "group": "strength", "picogk_hint": "закрыть/защитить уязвимые зоны"},
    17: {"name": "Температура",                 "group": "energy",   "picogk_hint": "рёбра охлаждения (principle 3)"},
    18: {"name": "Освещённость",                "group": "energy",   "picogk_hint": "отверстия/каналы для света"},
    19: {"name": "Энергозатраты подвижного объекта", "group": "energy", "picogk_hint": "уменьшить вес/трение"},
    20: {"name": "Энергозатраты неподвижного объекта", "group": "energy", "picogk_hint": "минимизировать объём"},
    21: {"name": "Мощность",                    "group": "energy",   "picogk_hint": "увеличить сечения в силовой части"},
    22: {"name": "Потери энергии",              "group": "energy",   "picogk_hint": "уменьшить вес/трение"},
    23: {"name": "Потери вещества",             "group": "energy",   "picogk_hint": "замкнутые объёмы/каналы"},
    24: {"name": "Потери информации",           "group": "info",     "picogk_hint": "уменьшить зазоры/допуски"},
    25: {"name": "Потери времени",              "group": "time",     "picogk_hint": "уменьшить число операций"},
    26: {"name": "Количество вещества",         "group": "weight",   "picogk_hint": "уменьшить материал через латтис"},
    27: {"name": "Надёжность",                  "group": "strength", "picogk_hint": "добавить рёбра/толщину в критичных зонах"},
    28: {"name": "Точность измерения",          "group": "info",     "picogk_hint": "уменьшить voxel_size для CAD"},
    29: {"name": "Точность изготовления",       "group": "info",     "picogk_hint": "уменьшить voxel_size, упростить геометрию"},
    30: {"name": "Вредные факторы (внешние)",   "group": "safety",   "picogk_hint": "закрыть уязвимые зоны"},
    31: {"name": "Вредные факторы (внутренние)","group": "safety",   "picogk_hint": "убрать зазоры/полости"},
    32: {"name": "Удобство изготовления",       "group": "process",  "picogk_hint": "упростить: одна операция subtract вместо 10"},
    33: {"name": "Удобство эксплуатации",       "group": "process",  "picogk_hint": "добавить крепёжные ушки/отверстия"},
    34: {"name": "Удобство ремонта",            "group": "process",  "picogk_hint": "разборные узлы: принцип 1 «Дробление»"},
    35: {"name": "Адаптивность",                "group": "process",  "picogk_hint": "гибкие/переменные сечения"},
    36: {"name": "Сложность устройства",        "group": "process",  "picogk_hint": "уменьшить число примитивов в build()"},
    37: {"name": "Сложность контроля",          "group": "process",  "picogk_hint": "уменьшить размеры допусков"},
    38: {"name": "Степень автоматизации",       "group": "process",  "picogk_hint": "параметризовать build(pg)"},
    39: {"name": "Производительность",          "group": "process",  "picogk_hint": "уменьшить voxel_size не критично"},
}


# ============================================================
# 40 ПРИНЦИПОВ + PICO GK-МАППИНГ
# ============================================================
PRINCIPLE_PICOGK = {
    1:  {"ops": ["pg.subtract", "pg.add"], "hint": "разбить деталь на N секций через subtract/add"},
    2:  {"ops": ["pg.subtract"], "hint": "вынести «мешающую» часть — вычесть из габарита"},
    3:  {"ops": ["pg.offset", "pg.render_implicit"], "hint": "неоднородная толщина: offset(+) в нагруженных зонах"},
    4:  {"ops": ["pg.render_implicit"], "hint": "асимметричный SDF вместо симметричного примитива"},
    5:  {"ops": ["pg.add", "pg.render_lattice"], "hint": "объединить несколько primitives в композит"},
    6:  {"ops": ["pg.add", "pg.subtract"], "hint": "многофункциональная деталь: полость + крепление"},
    7:  {"ops": ["pg.subtract"], "hint": "матpёшка: вложенные полости"},
    8:  {"ops": ["pg.render_implicit"], "hint": "компенсировать вес геометрией"},
    9:  {"ops": ["pg.offset"], "hint": "преднапряжение через offset(-) в heated zone"},
    10: {"ops": ["pg.add"], "hint": "добавить заранее подготовленный усиливающий элемент"},
    11: {"ops": ["pg.offset"], "hint": "заранее подложить «подушку» — offset(+0.5) локально"},
    12: {"ops": ["pg.render_implicit"], "hint": "эквипотенциальная плоскость: сместить всё к одной Z"},
    13: {"ops": ["pg.subtract"], "hint": "инверсия: то, что было материалом, стало полостью"},
    14: {"ops": ["pg.render_implicit"], "hint": "сфероидальные формы (SDF-smooth) вместо прямых углов"},
    15: {"ops": ["pg.render_implicit"], "hint": "динамическая переменная SDF-функция (адаптивность)"},
    16: {"ops": ["pg.offset"], "hint": "избыточный offset для компенсации допуска"},
    17: {"ops": ["pg.render_implicit"], "hint": "многослойная/наклонная структура через SDF"},
    18: {"ops": ["pg.render_lattice"], "hint": "вибрационная разгрузка через латтис-структуру"},
    19: {"ops": ["pg.render_lattice"], "hint": "периодический латтис с заданным шагом"},
    20: {"ops": ["pg.render_implicit"], "hint": "непрерывное сечение без скачков"},
    21: {"ops": ["pg.offset"], "hint": "быстрая операция offset вместо медленного render_implicit"},
    22: {"ops": ["pg.render_lattice"], "hint": "использовать «вредную» пустоту как латтис-ячейку"},
    23: {"ops": ["pg.render_implicit"], "hint": "обратная связь через форму (SDF зависит от координат)"},
    24: {"ops": ["pg.capsule", "pg.add"], "hint": "промежуточная капсула-связка между двумя частями"},
    25: {"ops": ["pg.offset"], "hint": "самоусиливающаяся структура: offset повторяется"},
    26: {"ops": ["pg.copy"], "hint": "копия детали для симметричной половины"},
    27: {"ops": ["pg.subtract"], "hint": "упрощённая недолговечная деталь (быстрее печатать)"},
    28: {"ops": ["pg.render_implicit"], "hint": "заменить механический элемент SDF-поверхностью"},
    29: {"ops": ["pg.capsule"], "hint": "пневматический/жидкостный канал — капсула"},
    30: {"ops": ["pg.render_implicit"], "hint": "тонкая гибкая оболочка через SDF"},
    31: {"ops": ["pg.render_lattice"], "hint": "пористая структура через латтис"},
    32: {"ops": ["pg.add"], "hint": "цвет/маркировка — отдельная геометрия-индикатор"},
    33: {"ops": ["pg.render_implicit"], "hint": "однородный материал — та же SDF-функция для всех частей"},
    34: {"ops": ["pg.subtract"], "hint": "отбраковка/регенерация — вычесть износостойкий слой"},
    35: {"ops": ["pg.render_implicit"], "hint": "изменение физико-химических параметров — градиент плотности SDF"},
    36: {"ops": ["pg.render_implicit"], "hint": "фазовый переход — резкая граница в SDF"},
    37: {"ops": ["pg.offset"], "hint": "тепловое расширение — offset(+) для компенсации"},
    38: {"ops": ["pg.render_implicit"], "hint": "окислитель — внутренние каналы для воздуха"},
    39: {"ops": ["pg.subtract"], "hint": "инертная среда — закрытая полость"},
    40: {"ops": ["pg.render_lattice", "pg.lattice_add_beam"], "hint": "композит — латтис с рёбрами в направлении нагрузки"},
}


# ============================================================
# МАТРИЦА ПРОТИВОРЕЧИЙ: загружается из triz_matrix.json
# Источник: Antropocosmist/triz-engineering-solver (MIT)
# ============================================================
def _load_matrix():
    """Загружает полную матрицу 39×39 из JSON. Возвращает dict[(int,int)] = [int,...]."""
    json_path = _os.path.join(_os.path.dirname(__file__), "triz_matrix.json")
    if not _os.path.exists(json_path):
        return {}
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = _json.load(f)
    except Exception:
        return {}

    # Пробуем несколько возможных форматов JSON
    cells = data.get("cells") or data.get("matrix") or data
    matrix = {}
    if isinstance(cells, dict):
        for key, principles in cells.items():
            if not isinstance(principles, list):
                continue
            try:
                if isinstance(key, str):
                    a, b = key.replace(" ", "").split(",")
                else:
                    a, b = key
                matrix[(int(a), int(b))] = [int(p) for p in principles]
            except Exception:
                continue
    return matrix


CONTRADICTION_MATRIX = _load_matrix()


# ============================================================
# УТИЛИТЫ
# ============================================================
def get_parameter(num: int) -> dict:
    return ENGINEERING_PARAMETERS.get(num, {})


def get_principle(num: int) -> dict:
    return PRINCIPLE_PICOGK.get(num, {})


def get_principles_for(improve: int, worsen: int) -> list:
    """Прямой порядок, потом обратный. Возвращает номера принципов."""
    return (CONTRADICTION_MATRIX.get((improve, worsen))
            or CONTRADICTION_MATRIX.get((worsen, improve))
            or [])


def list_cad_parameters() -> list:
    """Параметры, для которых есть PicoGK-подсказка."""
    return [n for n, p in ENGINEERING_PARAMETERS.items() if p.get("picogk_hint")]
