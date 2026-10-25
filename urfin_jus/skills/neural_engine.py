# skills/neural_engine.py
# -*- coding: utf-8 -*-
"""
Живая нейронная сеть. Алгоритмы роста, распада, обучения.
"""
import re, time, uuid, json, logging, threading
from typing import List, Dict, Any, Optional, Callable

from skills.brain_db import get_db, BrainDB, PRUNE_SYNAPSE_WEIGHT, PRUNE_NEURON_ACTIVATION

logger = logging.getLogger(__name__)

# === Гиперпараметры ===
SPREAD_LEVELS = 2
SPREAD_DECAY = 0.65
MIN_SPREAD_POWER = 0.05

HEBBIAN_DELTA = 0.08
HEBBIAN_WINDOW = 5

DECAY_INTERVAL_SEC = 60
ACTIVATION_DECAY_RATE = 0.985
SYNAPSE_DECAY_RATE = 0.998

MAX_CONCEPTS_PER_TEXT = 8

# Стоп-слова для извлечения концептов
STOP_WORDS = {
    "и","в","во","не","что","он","на","я","с","со","как","а","то","все","она","так",
    "его","но","да","ты","к","у","же","вы","за","бы","по","только","ее","мне","было",
    "вот","от","меня","еще","нет","о","из","ему","теперь","когда","даже","ну","вдруг",
    "ли","если","уже","или","ни","быть","был","него","до","вас","нибудь","опять","уж",
    "вам","ведь","там","потом","себя","ничего","ей","может","они","тут","где","есть",
    "надо","ней","для","мы","тебя","их","чем","была","сам","чтоб","без","будто","чего",
    "раз","тоже","себе","под","будет","ж","тогда","кто","этот","того","потому","этого",
    "какой","совсем","ним","здесь","этом","один","почти","мой","тем","чтобы","нее",
    "сейчас","были","куда","зачем","всех","никогда","можно","при","наконец","два","об",
    "другой","хоть","после","над","больше","тот","через","эти","нас","про","всего",
    "них","какая","много","разве","три","эту","моя","впрочем","хорошо","свою","этой",
    "перед","иногда","лучше","чуть","том","нельзя","такой","им","более","всегда","конечно",
    "всю","между","this","that","with","from","have","will","your","about"
}


