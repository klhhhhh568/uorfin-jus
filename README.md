# 🤖 Урфин Джус (urfin Jus)

**Открытая система управления производством и роем роботов.**

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

> Этот проект — инструмент для тех, кто создаёт, а не для тех, кто покупает.
> Он создан, чтобы служить тому, кто его собрал и настроил, а не тому, кто платит.
> Это не просто софт. Это твой цифровой соратник, твой «Урфин Джус».
> Проект сделан на Ubuntu 22.04.

**Версия:** 1.0.0 (стабильная)

**Специализация:** Робототехника и широкая промышленная автоматизация.
**Основы:** Формальная логика, диалектический материализм, инженерный расчёт.

---

### 🚀 Что он умеет уже сейчас

- **Проектировать 3D-детали:** генеративный CAD на ядре **PicoGK** (LEAP 71). По текстовому промпту на русском строит воксельные модели и экспортирует STL.
- **Управлять производством:** 3D-принтеры (Klipper/Moonraker/USB), эмуляция ЧПУ, генерация G-кода.
- **Управлять роботами:** ROS2 для координации роботов, дронов и ИИ-агентов.
- **Думать и спорить:** Двухполушарный ИИ (Инженер ↔ Критик) для поиска ошибок и стратегического планирования.
- **Тактически планировать:** GOAP-мозжечок для быстрых автономных действий.
- **Долговременная память:** помнит контекст, учится на ошибках, можно очистить память.
- **Живая нейронная сеть:** растёт с каждым диалогом, слабые связи забываются, сильные — усиливаются.

---

### 🏗️ Архитектура
Electron UI (Three.js) ← 3D-мозг, окна, чат
↓ WebSocket
Flask backend (web_server.py) ← оркестратор, 13 навыков
↓
Dual Hemisphere Cloud ← инженер + критик (qwen2.5:7b)
├─→ CAD Generation ← qwen2.5-coder:7b → PicoGK → STL
├─→ Printer Skill ← Klipper / Moonraker
├─→ ROS2 Skill ← симуляция роботов
├─→ Memory Skill ← SQLite сессии
├─→ Neural Engine ← живая нейросеть + brain.db
└─→ ...
text


---

### 🎨 CAD-ядро: PicoGK

**PicoGK 26.2.0** — компактное воксельное геометрическое ядро от LEAP 71.

**Что даёт:**
- Воксельные булевы операции (точность 0.1%)
- Lattice-структуры (решётки для облегчённых деталей)
- Импилицит-моделирование через SDF-функции
- Работает **локально на Linux** (собран из исходников)
- Python ctypes binding (`skills/picogk_binding.py`)
- Subprocess-изоляция (`skills/picogk_worker.py`) — защита от segfault

**Примеры запросов:**

| Промпт | Что построит |
|---|---|
| `сфера радиусом 10` | Сфера R=10 мм |
| `куб 30x30x30` | Куб 30×30×30 мм |
| `полая сфера радиус 15 толщина 2` | Полая сфера |
| `шар на ножке высотой 100` | Сфера + стойка |
| `решётка из 4 сфер соединённых балками` | Lattice-структура |
| `кронштейн 50x30 с крепёжными отверстиями` | Композиция из примитивов |

---

### 🛠️ Быстрый старт

**Требования:**
- Ubuntu 22.04+ x86_64
- 16 ГБ RAM (рекомендуется 32)
- Ollama с моделями `qwen2.5:7b`, `qwen2.5-coder:7b`, `bge-m3`
- `libpicogk.so` в `/usr/local/lib/` (инструкция по сборке в пункте 5)

**1. Клонируй репозиторий:**

