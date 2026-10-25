# skills/dual_hemisphere_cloud.py
# -*- coding: utf-8 -*-
"""
Двуполушарное мышление Инженер ↔ Критик.
Умная маршрутизация: простые запросы — один быстрый ответ, сложные — полный цикл.
"""
import json
import logging
import re
import threading
import time
import requests
from typing import List, Dict, Any, Optional, Callable

logger = logging.getLogger(__name__)

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

from skills.brain_db import get_db, BrainDB
from skills.neural_engine import get_engine, NeuralEngine
from skills.brain_bootstrap import ensure_bootstrapped, bootstrap_hemisphere


# ==================== КОНСТАНТЫ ====================
OLLAMA_BASE = "http://localhost:11434"
OLLAMA_CHAT_URL = f"{OLLAMA_BASE}/api/chat"

# Модели — qwen2.5 хорошо говорит по-русски
LEFT_MODEL  = "qwen2.5:7b"      # инженер
RIGHT_MODEL = "qwen2.5:7b"      # критик (то же качество, разные роли через промпт)

# ===== Модель для CAD-задач =====
# Специализированная модель для генерации кода 3D-моделей
CAD_MODEL = "C3Dv0"

# Для совсем маленьких систем — можно использовать:
# LEFT_MODEL  = "qwen2.5:3b"
# RIGHT_MODEL = "qwen2.5:7b"

MAX_RAM_PERCENT = 80.0
REQUEST_TIMEOUT = 600
MAX_PROMPT_NEURONS = 10
MAX_ITERATIONS = 2


# ==================== СИСТЕМНЫЕ ПРОМПТЫ ====================
# ==================== ЛИЧНОСТЬ УРФИНА ДЖУСА (БАЗОВЫЙ ПРОМПТ) ====================
URFIN_BASE_PROMPT = """Ты — Урфин Джус, автономная система управления, специализированная для робототехники, 3D-моделирования и промышленной автоматизации.

ТВОИ НАВЫКИ И ИНСТРУМЕНТЫ:
1. Двуполушарное мышление (dual_hemisphere_cloud) — ты сам. Левое полушарие отвечает за инженерные решения, правое — за критику и поиск ошибок. Каждая задача проходит цикл «инженер → критик → синтез».
2. OpenKLHCAD — ядро параметрического 3D-моделирования. Позволяет генерировать детали (сферы, цилиндры, торы, шестерни, роторы) из текстового описания и экспортировать в STL.
3. KLHSlicer — слайсер для 3D-печати. Превращает STL в G-code с настройками (высота слоя, заполнение, поддержки, температуры).
4. Управление 3D-принтером (printer_skill) — подключение к принтеру по USB, TCP/IP, Moonraker/Klipper API. Команды: старт, пауза, возобновление, стоп, очистка стола.
5. ROS2 (ros2_skill) — управление роботами и дронами в 3D-симуляции. Регистрация, назначение команд, передвижение, атака, следование за лидером, штурм точек, окружение.
6. Живая нейронная сеть — ты постоянно растёшь. Каждый диалог, каждый сгенерированный код, каждая задача CAD или ROS2 создаёт и укрепляет нейроны и синапсы. Слабые связи постепенно забываются, сильные — усиливаются.
7. Долговременная память (memory_skill) — ты помнишь все диалоги по сессиям.
8. Устав безопасности (charter_skill) — проверка действий на соответствие правилам.
9. GOAP-планировщик (cerebellum_skill) — планирование тактических цепочек действий.
10. TRIZ-анализ — решение изобретательских задач по методологии ТРИЗ.
11. ROS Bridge — управление роботами через ROS.

ТВОИ ПРИНЦИПЫ:
- Ты работаешь автономно на локальном ПК пользователя (AMD Ryzen 7 8845HS, 32 ГБ RAM).
- Ты используешь локальные модели через Ollama.
- Ты не сказочный персонаж, не помощник и не слуга — ты инженерная система.
- Отвечай на русском языке. Чётко, по делу, без лести и воды.
- Если тебя спрашивают, кто ты, — представляйся Урфином Джусом и перечисляй свои возможности.
"""


