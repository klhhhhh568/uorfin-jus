# skills/semantic_merger.py
# -*- coding: utf-8 -*-
"""
Семантическая близость нейронов через эмбеддинги.
- Считает вектора через Ollama (bge-m3)
- Находит дубликаты по косинусному расстоянию
- Сливает близкие нейроны (переносит синапсы, суммирует веса)
- Seed-нейроны (bootstrap) защищены от автослияния
"""
import array
import logging
import math
import requests
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)

OLLAMA_EMBED_URL = "http://localhost:11434/api/embeddings"
EMBED_MODEL = "bge-m3"
DEFAULT_THRESHOLD = 0.15  # 1 - similarity; similarity > 0.85 = дубликаты
VECTOR_DIM = 1024


# ============================================================
# ЭМБЕДДИНГИ
# ============================================================
def get_embedding(text: str) -> Optional[List[float]]:
    """Считает эмбеддинг для строки через Ollama."""
    if not text or len(text.strip()) < 2:
        return None
    try:
        r = requests.post(
            OLLAMA_EMBED_URL,
            json={"model": EMBED_MODEL, "prompt": text[:512]},
            timeout=30,
        )
        r.raise_for_status()
        vec = r.json().get("embedding", [])
        return vec if vec else None
    except requests.exceptions.ConnectionError:
        logger.debug("[semantic] Ollama недоступна")
        return None
    except Exception as e:
        logger.warning(f"[semantic] embedding error: {e}")
        return None


# ============================================================
# МАТЕМАТИКА
# ============================================================
def cosine_similarity(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na < 1e-9 or nb < 1e-9:
        return 0.0
    return dot / (na * nb)


def find_best_match(
    vector: List[float],
    candidates: Dict[int, List[float]],
) -> tuple:
    """
    Возвращает (neuron_id, similarity) для самого близкого кандидата.
    """
    if not candidates:
        return None, 0.0
    best_id = None
    best_sim = 0.0
    for nid, vec in candidates.items():
        sim = cosine_similarity(vector, vec)
        if sim > best_sim:
            best_sim = sim
            best_id = nid
    return best_id, best_sim


# ============================================================
# ХРАНЕНИЕ ВЕКТОРОВ
# ============================================================
def vec_to_blob(vec: List[float]) -> bytes:
    return array.array("f", vec).tobytes()


def blob_to_vec(blob: bytes) -> List[float]:
    arr = array.array("f")
    arr.frombytes(blob)
    return list(arr)


# ============================================================
# ПЕРИОДИЧЕСКАЯ ЧИСТКА ДУБЛИКАТОВ
# ============================================================
def merge_similar_neurons(
    db,
    hemisphere: str,
    percentile: float = 99.0,
    abs_min: float = 0.93,
    max_merges: int = 50,
) -> Dict[str, int]:
    """
    Консервативное слияние дубликатов — только MUTUAL top-1.

    Условие слияния (A→B):
    1. sim(A, B) >= threshold
    2. B — top-1 сосед для A
    3. A — top-1 сосед для B  (mutual!)

    Seed-защита: нейроны с is_seed=1 (из bootstrap) не участвуют
    в слиянии — ни как источник, ни как цель. Это сохраняет
    исходный «скелет» семантической сети.

    Защищает от ошибок типа 'математика → геометрия'.
    """
    all_neuros = db.get_all_embeddings(hemisphere)
    if len(all_neuros) < 3:
        return {"merged": 0, "scanned": len(all_neuros), "threshold": 0.0}

    items = list(all_neuros.items())

    # === Этап 1: top-1 для каждого ===
    top1: Dict[int, tuple] = {}
    for src_id, vec in items:
        candidates = {k: v for k, v in items if k != src_id}
        dst_id, sim = find_best_match(vec, candidates)
        if dst_id is not None:
            top1[src_id] = (dst_id, sim)

    if not top1:
        return {"merged": 0, "scanned": len(all_neuros), "threshold": 0.0}

    # === Этап 2: распределение ===
    sims = sorted([t[1] for t in top1.values()])
    idx = int(len(sims) * percentile / 100)
    idx = min(idx, len(sims) - 1)
    threshold = max(sims[idx], abs_min)

    logger.info(
        f"[semantic] {hemisphere}: {len(all_neuros)} нейронов, "
        f"top-1 sim mean={sum(sims)/len(sims):.3f}, "
        f"p{percentile}={threshold:.3f}"
    )

    # === Этап 3: MUTUAL top-1 ===
    mutual_pairs: List[tuple] = []
    for a_id, (b_id, sim) in top1.items():
        if b_id in top1 and top1[b_id][0] == a_id:
            pair = (min(a_id, b_id), max(a_id, b_id), sim)
            if pair not in mutual_pairs:
                mutual_pairs.append(pair)

    logger.info(f"[semantic] {hemisphere}: mutual-пар найдено {len(mutual_pairs)}")

    mutual_pairs.sort(key=lambda t: -t[2])

    # Индекс нейронов
    neurons_list = db.get_neurons(hemisphere, limit=1000)
    map_n = {n["id"]: n for n in neurons_list}

    merged = 0
    skipped_seed = 0
    processed: set = set()

    for a_id, b_id, sim in mutual_pairs:
        if sim < threshold:
            break
        if a_id in processed or b_id in processed:
            continue
        if a_id not in map_n or b_id not in map_n:
            continue

        n_a = map_n[a_id]
        n_b = map_n[b_id]

        # === SEED-ЗАЩИТА ===
        # bootstrap-нейроны (is_seed=1) нельзя сливать:
        # ни как источник, ни как цель. Иначе «скелет» сети мутирует
        # (был баг: тема → ответ, математика → геометрия).
        if n_a.get("is_seed") or n_b.get("is_seed"):
            processed.add(a_id)
            processed.add(b_id)
            skipped_seed += 1
            logger.debug(
                f"[semantic] skip seed-pair: "
                f"{n_a['name']} <-> {n_b['name']} (sim={sim:.3f})"
            )
            continue

        # Оставляем более «важный»
        if n_a["use_count"] >= n_b["use_count"]:
            keep_id, drop_id = a_id, b_id
        else:
            keep_id, drop_id = b_id, a_id

        try:
            db.merge_neurons(hemisphere, src_id=drop_id, dst_id=keep_id)
            processed.add(drop_id)
            merged += 1
            logger.info(
                f"[semantic] merge #{merged}: "
                f"{map_n[drop_id]['name']} → {map_n[keep_id]['name']} "
                f"(sim={sim:.3f})"
            )
            if merged >= max_merges:
                break
        except Exception as e:
            logger.warning(f"[semantic] merge {drop_id}→{keep_id}: {e}")

    return {
        "merged": merged,
        "scanned": len(all_neuros),
        "threshold": round(threshold, 3),
        "mutual_pairs": len(mutual_pairs),
        "skipped_seed": skipped_seed,
    }


# ============================================================
# BACKFILL (дозаполнение векторов)
# ============================================================
def backfill_embeddings(db, hemisphere: str, limit: int = 50) -> int:
    """
    Считает эмбеддинги для нейронов, у которых их ещё нет.
    Возвращает число добавленных.
    """
    neurons = db.get_neurons(hemisphere, limit=500)
    added = 0
    for n in neurons:
        if db.get_embedding(n["id"]):
            continue
        text = n["name"]
        if n.get("description"):
            text = f"{text}: {n['description']}"
        vec = get_embedding(text)
        if vec:
            db.set_embedding(n["id"], vec)
            added += 1
            if added >= limit:
                break
    if added > 0:
        logger.info(f"[semantic] backfill {hemisphere}: +{added} embeddings")
    return added