# skills/brain_bootstrap.py
# -*- coding: utf-8 -*-
"""
Алгоритмический бутстрап нейронной сети.
Не хардкодит сеть, а генерирует её из правил: домены × концепты + меж-доменные связи.
"""
import logging
from typing import Dict, List, Tuple, Any
from skills.neural_engine import NeuralEngine

logger = logging.getLogger(__name__)

# === СЕМЕНА: домены и их концепты ===
# Это не "сеть", а "словарные корни". Из них АЛГОРИТМ строит сеть.
DOMAIN_SEEDS: Dict[str, List[str]] = {
    "chat":    ["диалог", "общение", "вопрос", "ответ", "контекст", "интонация",
                "смысл", "реплика", "тема", "стиль"],
    "logic":   ["логика", "вывод", "доказательство", "противоречие",
                "анализ", "синтез", "гипотеза", "аксиома", "парадокс"],
    "math":    ["математика", "число", "формула", "уравнение",
                "геометрия", "алгебра", "интеграл", "матрица", "вектор"],
    "code":    ["код", "алгоритм", "функция", "переменная",
                "структура", "отладка", "рефакторинг", "модуль", "класс"],
    "cad":     ["модель", "деталь", "размер", "форма",
                "эскиз", "параметр", "сборка", "поверхность", "тело",
                "сфера", "цилиндр", "куб", "конус", "тор"],
    "ros":     ["робот", "движение", "сенсор", "команда",
                "траектория", "координата", "карта", "навигация", "лидер"],
    "print":   ["принтер", "слой", "экструзия", "сопло",
                "стол", "пластик", "температура", "адгезия", "поддержка"],
    "slicer":  ["слайсинг", "траектория", "инфилл", "периметр",
                "заполнение", "высота_слоя", "gcode"],
    "vision":  ["изображение", "распознавание", "объект", "сцена",
                "камера", "признак", "классификация", "детекция"],
    "physics": ["физика", "симуляция", "столкновение", "масса",
                "ускорение", "трение", "гравитация", "импульс"],
    "safety":  ["безопасность", "ограничение", "риск", "проверка",
                "запрет", "допуск", "устав"],
}

# === ПРАВИЛА МЕЖ-ДОМЕННЫХ СВЯЗЕЙ ===
# Каждый домен связан с "родственными". Это граф, а не список пар.
DOMAIN_ADJACENCY: Dict[str, List[Tuple[str, float]]] = {
    "chat":    [("logic", 0.6), ("safety", 0.5)],
    "logic":   [("math", 0.7), ("code", 0.6), ("chat", 0.5)],
    "math":    [("logic", 0.7), ("code", 0.6), ("cad", 0.5), ("physics", 0.5)],
    "code":    [("logic", 0.6), ("math", 0.5), ("cad", 0.6), ("ros", 0.5)],
    "cad":     [("math", 0.6), ("code", 0.5), ("print", 0.6), ("physics", 0.5)],
    "ros":     [("code", 0.6), ("vision", 0.6), ("safety", 0.7), ("physics", 0.5)],
    "print":   [("cad", 0.7), ("slicer", 0.8), ("physics", 0.4)],
    "slicer":  [("print", 0.8), ("cad", 0.5)],
    "vision":  [("ros", 0.6), ("logic", 0.4)],
    "physics": [("math", 0.5), ("cad", 0.5), ("ros", 0.5)],
    "safety":  [("chat", 0.5), ("ros", 0.7), ("code", 0.5)],
}

# === ОБЩИЕ СВОЙСТВА, применимые к любому домену ===
# Комбинируются с корнем домена (алгоритмически)
COMMON_ATTRS = ["важность", "сложность", "точность", "скорость"]


def _make_root_name(domain: str) -> str:
    return f"корень_{domain}"


