# skills/prompt_extractor.py
# -*- coding: utf-8 -*-
"""
Real-time извлечение структурированных параметров из промптов через Pydantic + Ollama.
Никаких заранее прописанных промптов. Всё работает на лету.
"""
import json
import logging
import requests
from typing import Optional, List
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

OLLAMA_URL = "http://localhost:11434"
EXTRACTOR_MODEL = "qwen2.5:7b"


# ============================================================
# PYDANTIC-СХЕМЫ (это и есть "понимание" промпта)
# ============================================================
class Dimensions(BaseModel):
    """Размеры детали в миллиметрах."""
    radius: Optional[float] = Field(None, description="Радиус в мм")
    diameter: Optional[float] = Field(None, description="Диаметр в мм")
    outer_diameter: Optional[float] = Field(None, description="Внешний диаметр в мм")
    inner_diameter: Optional[float] = Field(None, description="Внутренний диаметр в мм")
    height: Optional[float] = Field(None, description="Высота в мм")
    length: Optional[float] = Field(None, description="Длина в мм")
    width: Optional[float] = Field(None, description="Ширина в мм")
    thickness: Optional[float] = Field(None, description="Толщина в мм")
    teeth: Optional[int] = Field(None, description="Количество зубьев")
    module: Optional[float] = Field(None, description="Модуль зубчатого колеса")
    slots: Optional[int] = Field(None, description="Количество пазов")
    hole_diameter: Optional[float] = Field(None, description="Диаметр отверстия в мм")
    holes_count: Optional[int] = Field(None, description="Количество отверстий")
    wall_thickness: Optional[float] = Field(None, description="Толщина стенки в мм")


class CADSpec(BaseModel):
    """Извлечённое ТЗ из промпта пользователя."""
    part_type: str = Field(
        ...,
        description="Тип детали: сфера, куб, цилиндр, конус, тор, шестерня, фланец, "
                    "вал, ротор, статор, втулка, кронштейн, пластина, крышка, "
                    "труба, стакан, шкив, муфта, или 'сложная' для нестандартных"
    )
    dimensions: Dimensions = Field(
        default_factory=Dimensions,
        description="Размеры детали"
    )
    features: List[str] = Field(
        default_factory=list,
        description="Особенности: 'центральное отверстие', 'фаски', 'пазы', 'массив отверстий'"
    )
    expected_bbox_mm: Optional[List[float]] = Field(
        None,
        description="Ожидаемые габариты [X, Y, Z] в мм. Для шнестерни: (teeth+2)*module по X и Y"
    )
    confidence: float = Field(
        default=1.0,
        description="Уверенность извлечения от 0.0 до 1.0"
    )
    notes: Optional[str] = Field(None, description="Замечания или допущения")


