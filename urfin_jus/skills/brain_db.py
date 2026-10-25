# skills/brain_db.py
# -*- coding: utf-8 -*-
"""
База данных живой нейронной сети.
Схема: neurons + synapses + activation_log + process_context + cad_cache.
"""
import sqlite3, os, sys, time, logging, hashlib, re
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

def _find_db_path() -> str:
    """
    Ищет постоянное место для brain.db, независимо от режима (dev / PyInstaller).
    Приоритет:
    1. env URFIN_DATA_DIR
    2. <project>/data/ (dev-режим, для совместимости)
    3. ~/.urfin_jus/ (постоянное место для PyInstaller)
    """
    # 1. env
    env_dir = os.environ.get("URFIN_DATA_DIR")
    if env_dir:
        os.makedirs(env_dir, exist_ok=True)
        return os.path.join(env_dir, "brain.db")

    # 2. dev-режим — используем проект (совместимость с текущими базами)
    if not getattr(sys, 'frozen', False):
        project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        project_data = os.path.join(project_dir, "data")
        if os.path.exists(os.path.join(project_data, "brain.db")):
            return os.path.join(project_data, "brain.db")

    # 3. PyInstaller — постоянная домашняя папка
    home_dir = os.path.expanduser("~/.urfin_jus")
    os.makedirs(home_dir, exist_ok=True)
    return os.path.join(home_dir, "brain.db")


DB_PATH = _find_db_path()
logger.info(f"BrainDB путь: {DB_PATH}")

# Пороги распада / очистки
PRUNE_SYNAPSE_WEIGHT = 0.05
PRUNE_SYNAPSE_MIN_USES = 2
PRUNE_NEURON_ACTIVATION = 0.02
PRUNE_NEURON_MIN_USES = 2

# Стоп-слова для нормализации промпта при кэшировании
STOP_WORDS = {
    'и','в','на','с','по','для','от','до','из','к','о','у','это','как','что',
    'быть','был','была','было','были','или','но','а','же','бы','ли','не','ни',
    'нет','да','то','этот','эта','эти','тот','та','те','свой','своя','своё',
    'свои','весь','вся','всё','все','один','одна','одно','одни','при','под',
    'над','за','перед','через','без','между','около','вокруг',
    'the','a','an','of','to','for','with','on','in','at','by',
    'is','are','was','were','be','and','or','not',
}