class NeuralEngine:
    def __init__(self, db: Optional[BrainDB] = None):
        self.db = db or get_db()
        self._lock = threading.RLock()
        self._stop_flag = threading.Event()
        self._bg_thread: Optional[threading.Thread] = None
        self._emit_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None
        logger.info("NeuralEngine инициализирован")

    def set_emit_callback(self, cb: Callable[[str, Dict[str, Any]], None]):
        """callback(event_name, payload) — для Socket.IO."""
        self._emit_callback = cb

    def _emit(self, event: str, payload: Dict[str, Any]):
        if self._emit_callback:
            try:
                self._emit_callback(event, payload)
            except Exception as e:
                logger.error(f"emit ошибка: {e}")

    # ==================== АКТИВАЦИЯ И РАСПРОСТРАНЕНИЕ ====================
    def activate_by_name(self, hemi: str, name: str, strength: float = 0.8,
                         create: bool = True, process_type: str = 'general',
                         spread: bool = True) -> Dict[str, Any]:
        """Активирует нейрон по имени, распространяет возбуждение."""
        n = self.db.find_neuron(hemi, name)
        if not n and create:
            nid = self.db.add_neuron(hemi, name, "Автосозданный из контекста",
                                      'concept', 'general', activation=0.3, base_activation=0.3)
            n = self.db.find_neuron(hemi, name) if nid > 0 else None
        if not n:
            return {"error": f"Нейрон '{name}' не найден и не создан"}
        return self.activate_by_id(hemi, n['id'], strength, process_type, spread)

    def activate_by_id(self, hemi: str, nid: int, strength: float = 0.8,
                       process_type: str = 'general', spread: bool = True) -> Dict[str, Any]:
        """Возбуждает нейрон, распространяет по синапсам вглубь на SPREAD_LEVELS."""
        activated: Dict[int, float] = {}
        with self._lock:
            self.db.bump_neuron(hemi, nid, delta_activation=strength)
            activated[nid] = strength

            if spread:
                queue = [(nid, strength, 0)]
                while queue:
                    cur_id, power, level = queue.pop(0)
                    if level >= SPREAD_LEVELS:
                        continue
                    for syn in self.db.get_outgoing(hemi, cur_id):
                        next_power = power * syn['weight'] * SPREAD_DECAY
                        if next_power < MIN_SPREAD_POWER:
                            continue
                        tgt = syn['target_id']
                        if next_power > activated.get(tgt, 0):
                            activated[tgt] = next_power
                            self.db.bump_neuron(hemi, tgt, delta_activation=next_power * 0.3)
                            queue.append((tgt, next_power, level + 1))

            # Логируем + эмитим для визуализации
            for a_nid, a_pow in activated.items():
                self.db.log_activation(hemi, a_nid, a_pow, process_type)

        if activated:
            self._emit("brain_activation", {
                "hemisphere": hemi,
                "activated": [{"id": k, "strength": v} for k, v in activated.items()],
                "process_type": process_type,
                "ts": time.time()
            })

        return {"activated": activated, "count": len(activated)}

    # ==================== ОБУЧЕНИЕ (Hebbian) ====================
    def reinforce(self, hemi: str, src_id: int, tgt_id: int, delta: float = HEBBIAN_DELTA):
        """Усиливает синапс. Если нет — создаёт."""
        if src_id == tgt_id or src_id <= 0 or tgt_id <= 0:
            return
        with self._lock:
            syn = None
            for s in self.db.get_outgoing(hemi, src_id):
                if s['target_id'] == tgt_id:
                    syn = s
                    break
            if syn:
                new_w = min(1.0, syn['weight'] + delta)
                with self.db._get_conn() as conn:
                    conn.execute(
                        "UPDATE synapses SET weight=?, use_count=use_count+1, "
                        "last_used=?, updated_at=? WHERE id=?",
                        (new_w, time.time(), time.time(), syn['id'])
                    )
                    conn.commit()
            else:
                self.db.add_synapse(hemi, src_id, tgt_id, weight=min(1.0, delta + 0.3))

    # ==================== ИЗВЛЕЧЕНИЕ КОНЦЕПТОВ ====================
    def extract_concepts(self, text: str, max_count: int = MAX_CONCEPTS_PER_TEXT) -> List[str]:
        """Простой NER: возвращает значимые слова (не стоп-слова, длиной ≥ 4)."""
        if not text:
            return []
        clean = re.sub(r'[^\w\s\-]', ' ', text.lower())
        words = clean.split()
        concepts, seen = [], set()
        for w in words:
            w = w.strip('-')
            if len(w) < 4 or w in STOP_WORDS or w.isdigit():
                continue
            if w in seen:
                continue
            seen.add(w)
            concepts.append(w)
            if len(concepts) >= max_count:
                break
        return concepts

    # ==================== РОСТ ИЗ ТЕКСТА ====================
    def grow_from_text(self, hemi: str, text: str,
                       process_type: str = 'general',
                       domain: str = 'general',
                       strength: float = 0.6) -> Dict[str, Any]:
        """
        Извлекает концепты, создаёт/активирует нейроны,
        усиливает Hebbian-связи в скользящем окне.
        """
        concepts = self.extract_concepts(text)
        if not concepts:
            return {"neurons_created": 0, "synapses_created": 0, "activated": 0}

        nids: List[int] = []
        created = 0
        with self._lock:
            for c in concepts:
                n = self.db.find_neuron(hemi, c)
                if not n:
                    nid = self.db.add_neuron(hemi, c, f"Концепт из {process_type}",
                                             'concept', domain, activation=0.4, base_activation=0.3)
                    if nid > 0:
                        nids.append(nid)
                        created += 1
                else:
                    nids.append(n['id'])
                # Активируем
                self.activate_by_id(hemi, nids[-1], strength=strength,
                                     process_type=process_type, spread=False)

            # Hebbian: усиливаем связи между концептами в окне
            reinforced = 0
            for i, n1 in enumerate(nids):
                for j in range(i + 1, min(i + HEBBIAN_WINDOW, len(nids))):
                    n2 = nids[j]
                    before = len(self.db.get_outgoing(hemi, n1))
                    self.reinforce(hemi, n1, n2, HEBBIAN_DELTA)
                    self.reinforce(hemi, n2, n1, HEBBIAN_DELTA)
                    reinforced += 2

        result = {
            "concepts": concepts,
            "neurons_created": created,
            "synapses_reinforced": reinforced,
            "activated": len(nids)
        }
        self._emit("brain_growth", {
            "hemisphere": hemi,
            "process_type": process_type,
            "created": created,
            "concepts": concepts,
            "ts": time.time()
        })
        return result

    # ==================== РАСПАД ====================
    def decay_all(self, hemi: Optional[str] = None):
        """Периодический распад: слабеют активации и веса."""
        hemispheres = [hemi] if hemi else ['left', 'right']
        for h in hemispheres:
            self.db.decay(h, activation_rate=ACTIVATION_DECAY_RATE,
                          weight_rate=SYNAPSE_DECAY_RATE)

    # ==================== ОЧИСТКА ====================
    def prune(self, hemi: Optional[str] = None) -> Dict[str, Any]:
        """Удаляет слабые синапсы и нейроны."""
        hemispheres = [hemi] if hemi else ['left', 'right']
        total_syn = 0
        total_neu = 0
        for h in hemispheres:
            weak_syn = self.db.get_weak_synapses(h)
            for s in weak_syn:
                self.db.delete_synapse(s['id'])
                total_syn += 1
            weak_neu = self.db.get_weak_neurons(h)
            for n in weak_neu:
                self.db.delete_neuron(h, n['id'])
                total_neu += 1
            # Чистим старые логи
            self.db.cleanup_old_logs(older_than_sec=3600)

        if total_syn or total_neu:
            self._emit("brain_prune", {
                "synapses_removed": total_syn,
                "neurons_removed": total_neu,
                "ts": time.time()
            })
        return {"synapses_removed": total_syn, "neurons_removed": total_neu}

    # ==================== ПРОЦЕССЫ ====================
    def track_process(self, process_type: str, context: Dict[str, Any],
                      hemisphere: str = 'left') -> str:
        """Регистрирует процесс (chat/cad/ros2/printer/...) и активирует релевантные нейроны."""
        pid = f"{process_type}_{uuid.uuid4().hex[:8]}"
        self.db.start_process(pid, process_type, context)

        # Активируем корневой нейрон процесса
        domain_neurons = {
            "chat":     ["диалог", "общение", "контекст"],
            "cad":      ["модель", "деталь", "форма"],
            "ros2":     ["робот", "движение", "команда"],
            "printer":  ["принтер", "слой", "экструзия"],
            "slicer":   ["слайсинг", "траектория", "инфилл"],
            "vision":   ["изображение", "распознавание", "объект"],
            "physics":  ["физика", "симуляция", "столкновение"],
        }.get(process_type, [])

        for name in domain_neurons:
            self.activate_by_name(hemisphere, name, strength=0.7,
                                   create=True, process_type=process_type, spread=True)

        # Плюс концепты из текста контекста
        text = " ".join(str(v) for v in context.values() if isinstance(v, (str, int, float)))
        if text:
            self.grow_from_text(hemisphere, text, process_type=process_type)

        self._emit("brain_process_start", {
            "process_id": pid, "process_type": process_type, "hemisphere": hemisphere
        })
        return pid

    def end_process(self, pid: str):
        self.db.end_process(pid)
        self._emit("brain_process_end", {"process_id": pid})

    # ==================== ФОНОВЫЙ ЦИКЛ ====================
    def start_background(self):
        if self._bg_thread and self._bg_thread.is_alive():
            return
        self._stop_flag.clear()
        self._bg_thread = threading.Thread(target=self._bg_loop, daemon=True)
        self._bg_thread.start()
        logger.info("NeuralEngine: фоновый цикл запущен (распад+очистка каждые %ds)" % DECAY_INTERVAL_SEC)

    def _bg_loop(self):
        last_merge = time.time()
        while not self._stop_flag.is_set():
            try:
                time.sleep(DECAY_INTERVAL_SEC)
                self.decay_all()
                self.prune()

                # Backfill эмбеддингов — каждый цикл по 30 нейронов на полушарие
                for hemi in ("left", "right"):
                    try:
                        from skills.semantic_merger import backfill_embeddings
                        backfill_embeddings(self.db, hemi, limit=30)
                    except Exception as e:
                        logger.debug(f"backfill {hemi}: {e}")

                # Merge дубликатов — раз в час
                if time.time() - last_merge > 3600:
                    self._merge_all_hemispheres()
                    last_merge = time.time()
            except Exception as e:
                logger.error(f"NeuralEngine bg ошибка: {e}")

    def _merge_all_hemispheres(self):
        """Периодическая чистка дубликатов."""
        from skills.semantic_merger import merge_similar_neurons
        for hemi in ("left", "right"):
            try:
                result = merge_similar_neurons(
                    self.db, hemi,
                    percentile=99.0,
                    abs_min=0.93,
                    max_merges=50,
                )
                if result["merged"] > 0:
                    logger.info(
                        f"[neural] merge {hemi}: "
                        f"удалено {result['merged']} дубликатов "
                        f"(просмотрено {result['scanned']})"
                    )
                    self._emit("brain_prune", {
                        "hemisphere": hemi,
                        "neurons_removed": result["merged"],
                        "synapses_removed": 0,
                        "type": "merge",
                    })
            except Exception as e:
                logger.error(f"merge {hemi}: {e}")

    def stop_background(self):
        self._stop_flag.set()


# === Синглтон ===
_engine: Optional[NeuralEngine] = None

def get_engine() -> NeuralEngine:
    global _engine
    if _engine is None:
        _engine = NeuralEngine()
    return _engine