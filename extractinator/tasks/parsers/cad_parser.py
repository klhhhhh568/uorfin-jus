from pydantic import BaseModel, Field
from typing import Optional, List

class Dimensions(BaseModel):
    radius: Optional[float] = Field(None, description="Радиус в мм")
    diameter: Optional[float] = Field(None, description="Диаметр в мм")
    height: Optional[float] = Field(None, description="Высота в мм")
    length: Optional[float] = Field(None, description="Длина в мм")
    width: Optional[float] = Field(None, description="Ширина в мм")
    thickness: Optional[float] = Field(None, description="Толщина в мм")
    teeth: Optional[int] = Field(None, description="Количество зубьев")
    module: Optional[float] = Field(None, description="Модуль зубчатого колеса")
    hole_diameter: Optional[float] = Field(None, description="Диаметр отверстия в мм")
    holes_count: Optional[int] = Field(None, description="Количество отверстий")

class OutputParser(BaseModel):
    part_type: str = Field(..., description="Тип детали: сфера, куб, цилиндр, шестерня, фланец, вал, ротор, статор и т.д.")
    dimensions: Dimensions
    features: List[str] = Field(default_factory=list, description="Особенности: отверстия, пазы, фаски")
    expected_bbox_mm: Optional[List[float]] = Field(None, description="Ожидаемые габариты [X, Y, Z] в мм")
    notes: Optional[str] = Field(None, description="Дополнительные замечания")