# ============================================================
# ИЗВЛЕКАТЕЛЬ
# ============================================================
class PromptExtractor:
    """
    Real-time извлечение ТЗ из промпта.
    Использует Ollama /api/chat со схемой JSON + Pydantic-валидацию.
    """

    SYSTEM_PROMPT = """Ты — CAD-инженер. Разбери запрос пользователя на русском языке и извлеки структурированное техническое задание.

ПРАВИЛА:
1. Если размер не указан — оставь его null. Не выдумывай.
2. part_type — одна из: сфера, куб, цилиндр, конус, тор, шестерня, фланец, вал, ротор, статор, втулка, кронштейн, пластина, крышка, труба, стакан, шкив, муфта, сложная.
3. Если деталь сложная и не подходит ни под один тип — ставь "сложная".
4. Для шестерни: диаметр ≈ (teeth + 2) × module. Это expected_bbox_mm по X и Y.
5. Все размеры в миллиметрах.
6. features — список особенностей, которые должны быть в модели.
7. confidence: 1.0 если всё ясно, 0.5-0.8 если есть догадки, 0.3 если совсем непонятно.

ПРИМЕРЫ:
"сфера радиусом 10" → {part_type: "сфера", dimensions: {radius: 10}, expected_bbox_mm: [20, 20, 20]}
"шестерня на 16 зубьев модуль 2 высота 6" → {part_type: "шестерня", dimensions: {teeth: 16, module: 2, height: 6}, expected_bbox_mm: [36, 36, 6]}
"статор внешний 100 внутренний 50 высота 20, 16 пазов" → {part_type: "статор", dimensions: {outer_diameter: 100, inner_diameter: 50, height: 20, slots: 16}, expected_bbox_mm: [100, 100, 20]}
"фланец диаметром 100 толщина 8, 6 отверстий М8" → {part_type: "фланец", dimensions: {diameter: 100, thickness: 8, holes_count: 6, hole_diameter: 8}, expected_bbox_mm: [100, 100, 8]}
"вал длиной 200 диаметром 20" → {part_type: "вал", dimensions: {length: 200, diameter: 20}, expected_bbox_mm: [20, 20, 200]}
"""

    def __init__(self, model: str = EXTRACTOR_MODEL, base_url: str = OLLAMA_URL):
        self.model = model
        self.base_url = base_url
        self.schema = CADSpec.model_json_schema()

    # ==================== ГЛАВНЫЙ МЕТОД ====================
    def extract(self, prompt: str, max_retries: int = 2) -> Optional[CADSpec]:
        """
        Извлекает структурированное ТЗ из промпта.
        Возвращает CADSpec или None, если не удалось.
        """
        for attempt in range(1, max_retries + 1):
            logger.info(f"[Extractor] Попытка {attempt}/{max_retries} для: {prompt[:60]}")

            try:
                response = self._call_ollama_with_schema(prompt)
                if not response:
                    continue

                # Pydantic-валидация
                spec = CADSpec.model_validate_json(response)
                logger.info(f"[Extractor] ✅ {spec.part_type} "
                            f"(уверенность={spec.confidence:.2f})")
                return spec

            except Exception as e:
                logger.warning(f"[Extractor] Попытка {attempt} упала: {e}")
                continue

        logger.error(f"[Extractor] Все попытки исчерпаны")
        return None

    # ==================== ВЫЗОВ OLLAMA СО СХЕМОЙ ====================
    def _call_ollama_with_schema(self, prompt: str) -> Optional[str]:
        """
        Отправляет запрос в Ollama с format=schema.
        Ollama гарантирует, что ответ будет валидным JSON по схеме.
        """
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": f"Промпт: {prompt}"}
            ],
            "stream": False,
            "format": self.schema,   # ← ключевое: Ollama вернёт строго по схеме!
            "options": {
                "temperature": 0.1,
                "num_ctx": 4096,
                "num_predict": 1024,
            }
        }

        try:
            r = requests.post(url, json=payload, timeout=120)
            r.raise_for_status()
            data = r.json()
            return data.get("message", {}).get("content", "")
        except requests.exceptions.ConnectionError:
            logger.error("[Extractor] Ollama недоступна")
            return None
        except Exception as e:
            logger.error(f"[Extractor] Ошибка: {e}")
            return None

    # ==================== ПРОВЕРКА ПОЛНОТЫ ====================
    def needs_clarification(self, spec: CADSpec) -> List[str]:
        """
        Проверяет, нужно ли уточнение от пользователя.
        Возвращает список вопросов.
        """
        questions = []

        # Для неизвестных типов — сразу уточняем
        if spec.part_type == "сложная":
            questions.append(
                "Опишите деталь подробнее: из каких простых форм она состоит?"
            )
            return questions

        # Проверяем, есть ли хотя бы один размер
        d = spec.dimensions
        has_size = any([
            d.radius, d.diameter, d.outer_diameter,
            d.height, d.length, d.width, d.thickness,
            d.teeth, d.module,
        ])

        if not has_size:
            questions.append(
                f"Какие размеры у детали '{spec.part_type}'? "
                f"(например, радиус, высота, длина)"
            )

        # Для шестерни без зубьев
        if spec.part_type in ("шестерня", "gear") and not d.teeth:
            questions.append("Сколько зубьев должна иметь шестерня?")

        # Для фланца без отверстий
        if spec.part_type in ("фланец", "flange") and not d.holes_count:
            questions.append("Сколько крепёжных отверстий нужно?")

        # Низкая уверенность
        if spec.confidence < 0.5:
            questions.append(
                "Уточните, пожалуйста, что именно нужно смоделировать?"
            )

        return questions


# ============================================================
# СИНГЛТОН
# ============================================================
_extractor: Optional[PromptExtractor] = None

def get_extractor(model: str = EXTRACTOR_MODEL) -> PromptExtractor:
    global _extractor
    if _extractor is None or _extractor.model != model:
        _extractor = PromptExtractor(model)
    return _extractor