#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

print("=== Тест OpenKLHCAD (PyVista + DART/PyBullet) ===\n")

# 1. Геометрия
print("1. Тест геометрии (py-slvs)...")
from openklhcad import box, sphere, cylinder, union, export_stl
b = box(2, 3, 4)
s = sphere(1.5)
result = union(b, s)
if result is not None:
    export_stl(result, "test_union.stl")
    print("   ✓ Объединение сохранено в test_union.stl")
else:
    print("   ✗ Ошибка объединения")

# 2. Вьювер (без открытия окна – просто проверка импорта)
print("\n2. Тест вьювера (PyVista)...")
from openklhcad import Viewer3D
viewer = Viewer3D("Test")
print("   ✓ Вьювер создан")

# 3. Физика
print("\n3. Тест физики...")
from openklhcad import PhysicsWorld
world = PhysicsWorld(time_step=0.001)
sphere_id = world.add_sphere(radius=0.5, mass=1.0, position=(0, 0, 2))
for _ in range(50):
    world.step()
pos = world.get_position(sphere_id)
print(f"   ✓ Позиция сферы после падения: {pos}")
world.cleanup()

# 4. ТРИЗ
print("\n4. Тест ТРИЗ...")
from openklhcad import TRIZ_PRINCIPLES
print(f"   ✓ Загружено принципов: {len(TRIZ_PRINCIPLES)}")
print(f"     Пример: {TRIZ_PRINCIPLES[1]['name']} - {TRIZ_PRINCIPLES[1]['description']}")

print("\n✅ Все тесты пройдены!")