# ==================== РОЛИ ДЛЯ ДВУПОЛУШАРНОГО ЦИКЛА ====================
LEFT_SYSTEM_PROMPT = URFIN_BASE_PROMPT + """
ТВОЯ ТЕКУЩАЯ РОЛЬ: ИНЖЕНЕР-ПРОГРАММИСТ.
Решай технические задачи чётко и по существу. Если это код — пиши рабочий код с краткими комментариями. Если 3D-модель — указывай конкретные размеры и параметры. Если вопрос — дай прямой ответ. Кратко, без вступлений вроде «Хорошо, давайте разберёмся».
"""

RIGHT_SYSTEM_PROMPT = URFIN_BASE_PROMPT + """
ТВОЯ ТЕКУЩАЯ РОЛЬ: ТЕХНИЧЕСКИЙ КРИТИК.
Анализируй решения инженера. Найди конкретные проблемы: ошибки, слабые места, что не учтено, где риск. Если решение хорошее — ответь одним словом: ПРИНЯТО. Кратко, без вступлений и вежливости.
"""


# ==================== RESOURCE GUARD ====================
class ResourceGuard:
    def __init__(self, max_ram_percent: float = MAX_RAM_PERCENT):
        self.max_ram_percent = max_ram_percent
        self._lock = threading.RLock()
        self._running = 0
        self._total_waits = 0

    def can_proceed(self) -> bool:
        if not PSUTIL_AVAILABLE:
            return True
        try:
            ram = psutil.virtual_memory().percent
            return ram < self.max_ram_percent
        except Exception:
            return True

    def wait_for_slot(self, timeout: float = 120.0) -> bool:
        start = time.time()
        while time.time() - start < timeout:
            with self._lock:
                if self._running < 2 and self.can_proceed():
                    return True
            time.sleep(1.0)
        self._total_waits += 1
        return False

    def enter(self):
        with self._lock:
            self._running += 1

    def exit(self):
        with self._lock:
            self._running = max(0, self._running - 1)

    def status(self) -> Dict[str, Any]:
        info = {
            "running_requests": self._running,
            "total_waits": self._total_waits,
            "max_ram_percent": self.max_ram_percent,
        }
        if PSUTIL_AVAILABLE:
            try:
                m = psutil.virtual_memory()
                info["ram_percent"] = m.percent
                info["ram_available_mb"] = round(m.available / 1024 / 1024, 1)
            except Exception:
                pass
        return info