```bash
git clone https://github.com/klhhhhh568/urfin-jus.git
cd urfin-jus
2. Создай виртуальное окружение:
bash

python3 -m venv urfin_env
source urfin_env/bin/activate

3. Установи зависимости:
bash

pip install -r requirements.txt

4. Установи Ollama и модели:
bash

# Если Ollama ещё не установлена:
curl -fsSL https://ollama.com/install.sh | sh

# Запусти сервис:
ollama serve &

# Скачай модели:
ollama pull qwen2.5:7b
ollama pull qwen2.5-coder:7b
ollama pull bge-m3

5. Собери PicoGK (одноразово, ~30 минут).

PicoGK от LEAP 71 — воксельное ядро. Готового Linux-бинарника нет,
только сборка из исходников с патчами под Clang 14.

Зависимости:
bash

sudo apt install -y build-essential cmake clang \
    libopenvdb-dev libtbb-dev libblosc-dev

Клонирование (--depth=1 — чтобы быстрее по сети):
bash

cd ~
git clone --recursive --depth=1 https://github.com/leap71/PicoGK.git
cd PicoGK/PicoGKRuntime

Патчи (обязательны — без них make упадёт под Clang 14):

    В CMakeLists.txt: cmake_minimum_required(VERSION 3.25.1) → (VERSION 3.22)

    В CMakeLists.txt после project(...): set(CMAKE_POSITION_INDEPENDENT_CODE ON)

    В Source/PicoGKTrace.h: все oMS → oMS.count()

    В Source/PicoGKVdbField.h: TFieldType::Ptr → typename TFieldType::Ptr

    Симлинк: ln -sf /usr/include/Imath ext/imath

Сборка и установка:
bash

cd ~/PicoGK/PicoGKRuntime
mkdir -p build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release \
         -DCMAKE_POSITION_INDEPENDENT_CODE=ON \
         -DCMAKE_CXX_COMPILER=clang++ \
         -DCMAKE_C_COMPILER=clang
make -j$(nproc)

# после сборки появится build/lib/picogk.so (~19 МБ)
sudo cp build/lib/picogk.so /usr/local/lib/picogk.so
sudo ln -sf /usr/local/lib/picogk.so /usr/local/lib/libpicogk.so
sudo ldconfig

Проверка интеграции:
bash

cd ~/urfin-jus/urfin_jus
source ../urfin_env/bin/activate
python3 -c "
from skills.picogk_binding import get_picogk
pg = get_picogk(voxel_size_mm=0.5)
s = pg.sphere((0, 0, 0), 10.0)
print(f'valid={pg.is_valid(s)}, vol={pg.volume(s):.2f}')
"
# Ожидание: valid=True, vol≈4188.79

6. Собери бэкенд:
bash

cd urfin_jus/web
pyinstaller run_backend.spec --clean

7. Запусти систему:
bash

cd urfin-jus
./run.sh

Или вручную:
bash

cd urfin_jus/electron
npm install   # один раз
npm start

📁 Структура проекта
text

urfin-jus/
├── urfin_env/              ← Python venv
├── urfin_jus/
│   ├── web/                ← Flask backend
│   │   ├── web_server.py
│   │   ├── run_backend.spec
│   │   └── dist/run_backend
│   ├── electron/           ← UI
│   │   ├── main.js
│   │   └── package.json
│   ├── skills/             ← 13 навыков
│   │   ├── picogk_binding.py    ← ctypes PicoGK
│   │   ├── picogk_worker.py     ← изолированный worker
│   │   ├── cad_generation.py    ← LLM → код → PicoGK
│   │   ├── dual_hemisphere_cloud.py
│   │   ├── brain_db.py
│   │   └── ...
│   ├── data/brain.db       ← SQLite нейросеть
│   └── urfin_charter.yaml ← Устав + system prompt
└── run.sh                  ← Единый запуск

🔧 Переменные окружения

Опциональные:
bash

# Путь к Python для PicoGK-worker (по умолчанию ищется автоматически)
export URFIN_CAD_PYTHON=/path/to/urfin_env/bin/python3

# Если Ollama слушает не стандартный порт
export OLLAMA_BASE_URL=http://localhost:11434

Примечание: ros2 не изменялся с прошлого релиза, его обновление будет в следующем релзе.

📜 Лицензия

GPL v3 — см. LICENSE.

PicoGK распространяется по лицензии Apache 2.0. Линковка с нашим проектом
идёт через ctypes (динамическая, без включения исходников PicoGK в репозиторий),
поэтому PicoGK не становится производным произведением, а Urfin Jus не нарушает
условия Apache 2.0.
🙏 Благодарности

    LEAP 71 — за открытие PicoGK

    OpenVDB — за воксельную библиотеку

    Ollama — за локальный запуск LLM

    Alibaba Qwen — за модели qwen2.5:7b и qwen2.5-coder:7b

    BAAI — за модель bge-m3 (эмбеддинги 1024-dim)

Computational Engineering will profoundly change our physical world in the years ahead.