def bootstrap_hemisphere(engine: NeuralEngine, hemisphere: str,
                         model_name: str = "deepseek-r1:1.5b",
                         weight_domains: Dict[str, float] = None) -> Dict[str, Any]:
    """
    Алгоритмически строит базовую сеть для полушария.
    weight_domains: необязательный приоритет (0..1) для каждого домена.
    """
    db = engine.db
    weight_domains = weight_domains or {}

    # === 1. Корневые нейроны доменов ===
    domain_root_ids: Dict[str, int] = {}
    for domain in DOMAIN_SEEDS:
        root_name = _make_root_name(domain)
        priority = weight_domains.get(domain, 0.5)
        nid = db.add_neuron(
            hemisphere, root_name,
            f"Корень домена '{domain}'",
            neuron_type='domain', domain=domain,
            activation=0.5, base_activation=0.7 + 0.2 * priority,
            is_seed=True
        )
        domain_root_ids[domain] = nid

    # === 2. Концепты домена + автосвязи с корнем ===
    total_concepts = 0
    for domain, words in DOMAIN_SEEDS.items():
        root_id = domain_root_ids[domain]
        # Каждое слово — нейрон
        for w in words:
            nid = db.add_neuron(
                hemisphere, w,
                f"Концепт домена '{domain}'",
                neuron_type='concept', domain=domain,
                activation=0.4, base_activation=0.6,
                is_seed=True
            )
            if nid > 0:
                # root → concept, concept → root
                db.add_synapse(hemisphere, root_id, nid, weight=0.65)
                db.add_synapse(hemisphere, nid, root_id, weight=0.45)
                total_concepts += 1

        # Свойства: domain_attr концепты (алгоритмически)
        for attr in COMMON_ATTRS:
            attr_name = f"{domain}_{attr}"
            nid_attr = db.add_neuron(
                hemisphere, attr_name,
                f"Свойство '{attr}' домена '{domain}'",
                neuron_type='attribute', domain=domain,
                activation=0.2, base_activation=0.4,
                is_seed=True
            )
            if nid_attr > 0:
                db.add_synapse(hemisphere, root_id, nid_attr, weight=0.35)

    # === 3. Меж-доменные связи ===
    total_cross = 0
    for src_domain, targets in DOMAIN_ADJACENCY.items():
        src_root = domain_root_ids[src_domain]
        for tgt_domain, w in targets:
            tgt_root = domain_root_ids.get(tgt_domain)
            if tgt_root:
                db.add_synapse(hemisphere, src_root, tgt_root, weight=w)
                total_cross += 1

    # === 4. Внутри домена: концепты связываются в цепочку Hebbian-подобно ===
    # (простой алгоритм: каждый концепт связан со следующим по порядку)
    for domain, words in DOMAIN_SEEDS.items():
        for i in range(len(words) - 1):
            n1 = db.find_neuron(hemisphere, words[i])
            n2 = db.find_neuron(hemisphere, words[i + 1])
            if n1 and n2:
                db.add_synapse(hemisphere, n1['id'], n2['id'], weight=0.25)
                db.add_synapse(hemisphere, n2['id'], n1['id'], weight=0.2)

    stats = db.get_stats(hemisphere)
    logger.info(f"Bootstrap {hemisphere}: {stats}")
    return {
        "hemisphere": hemisphere,
        "domains": len(DOMAIN_SEEDS),
        "concepts": total_concepts,
        "cross_links": total_cross,
        "stats": stats,
    }


def is_bootstrapped(engine: NeuralEngine, hemisphere: str) -> bool:
    stats = engine.db.get_stats(hemisphere)
    return stats['neurons'] >= 30


def ensure_bootstrapped(engine: NeuralEngine, hemisphere: str,
                        model_name: str = "deepseek-r1:1.5b") -> Dict[str, Any]:
    """Если сеть полушария пустая — запускает bootstrap. Иначе — no-op."""
    if is_bootstrapped(engine, hemisphere):
        return {"skipped": True, "stats": engine.db.get_stats(hemisphere)}
    return bootstrap_hemisphere(engine, hemisphere, model_name)