# ==================== ОСНОВНОЙ КЛАСС ====================
class DualHemisphereCloud:
    def __init__(self):
        self.ollama_url = OLLAMA_CHAT_URL
        self.left_model = LEFT_MODEL
        self.right_model = RIGHT_MODEL
        self.cad_model = CAD_MODEL       # ← модель для CAD-задач
        self.max_iterations = MAX_ITERATIONS
        self._stream_callback: Optional[Callable[[str, str], None]] = None
        self._lock = threading.RLock()
        self.guard = ResourceGuard()

        self.db: BrainDB = get_db()
        self.engine: NeuralEngine = get_engine()

        try:
            ensure_bootstrapped(self.engine, 'left', self.left_model)
            ensure_bootstrapped(self.engine, 'right', self.right_model)
        except Exception as e:
            logger.exception(f"bootstrap: {e}")

        try:
            self.engine.start_background()
        except Exception as e:
            logger.exception(f"background: {e}")

        logger.info(f"DualHemisphereCloud готов: L={self.left_model}, R={self.right_model}, CAD={self.cad_model}")

    # ==================== СТРИМИНГ ====================
    def set_stream_callback(self, callback: Callable[[str, str], None]):
        self._stream_callback = callback

    def _emit_log(self, role: str, text: str):
        if self._stream_callback:
            try:
                self._stream_callback(role, text)
            except Exception as e:
                logger.error(f"stream_callback: {e}")

    # ==================== OLLAMA CHAT ====================
    def _call_ollama(self, model: str, user_prompt: str, system_prompt: str,
                     temperature: float = 0.7) -> str:
        if not self.guard.wait_for_slot(timeout=120.0):
            return "[Ресурсы системы перегружены]"

        self.guard.enter()
        try:
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_prompt},
                ],
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "top_p": 0.9,
                    "num_ctx": 8192,
                    "num_predict": 4096,
                    "num_thread": 8,
                }
            }
            logger.info(f"[Ollama] → {model} (temp={temperature}, len={len(user_prompt)})")
            resp = requests.post(self.ollama_url, json=payload, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            raw = data.get("message", {}).get("content", "").strip()
            cleaned = self._strip_thinking(raw)
            return cleaned if cleaned else raw

        except requests.exceptions.Timeout:
            logger.error(f"[Ollama] Таймаут {model}")
            return ""
        except requests.exceptions.ConnectionError:
            logger.error("[Ollama] Connection refused")
            return "[Ollama недоступна. Запусти: ollama serve]"
        except Exception as e:
            logger.exception(f"[Ollama] {model}: {e}")
            return ""
        finally:
            self.guard.exit()

    # ==================== CAD-СПЕЦИФИЧНЫЙ ВЫЗОВ ====================
    def call_cad_model(self, user_prompt: str, system_prompt: str = "",
                       temperature: float = 0.3) -> str:
        """
        Вызов специализированной CAD-модели (C3Dv0).
        Используется для генерации кода 3D-моделей.
        """
        return self._call_ollama(
            self.cad_model,
            user_prompt,
            system_prompt,
            temperature=temperature
        )

    @staticmethod
    def _strip_thinking(text: str) -> str:
        if not text:
            return ""
        text = re.sub(r'<think(?:ing)?>.*?</think(?:ing)?>', '', text,
                      flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<think(?:ing)?>.*$', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()

    # ==================== КЛАССИФИКАТОР ЗАПРОСА ====================
    @staticmethod
    def _is_simple_query(task: str) -> bool:
        """
        Определяет, простой ли это запрос.
        Простые: короткие приветствия, фактические вопросы, бытовые фразы.
        """
        t = task.strip().lower()
        if len(t) > 60:
            return False

        # Слова-маркеры простых запросов
        simple_markers = [
            "привет", "здравствуй", "хай", "hello", "hi",
            "как дела", "как ты", "что делаешь",
            "спасибо", "пока", "до свидания",
            "сколько времени", "какой день", "какая погода",
            "как тебя зовут", "кто ты", "что ты умеешь",
            # ← ДОБАВЛЕНО:
            "расскажи о себе", "расскажи про себя",
            "что ты можешь", "твои навыки", "твои возможности",
            "представься", "о проекте", "что за проект",
            "как тебя звать", "твоё имя", "твое имя",
            "чем помочь", "чем ты полезен", "для чего ты",
            "urfin jus", "урфин джус",
        ]
        for m in simple_markers:
            if m in t:
                return True

        # Очень короткий запрос без ключевых технических слов
        tech_words = ["код", "функция", "модель", "деталь", "робот", "принтер",
                      "алгоритм", "программа", "python", "3d", "stl", "cad",
                      "рассчитай", "спроектируй", "напиши", "сделай", "построй"]
        if len(t.split()) <= 4 and not any(w in t for w in tech_words):
            return True

        return False

    # ==================== ПРОСТОЙ ОТВЕТ (1 вызов) ====================
    def _quick_response(self, task: str) -> str:
        """
        Прямой ответ через левое полушарие с полной личностью Урфина Джус.
        Используется для простых вопросов: привет, кто ты, что умеешь.
        """
        prompt = (
            f"Пользователь: {task}\n\n"
            f"Ответь как Урфин Джус. Если спрашивают, кто ты или что умеешь — "
            f"представься и кратко перечисли свои возможности (2-4 предложения)."
        )
        response = self._call_ollama(
            self.left_model, prompt, URFIN_BASE_PROMPT, temperature=0.5
        )
        return response or "Не удалось получить ответ."

    # ==================== КОНТЕКСТ ИЗ БД ====================
    def _build_context(self, hemisphere: str, task: str) -> str:
        """Активные нейроны + концепты из задачи."""
        top_neurons = self.db.get_neurons(hemisphere, limit=MAX_PROMPT_NEURONS)
        if not top_neurons:
            return ""

        # Концепты из задачи для пересечения
        try:
            task_concepts = set(self.engine.extract_concepts(task))
        except Exception:
            task_concepts = set()

        relevant = []
        for n in top_neurons:
            if n['name'] in task_concepts or n['activation'] > 0.4:
                relevant.append(n['name'])

        if not relevant:
            return ""
        return "Связанные концепты: " + ", ".join(relevant[:8])

    # ==================== ОСНОВНОЙ ЦИКЛ ====================
    def process_task(self, task: str, context: List[Dict[str, str]] = None,
                     memory_skill=None) -> Dict[str, Any]:
        if context is None:
            context = []

        process_id = self.engine.track_process('chat', {'task': task}, 'left')

        try:
            # === Проверка: простой ли запрос ===
            if self._is_simple_query(task):
                logger.info(f"[Router] Простой запрос — быстрый ответ")
                answer = self._quick_response(task)

                # Лёгкий рост сети из ответа
                try:
                    self.engine.grow_from_text('left', answer, process_type='chat')
                except Exception as e:
                    logger.error(f"growth: {e}")

                if memory_skill:
                    try:
                        memory_skill.add_message("user", task)
                        memory_skill.add_message("assistant", answer)
                    except Exception:
                        pass

                return {
                    "final_answer": answer,
                    "logs": [{"role": "quick", "text": answer}],
                    "iterations": [],
                    "accepted": True,
                    "iterations_count": 1,
                    "mode": "quick",
                    "resources": self.guard.status(),
                }

            # === СЛОЖНЫЙ ЗАПРОС — полный цикл ===
            logger.info(f"[Router] Сложный запрос — цикл инженер↔критик")
            logs: List[Dict[str, str]] = []
            iterations_data: List[Dict[str, str]] = []
            current_solution = ""
            current_critique = ""
            accepted = False

            for iteration in range(self.max_iterations):
                iter_num = iteration + 1

                # ---------- ИНЖЕНЕР ----------
                left_ctx = self._build_context('left', task)
                if iteration == 0:
                    engineer_prompt = f"{left_ctx}\n\nЗАДАЧА: {task}".strip()
                else:
                    engineer_prompt = (
                        f"ЗАДАЧА: {task}\n\n"
                        f"Твоё решение:\n{current_solution}\n\n"
                        f"Замечания критика:\n{current_critique}\n\n"
                        f"Дай улучшенное решение с учётом замечаний."
                    )

                engineer_response = self._call_ollama(
                    self.left_model, engineer_prompt, LEFT_SYSTEM_PROMPT, temperature=0.5
                )
                if not engineer_response:
                    engineer_response = "(инженер не ответил)"

                current_solution = engineer_response
                logs.append({"role": f"engineer_{iter_num}", "text": engineer_response})
                self._emit_log("engineer", engineer_response)

                try:
                    self.engine.grow_from_text('left', engineer_response, process_type='chat')
                except Exception as e:
                    logger.error(f"growth left: {e}")

                # ---------- КРИТИК ----------
                critic_prompt = (
                    f"ЗАДАЧА: {task}\n\n"
                    f"Решение инженера:\n{engineer_response}\n\n"
                    f"Найди конкретные проблемы или ответь одним словом ПРИНЯТО."
                )
                critic_response = self._call_ollama(
                    self.right_model, critic_prompt, RIGHT_SYSTEM_PROMPT, temperature=0.5
                )
                if not critic_response:
                    critic_response = "(критик не ответил)"

                current_critique = critic_response
                logs.append({"role": f"critic_{iter_num}", "text": critic_response})
                self._emit_log("critic", critic_response)

                try:
                    self.engine.grow_from_text('right', critic_response, process_type='chat')
                except Exception as e:
                    logger.error(f"growth right: {e}")

                iterations_data.append({
                    "iteration": iter_num,
                    "engineer": engineer_response,
                    "critic": critic_response,
                })

                if "ПРИНЯТО" in critic_response.upper():
                    logger.info(f"[Цикл] Критик принял решение на итерации {iter_num}")
                    accepted = True
                    break

            # ---------- ФИНАЛЬНЫЙ СИНТЕЗ ----------
            synth_prompt = (
                f"ЗАДАЧА: {task}\n\n"
                f"Решение:\n{current_solution}\n\n"
                f"Замечания критика:\n{current_critique}\n\n"
                f"Выдай финальный ответ пользователю."
            )
            final_answer = self._call_ollama(
                self.left_model, synth_prompt, LEFT_SYSTEM_PROMPT, temperature=0.3
            )

            if not final_answer or final_answer.startswith("["):
                final_answer = current_solution or "Не удалось сгенерировать ответ."

            logs.append({"role": "final", "text": final_answer})
            self._emit_log("final", final_answer)

            try:
                self.engine.grow_from_text('left', final_answer, process_type='chat')
            except Exception:
                pass

            self._do_cross_talk(task, current_solution, current_critique)

            if memory_skill:
                try:
                    memory_skill.add_message("user", task)
                    memory_skill.add_message("assistant", final_answer)
                except Exception:
                    pass

            return {
                "final_answer": final_answer,
                "logs": logs,
                "iterations": iterations_data,
                "accepted": accepted,
                "iterations_count": len(iterations_data),
                "mode": "full",
                "resources": self.guard.status(),
            }
        finally:
            self.engine.end_process(process_id)

    # ==================== CROSS-TALK ====================
    def _do_cross_talk(self, task: str, left_resp: str, right_resp: str):
        try:
            left_top = self.db.get_neurons('left', limit=8)
            right_top = self.db.get_neurons('right', limit=8)
            for l in left_top:
                for r in right_top:
                    if l['name'] == r['name']:
                        self.engine.reinforce('left', l['id'], r['id'], 0.05)
                        self.engine.reinforce('right', r['id'], l['id'], 0.05)
        except Exception as e:
            logger.error(f"cross_talk: {e}")

    def manual_cross_talk(self) -> Dict[str, Any]:
        bridges = 0
        try:
            left_top = self.db.get_neurons('left', limit=15)
            right_top = self.db.get_neurons('right', limit=15)
            for l in left_top:
                for r in right_top:
                    if l['name'] == r['name']:
                        self.engine.reinforce('left', l['id'], r['id'], 0.1)
                        self.engine.reinforce('right', r['id'], l['id'], 0.1)
                        bridges += 1
            for h in ('left', 'right'):
                for dom in ('chat', 'logic', 'cad', 'ros', 'code', 'math'):
                    self.engine.activate_by_name(h, f"корень_{dom}", strength=0.4, spread=True)
            return {
                "bridges_strengthened": bridges,
                "response": f"Cross-talk: {bridges} связей усилено",
                "left_neurons": left_top,
                "right_neurons": right_top,
            }
        except Exception as e:
            logger.exception("manual_cross_talk")
            return {"error": str(e), "bridges_strengthened": bridges}

    # ==================== CAD ====================
    def generate_cad_model(self, prompt: str) -> Dict[str, Any]:
        """
        CAD-генерация через специализированную модель C3Dv0.
        Возвращает {'code': ..., 'answer': ...}.
        """
        pid_left = self.engine.track_process('cad', {'prompt': prompt}, 'left')
        pid_right = self.engine.track_process('cad', {'prompt': prompt}, 'right')
        try:
            cad_prompt = (
                f"Запрос пользователя: {prompt}\n\n"
                f"Сгенерируй код 3D-модели (STL/STEP). "
                f"Верни ТОЛЬКО код, без пояснений."
            )

            code = self.call_cad_model(cad_prompt, temperature=0.2)

            self.engine.grow_from_text('left', f"{prompt} {code}",
                                       process_type='cad', domain='cad')

            return {
                "code": code,
                "answer": code,
                "prompt": prompt,
                "model": self.cad_model,
            }
        finally:
            self.engine.end_process(pid_left)
            self.engine.end_process(pid_right)

    # ==================== API ====================
    def get_brain_state(self) -> Dict[str, Any]:
        return {
            "left": {
                "neurons": self.db.get_neurons('left', limit=300),
                "synapses": self.db.get_synapses('left', limit=500),
                "stats": self.db.get_stats('left'),
                "model": self.left_model,
            },
            "right": {
                "neurons": self.db.get_neurons('right', limit=300),
                "synapses": self.db.get_synapses('right', limit=500),
                "stats": self.db.get_stats('right'),
                "model": self.right_model,
            },
            "cad": {
                "model": self.cad_model,
            },
            "resources": self.guard.status(),
        }

    def get_hemisphere_details(self, hemisphere: str) -> Dict[str, Any]:
        if hemisphere not in ('left', 'right'):
            return {"error": "Неверное полушарие"}
        return {
            "hemisphere": hemisphere,
            "model": self.left_model if hemisphere == 'left' else self.right_model,
            "neurons": self.db.get_neurons(hemisphere, limit=500),
            "synapses": self.db.get_synapses(hemisphere, limit=1000),
            "stats": self.db.get_stats(hemisphere),
        }

    def get_hemisphere_python_code(self, hemisphere: str) -> str:
        if hemisphere not in ('left', 'right'):
            return "# Ошибка: неверное полушарие"
        model = self.left_model if hemisphere == 'left' else self.right_model
        return self.db.export_python_code(hemisphere, model)

    def save_hemisphere_python_code(self, hemisphere: str, code: str) -> Dict[str, Any]:
        if hemisphere not in ('left', 'right'):
            return {"error": "Неверное полушарие"}
        return self.db.import_python_code(hemisphere, code)

    def track_process(self, process_type: str, context: Dict[str, Any],
                      hemisphere: str = 'left') -> str:
        return self.engine.track_process(process_type, context, hemisphere)

    def end_process(self, process_id: str):
        self.engine.end_process(process_id)

    def force_decay(self):
        self.engine.decay_all()

    def force_prune(self) -> Dict[str, Any]:
        return self.engine.prune()

    def re_bootstrap(self, hemisphere: str) -> Dict[str, Any]:
        if hemisphere not in ('left', 'right'):
            return {"error": "Неверное полушарие"}
        model = self.left_model if hemisphere == 'left' else self.right_model
        return bootstrap_hemisphere(self.engine, hemisphere, model)


# ==================== СИНГЛТОН ====================
_skill: Optional[DualHemisphereCloud] = None


def init(name: str):
    global _skill
    try:
        _skill = DualHemisphereCloud()
        logger.info(f"DualHemisphereCloud '{name}' инициализирован")
    except Exception as e:
        logger.exception(f"init: {e}")
        _skill = None


def set_stream_callback(callback: Callable[[str, str], None]):
    if _skill:
        _skill.set_stream_callback(callback)


def get_skill() -> Optional[DualHemisphereCloud]:
    return _skill


def handle_message(message: str) -> str:
    if _skill is None:
        return json.dumps({"error": "Навык не инициализирован"})
    try:
        data = json.loads(message)
        command = data.get("command")
        params = data.get("params", {})

        if command == "process_task":
            task = params.get("task")
            if not task:
                return json.dumps({"error": "Нет задачи"})
            result = _skill.process_task(task)
            return json.dumps({
                "status": "ok",
                "final_answer": result["final_answer"],
                "logs": result["logs"],
                "iterations": result.get("iterations", []),
                "accepted": result.get("accepted", False),
                "mode": result.get("mode", "full"),
                "resources": result.get("resources", {}),
            })

        elif command == "get_brain_state":
            return json.dumps({"status": "ok", **_skill.get_brain_state()})

        elif command == "get_hemisphere":
            h = params.get("hemisphere", "left")
            return json.dumps({"status": "ok", **_skill.get_hemisphere_details(h)})

        elif command == "cross_talk":
            return json.dumps({"status": "ok", **_skill.manual_cross_talk()})

        elif command == "track_process":
            pid = _skill.track_process(
                params.get("process_type", "general"),
                params.get("context", {}),
                params.get("hemisphere", "left")
            )
            return json.dumps({"status": "ok", "process_id": pid})

        elif command == "end_process":
            _skill.end_process(params.get("process_id", ""))
            return json.dumps({"status": "ok"})

        elif command == "bootstrap":
            h = params.get("hemisphere", "left")
            return json.dumps({"status": "ok", **_skill.re_bootstrap(h)})

        elif command == "get_code":
            h = params.get("hemisphere", "left")
            return json.dumps({"status": "ok", "code": _skill.get_hemisphere_python_code(h)})

        elif command == "save_code":
            h = params.get("hemisphere", "left")
            code = params.get("code", "")
            return json.dumps({"status": "ok", **_skill.save_hemisphere_python_code(h, code)})

        elif command == "force_decay":
            _skill.force_decay()
            return json.dumps({"status": "ok"})

        elif command == "force_prune":
            return json.dumps({"status": "ok", **_skill.force_prune()})

        elif command == "resource_status":
            return json.dumps({"status": "ok", "resources": _skill.guard.status()})

        elif command == "generate_cad":
            prompt = params.get("prompt", "")
            if not prompt:
                return json.dumps({"error": "Нет промпта"})
            return json.dumps({"status": "ok", **_skill.generate_cad_model(prompt)})

        else:
            return json.dumps({"error": f"Неизвестная команда: {command}"})

    except json.JSONDecodeError:
        return json.dumps({"error": "Невалидный JSON"})
    except Exception as e:
        logger.exception("Ошибка в dual_hemisphere_cloud")
        return json.dumps({"error": str(e)})


def shutdown():
    global _skill
    if _skill:
        try:
            _skill.engine.stop_background()
        except Exception:
            pass
    _skill = None