class BrainDB:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_schema()
        logger.info(f"BrainDB инициализирована: {self.db_path}")

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def _init_schema(self):
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS neurons (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    hemisphere TEXT NOT NULL CHECK (hemisphere IN ('left','right')),
                    name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    neuron_type TEXT DEFAULT 'concept',
                    domain TEXT DEFAULT 'general',
                    activation REAL DEFAULT 0.0,
                    base_activation REAL DEFAULT 0.0,
                    use_count INTEGER DEFAULT 0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    last_used REAL DEFAULT 0,
                    is_seed INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(hemisphere, name)
                );

                CREATE TABLE IF NOT EXISTS synapses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    hemisphere TEXT NOT NULL,
                    source_id INTEGER NOT NULL,
                    target_id INTEGER NOT NULL,
                    weight REAL DEFAULT 1.0,
                    use_count INTEGER DEFAULT 0,
                    synapse_type TEXT DEFAULT 'excitatory',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    last_used REAL DEFAULT 0,
                    FOREIGN KEY (source_id) REFERENCES neurons(id) ON DELETE CASCADE,
                    FOREIGN KEY (target_id) REFERENCES neurons(id) ON DELETE CASCADE,
                    UNIQUE(source_id, target_id)
                );

                CREATE TABLE IF NOT EXISTS activation_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    hemisphere TEXT NOT NULL,
                    neuron_id INTEGER NOT NULL,
                    strength REAL DEFAULT 0,
                    process_type TEXT DEFAULT 'general',
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS process_context (
                    id TEXT PRIMARY KEY,
                    process_type TEXT NOT NULL,
                    context_json TEXT DEFAULT '{}',
                    started_at REAL NOT NULL,
                    ended_at REAL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS cad_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    prompt_hash TEXT UNIQUE,
                    prompt TEXT,
                    code TEXT,
                    stl_base64 TEXT,
                    created_at REAL,
                    hit_count INTEGER DEFAULT 0
                );

                CREATE INDEX IF NOT EXISTS idx_neurons_hemi ON neurons(hemisphere);
                CREATE INDEX IF NOT EXISTS idx_syn_src ON synapses(source_id);
                CREATE INDEX IF NOT EXISTS idx_syn_tgt ON synapses(target_id);
                CREATE INDEX IF NOT EXISTS idx_syn_hemi ON synapses(hemisphere);
                CREATE INDEX IF NOT EXISTS idx_act_log ON activation_log(hemisphere, created_at);
                CREATE INDEX IF NOT EXISTS idx_cad_prompt ON cad_cache(prompt_hash);

                CREATE TABLE IF NOT EXISTS embeddings (
                    neuron_id INTEGER PRIMARY KEY,
                    vector BLOB NOT NULL,
                    updated_at REAL NOT NULL,
                    FOREIGN KEY (neuron_id) REFERENCES neurons(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_embeddings_neuron ON embeddings(neuron_id);
            """)
            conn.commit()

    # ==================== NEURONS ====================
    def add_neuron(self, hemi: str, name: str, description: str = "",
                   neuron_type: str = 'concept', domain: str = 'general',
                   activation: float = 0.5, base_activation: float = 0.5,
                   is_seed: bool = False) -> int:
        name = name.strip()[:80]
        if not name:
            return -1
        now = time.time()
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT id FROM neurons WHERE hemisphere = ? AND name = ?",
                (hemi, name)
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE neurons SET description = COALESCE(NULLIF(?,''), description), "
                    "updated_at = ?, activation = MIN(1.0, activation + 0.03) WHERE id = ?",
                    (description, now, row['id'])
                )
                conn.commit()
                return row['id']
            cur = conn.execute(
                "INSERT INTO neurons (hemisphere, name, description, neuron_type, domain,"
                " activation, base_activation, use_count, created_at, updated_at, last_used, is_seed)"
                " VALUES (?,?,?,?,?,?,?,0,?,?,?,?)",
                (hemi, name, description, neuron_type, domain,
                 activation, base_activation, now, now, now,
                 1 if is_seed else 0)
            )
            conn.commit()
            return cur.lastrowid

    def find_neuron(self, hemi: str, name: str) -> Optional[Dict[str, Any]]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM neurons WHERE hemisphere = ? AND name = ?",
                (hemi, name)
            ).fetchone()
            return dict(row) if row else None

    def get_neurons(self, hemi: str, limit: int = 1000,
                    domain: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            if domain:
                rows = conn.execute(
                    "SELECT * FROM neurons WHERE hemisphere = ? AND domain = ? "
                    "ORDER BY activation DESC, use_count DESC LIMIT ?",
                    (hemi, domain, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM neurons WHERE hemisphere = ? "
                    "ORDER BY activation DESC, use_count DESC LIMIT ?",
                    (hemi, limit)
                ).fetchall()
            return [dict(r) for r in rows]

    def bump_neuron(self, hemi: str, nid: int, delta_activation: float = 0.1):
        now = time.time()
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE neurons SET activation = MIN(1.0, activation + ?), "
                "base_activation = MIN(1.0, base_activation + ?), "
                "use_count = use_count + 1, last_used = ?, updated_at = ? WHERE id = ?",
                (delta_activation, delta_activation * 0.3, now, now, nid)
            )
            conn.commit()

    def set_activation(self, hemi: str, nid: int, value: float):
        value = max(0.0, min(1.0, value))
        with self._get_conn() as conn:
            conn.execute("UPDATE neurons SET activation = ?, updated_at = ? WHERE id = ?",
                         (value, time.time(), nid))
            conn.commit()

    def delete_neuron(self, hemi: str, nid: int):
        with self._get_conn() as conn:
            conn.execute("DELETE FROM neurons WHERE id = ? AND hemisphere = ?", (nid, hemi))
            conn.commit()

    # ==================== SYNAPSES ====================
    def add_synapse(self, hemi: str, src: int, tgt: int, weight: float = 1.0,
                    synapse_type: str = 'excitatory') -> int:
        if src <= 0 or tgt <= 0 or src == tgt:
            return -1
        weight = max(0.0, min(1.0, float(weight)))
        now = time.time()
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT id FROM synapses WHERE source_id = ? AND target_id = ?",
                (src, tgt)
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE synapses SET weight = MIN(1.0, weight + 0.05), "
                    "use_count = use_count + 1, last_used = ?, updated_at = ? WHERE id = ?",
                    (now, now, row['id'])
                )
                conn.commit()
                return row['id']
            cur = conn.execute(
                "INSERT INTO synapses (hemisphere, source_id, target_id, weight,"
                " use_count, synapse_type, created_at, updated_at, last_used)"
                " VALUES (?,?,?,?,1,?,?,?,?)",
                (hemi, src, tgt, weight, synapse_type, now, now, now)
            )
            conn.commit()
            return cur.lastrowid

    def get_synapses(self, hemi: str, limit: int = 2000) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT s.*, n1.name as source_name, n2.name as target_name
                   FROM synapses s
                   JOIN neurons n1 ON s.source_id = n1.id
                   JOIN neurons n2 ON s.target_id = n2.id
                   WHERE s.hemisphere = ?
                   ORDER BY s.weight DESC LIMIT ?""",
                (hemi, limit)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_outgoing(self, hemi: str, nid: int) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM synapses WHERE hemisphere = ? AND source_id = ?",
                (hemi, nid)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_weak_synapses(self, hemi: str, threshold: float = PRUNE_SYNAPSE_WEIGHT,
                          min_uses: int = PRUNE_SYNAPSE_MIN_USES) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT id FROM synapses WHERE hemisphere = ? AND weight < ? AND use_count < ?",
                (hemi, threshold, min_uses)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_weak_neurons(self, hemi: str, threshold: float = PRUNE_NEURON_ACTIVATION,
                         min_uses: int = PRUNE_NEURON_MIN_USES) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT n.id FROM neurons n
                   WHERE n.hemisphere = ?
                     AND n.activation < ?
                     AND n.use_count < ?
                     AND NOT EXISTS (
                         SELECT 1 FROM synapses s
                         WHERE (s.source_id = n.id OR s.target_id = n.id) AND s.weight > 0.3
                     )""",
                (hemi, threshold, min_uses)
            ).fetchall()
            return [dict(r) for r in rows]

    def delete_synapse(self, sid: int):
        with self._get_conn() as conn:
            conn.execute("DELETE FROM synapses WHERE id = ?", (sid,))
            conn.commit()

    def decay(self, hemi: str, activation_rate: float = 0.995, weight_rate: float = 0.999):
        with self._get_conn() as conn:
            conn.execute("UPDATE neurons SET activation = activation * ? WHERE hemisphere = ?",
                         (activation_rate, hemi))
            conn.execute("UPDATE synapses SET weight = weight * ? WHERE hemisphere = ?",
                         (weight_rate, hemi))
            conn.commit()

    # ==================== ACTIVATION LOG ====================
    def log_activation(self, hemi: str, nid: int, strength: float, process_type: str = 'general'):
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO activation_log (hemisphere, neuron_id, strength, process_type, created_at)"
                " VALUES (?,?,?,?,?)",
                (hemi, nid, strength, process_type, time.time())
            )
            conn.commit()

    def cleanup_old_logs(self, older_than_sec: int = 3600):
        with self._get_conn() as conn:
            conn.execute("DELETE FROM activation_log WHERE created_at < ?",
                         (time.time() - older_than_sec,))
            conn.commit()

    # ==================== PROCESS ====================
    def start_process(self, process_id: str, process_type: str, context: Dict[str, Any]):
        import json as _json
        with self._get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO process_context "
                "(id, process_type, context_json, started_at) VALUES (?,?,?,?)",
                (process_id, process_type, _json.dumps(context, ensure_ascii=False)[:3000], time.time())
            )
            conn.commit()

    def end_process(self, process_id: str):
        with self._get_conn() as conn:
            conn.execute("UPDATE process_context SET ended_at = ? WHERE id = ?",
                         (time.time(), process_id))
            conn.commit()

    # ==================== STATS ====================
    def get_stats(self, hemi: str) -> Dict[str, Any]:
        with self._get_conn() as conn:
            n = conn.execute("SELECT COUNT(*) c FROM neurons WHERE hemisphere = ?", (hemi,)).fetchone()['c']
            s = conn.execute("SELECT COUNT(*) c FROM synapses WHERE hemisphere = ?", (hemi,)).fetchone()['c']
            a = conn.execute("SELECT AVG(activation) a FROM neurons WHERE hemisphere = ?",
                             (hemi,)).fetchone()['a'] or 0.0
            w = conn.execute("SELECT AVG(weight) w FROM synapses WHERE hemisphere = ?",
                             (hemi,)).fetchone()['w'] or 0.0
            active = conn.execute(
                "SELECT COUNT(*) c FROM neurons WHERE hemisphere = ? AND activation > 0.3",
                (hemi,)).fetchone()['c']
            return {
                "neurons": n, "synapses": s,
                "avg_activation": round(float(a), 3),
                "avg_weight": round(float(w), 3),
                "active_neurons": active,
            }

    # ==================== CAD CACHE ====================
    @staticmethod
    def _normalize_prompt(prompt: str) -> str:
        """Нормализует промпт для кэширования: lowercase, без стоп-слов, без пунктуации."""
        if not prompt:
            return ""
        s = prompt.lower()
        # Заменяем пунктуацию на пробелы (сохраняем буквы/цифры)
        s = re.sub(r'[^\w\s]+', ' ', s, flags=re.UNICODE)
        # Убираем стоп-слова
        words = [w for w in s.split() if w and w not in STOP_WORDS]
        return ' '.join(words)

    @staticmethod
    def _hash_prompt(prompt: str) -> str:
        normalized = BrainDB._normalize_prompt(prompt)
        return hashlib.md5(normalized.encode('utf-8')).hexdigest()

    def cache_get(self, prompt: str) -> Optional[Dict[str, Any]]:
        """
        Возвращает закэшированный результат для промпта.
        Инкрементирует hit_count при попадании.
        """
        h = self._hash_prompt(prompt)
        if not h:
            return None
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM cad_cache WHERE prompt_hash = ?", (h,)
            ).fetchone()
            if not row:
                return None
            conn.execute(
                "UPDATE cad_cache SET hit_count = hit_count + 1 WHERE id = ?",
                (row['id'],)
            )
            conn.commit()
            return dict(row)

    def cache_set(self, prompt: str, code: str, stl_base64: str) -> int:
        """
        Сохраняет результат в кэш. Если запись для промпта существует — обновляет.
        Возвращает id записи или -1 при ошибке.
        """
        h = self._hash_prompt(prompt)
        if not h:
            return -1
        now = time.time()
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT id FROM cad_cache WHERE prompt_hash = ?", (h,)
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE cad_cache SET prompt = ?, code = ?, stl_base64 = ?, created_at = ? "
                    "WHERE id = ?",
                    (prompt, code, stl_base64, now, row['id'])
                )
                conn.commit()
                return row['id']
            cur = conn.execute(
                "INSERT INTO cad_cache (prompt_hash, prompt, code, stl_base64, created_at, hit_count)"
                " VALUES (?,?,?,?,?,0)",
                (h, prompt, code, stl_base64, now)
            )
            conn.commit()
            return cur.lastrowid

    def cache_clear(self):
        """Полная очистка CAD-кэша."""
        with self._get_conn() as conn:
            conn.execute("DELETE FROM cad_cache")
            conn.commit()

    def cache_stats(self) -> Dict[str, Any]:
        """Статистика CAD-кэша."""
        with self._get_conn() as conn:
            total = conn.execute("SELECT COUNT(*) c FROM cad_cache").fetchone()['c']
            hits = conn.execute(
                "SELECT COALESCE(SUM(hit_count), 0) s FROM cad_cache"
            ).fetchone()['s']
            return {"entries": int(total), "total_hits": int(hits)}

    # ==================== PYTHON CODE EXPORT / IMPORT ====================
    def export_python_code(self, hemi: str, model_name: str = "deepseek-r1:1.5b") -> str:
        neurons = self.get_neurons(hemi, limit=5000)
        synapses = self.get_synapses(hemi, limit=10000)
        st = self.get_stats(hemi)

        lines = [
            f"# Полушарие: {hemi.upper()}",
            f"# Модель: {model_name}",
            f"# Сгенерировано из живой БД: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"# Нейронов: {st['neurons']}  |  Синапсов: {st['synapses']}  |  Ср. активация: {st['avg_activation']}",
            "",
            "# Каждый нейрон — живой. Поля:",
            "#   name, description, neuron_type, domain,",
            "#   activation (текущее возбуждение 0..1), base_activation (долговременная память)",
            "#   use_count (сколько раз использовался)",
            "neurons = [",
        ]
        for n in neurons:
            name = n['name'].replace('"', '\\"')
            desc = (n['description'] or '').replace('"', '\\"').replace("\n", " ")[:200]
            lines.append(
                f'    {{"name": "{name}", "description": "{desc}", '
                f'"neuron_type": "{n["neuron_type"]}", "domain": "{n["domain"]}", '
                f'"activation": {float(n["activation"]):.3f}, '
                f'"base_activation": {float(n["base_activation"]):.3f}, '
                f'"use_count": {int(n["use_count"])}}},'
            )
        lines.append("]")
        lines.append("")
        lines.append("# Синапсы: source → target, weight 0..1, use_count (число подкреплений)")
        lines.append("synapses = [")
        for s in synapses:
            src = s['source_name'].replace('"', '\\"')
            tgt = s['target_name'].replace('"', '\\"')
            lines.append(
                f'    {{"source": "{src}", "target": "{tgt}", '
                f'"weight": {float(s["weight"]):.3f}, '
                f'"use_count": {int(s["use_count"])}, '
                f'"synapse_type": "{s["synapse_type"]}"}},'
            )
        lines.append("]")
        return "\n".join(lines)

    def import_python_code(self, hemi: str, code: str) -> Dict[str, Any]:
        """Полная замена нейронной карты полушария из Python-кода."""
        safe_builtins = {
            "True": True, "False": False, "None": None,
            "len": len, "str": str, "int": int, "float": float,
            "list": list, "dict": dict, "tuple": tuple, "set": set,
            "range": range, "enumerate": enumerate, "zip": zip,
            "min": min, "max": max, "abs": abs, "round": round,
        }
        ns: Dict[str, Any] = {}
        try:
            exec(code, {"__builtins__": safe_builtins}, ns)
        except SyntaxError as e:
            return {"error": f"Синтаксис: строка {e.lineno}: {e.msg}"}
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"}

        neurons_data = ns.get("neurons", [])
        synapses_data = ns.get("synapses", [])
        if not isinstance(neurons_data, list):
            return {"error": "'neurons' должен быть списком"}
        if not isinstance(synapses_data, list):
            return {"error": "'synapses' должен быть списком"}

        with self._get_conn() as conn:
            conn.execute("DELETE FROM synapses WHERE hemisphere = ?", (hemi,))
            conn.execute("DELETE FROM neurons WHERE hemisphere = ?", (hemi,))
            conn.commit()

        added_n = 0
        name_to_id: Dict[str, int] = {}
        for n in neurons_data:
            if not isinstance(n, dict) or "name" not in n:
                continue
            name = str(n["name"]).strip()
            if not name:
                continue
            desc = str(n.get("description", ""))[:400]
            ntype = str(n.get("neuron_type", "concept"))
            domain = str(n.get("domain", "general"))
            act = max(0.0, min(1.0, float(n.get("activation", 0.5))))
            base = max(0.0, min(1.0, float(n.get("base_activation", act))))
            uses = max(0, int(n.get("use_count", 0)))
            nid = self.add_neuron(hemi, name, desc, ntype, domain, act, base)
            if nid > 0:
                with self._get_conn() as conn:
                    conn.execute("UPDATE neurons SET use_count = ? WHERE id = ?", (uses, nid))
                    conn.commit()
                name_to_id[name] = nid
                added_n += 1

        added_s = 0
        for s in synapses_data:
            if not isinstance(s, dict):
                continue
            src = str(s.get("source", "")).strip()
            tgt = str(s.get("target", "")).strip()
            if not src or not tgt:
                continue
            if src not in name_to_id:
                nid = self.add_neuron(hemi, src, "Автосозданный", "concept", "general", 0.4, 0.4)
                if nid > 0: name_to_id[src] = nid; added_n += 1
            if tgt not in name_to_id:
                nid = self.add_neuron(hemi, tgt, "Автосозданный", "concept", "general", 0.4, 0.4)
                if nid > 0: name_to_id[tgt] = nid; added_n += 1
            w = max(0.0, min(1.0, float(s.get("weight", 1.0))))
            uses = max(0, int(s.get("use_count", 0)))
            stype = str(s.get("synapse_type", "excitatory"))
            sid = self.add_synapse(hemi, name_to_id[src], name_to_id[tgt], w, stype)
            if sid > 0:
                with self._get_conn() as conn:
                    conn.execute("UPDATE synapses SET use_count = ? WHERE id = ?", (uses, sid))
                    conn.commit()
                added_s += 1

        return {"neurons_added": added_n, "synapses_added": added_s}

    # ==================== ЭМБЕДДИНГИ ====================
    def set_embedding(self, neuron_id: int, vector: List[float]):
        from skills.semantic_merger import vec_to_blob
        blob = vec_to_blob(vector)
        with self._get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO embeddings (neuron_id, vector, updated_at) "
                "VALUES (?, ?, ?)",
                (neuron_id, blob, time.time()),
            )
            conn.commit()

    def get_embedding(self, neuron_id: int) -> Optional[List[float]]:
        from skills.semantic_merger import blob_to_vec
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT vector FROM embeddings WHERE neuron_id = ?",
                (neuron_id,),
            ).fetchone()
            if not row:
                return None
            return blob_to_vec(row["vector"])

    def get_all_embeddings(self, hemisphere: str) -> Dict[int, List[float]]:
        from skills.semantic_merger import blob_to_vec
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT e.neuron_id, e.vector
                   FROM embeddings e
                   JOIN neurons n ON n.id = e.neuron_id
                   WHERE n.hemisphere = ?""",
                (hemisphere,),
            ).fetchall()
            return {r["neuron_id"]: blob_to_vec(r["vector"]) for r in rows}

    def merge_neurons(self, hemisphere: str, src_id: int, dst_id: int):
        """
        Объединяет нейрон src в dst:
        - суммирует use_count, activation
        - переносит синапсы
        - удаляет src
        """
        if src_id == dst_id:
            return
        now = time.time()
        with self._get_conn() as conn:
            src = conn.execute(
                "SELECT * FROM neurons WHERE id = ? AND hemisphere = ?",
                (src_id, hemisphere),
            ).fetchone()
            dst = conn.execute(
                "SELECT * FROM neurons WHERE id = ? AND hemisphere = ?",
                (dst_id, hemisphere),
            ).fetchone()
            if not src or not dst:
                return

            new_use = dst["use_count"] + src["use_count"]
            new_act = min(1.0, dst["activation"] + src["activation"] * 0.5)
            new_base = min(1.0, dst["base_activation"] + src["base_activation"] * 0.3)
            conn.execute(
                "UPDATE neurons SET use_count = ?, activation = ?, "
                "base_activation = ?, updated_at = ? WHERE id = ?",
                (new_use, new_act, new_base, now, dst_id),
            )

            # Исходящие синапсы
            out_syns = conn.execute(
                "SELECT target_id, weight, use_count, synapse_type "
                "FROM synapses WHERE source_id = ?",
                (src_id,),
            ).fetchall()
            for syn in out_syns:
                if syn["target_id"] == dst_id:
                    continue
                existing = conn.execute(
                    "SELECT id FROM synapses WHERE source_id = ? AND target_id = ?",
                    (dst_id, syn["target_id"]),
                ).fetchone()
                if existing:
                    conn.execute(
                        "UPDATE synapses SET weight = MIN(1.0, weight + ?), "
                        "use_count = use_count + ?, updated_at = ? WHERE id = ?",
                        (syn["weight"] * 0.5, syn["use_count"], now, existing["id"]),
                    )
                else:
                    conn.execute(
                        "INSERT INTO synapses (hemisphere, source_id, target_id, "
                        "weight, use_count, synapse_type, created_at, updated_at, last_used) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (hemisphere, dst_id, syn["target_id"], syn["weight"],
                         syn["use_count"], syn["synapse_type"], now, now, now),
                    )

            # Входящие синапсы
            in_syns = conn.execute(
                "SELECT source_id, weight, use_count, synapse_type "
                "FROM synapses WHERE target_id = ?",
                (src_id,),
            ).fetchall()
            for syn in in_syns:
                if syn["source_id"] == dst_id:
                    continue
                existing = conn.execute(
                    "SELECT id FROM synapses WHERE source_id = ? AND target_id = ?",
                    (syn["source_id"], dst_id),
                ).fetchone()
                if existing:
                    conn.execute(
                        "UPDATE synapses SET weight = MIN(1.0, weight + ?), "
                        "use_count = use_count + ?, updated_at = ? WHERE id = ?",
                        (syn["weight"] * 0.5, syn["use_count"], now, existing["id"]),
                    )
                else:
                    conn.execute(
                        "INSERT INTO synapses (hemisphere, source_id, target_id, "
                        "weight, use_count, synapse_type, created_at, updated_at, last_used) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (hemisphere, syn["source_id"], dst_id, syn["weight"],
                         syn["use_count"], syn["synapse_type"], now, now, now),
                    )

            # Удаляем src (CASCADE снесёт embeddings)
            conn.execute("DELETE FROM synapses WHERE source_id = ? OR target_id = ?",
                         (src_id, src_id))
            conn.execute("DELETE FROM neurons WHERE id = ?", (src_id,))
            conn.commit()

        logger.info(f"[brain] merge: {src['name']} → {dst['name']}")

    # ==================== АЛИАСЫ ДЛЯ СОВМЕСТИМОСТИ ====================
    def generate_python_code(self, hemisphere: str) -> str:
        """
        Алиас для export_python_code.
        Оставлен для совместимости со старыми вызовами (web_server / dual_hemisphere_cloud).
        """
        return self.export_python_code(hemisphere, "deepseek-r1:7b")

    def update_from_python_code(self, hemisphere: str, code: str) -> Dict[str, Any]:
        """
        Алиас для import_python_code.
        Оставлен для совместимости со старыми вызовами.
        """
        return self.import_python_code(hemisphere, code)


_brain_db: Optional[BrainDB] = None

def get_db() -> BrainDB:
    global _brain_db
    if _brain_db is None:
        _brain_db = BrainDB()
    return _brain_db