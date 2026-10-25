# skills/memory_skill.py
import json
import sqlite3
import os
import uuid
import threading
import logging
from datetime import datetime
from contextlib import contextmanager
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'memory.db')
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

MAX_MESSAGE_LENGTH = 10000
DEFAULT_HISTORY_LIMIT = 100
SESSION_CONTEXT_LIMIT = 50

ALLOWED_ROLES = {'user', 'assistant', 'system'}


class MemorySkill:
    """Потокобезопасное хранилище истории диалогов на SQLite с поддержкой сессий и имён."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._lock = threading.RLock()
        self.current_session: Optional[str] = None
        self._init_db()
        # НЕ создаём автоматически сессию — только при необходимости

    @contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _validate_role(role: str) -> None:
        if role not in ALLOWED_ROLES:
            raise ValueError(f"Недопустимая роль '{role}'. Разрешены: {', '.join(ALLOWED_ROLES)}")

    @staticmethod
    def _sanitize_content(content: str) -> str:
        if not content:
            return content
        if len(content) <= MAX_MESSAGE_LENGTH:
            return content
        truncated = content[:MAX_MESSAGE_LENGTH]
        while True:
            try:
                truncated.encode('utf-8')
                break
            except UnicodeEncodeError:
                truncated = truncated[:-1]
        logger.info("Сообщение обрезано до %d символов", len(truncated))
        return truncated + "..."

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            # Создаём таблицу sessions с полем name
            conn.execute('''
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id  TEXT PRIMARY KEY,
                    name        TEXT NOT NULL,
                    created_at  TEXT NOT NULL,
                    last_activity TEXT NOT NULL
                )
            ''')
            # Проверяем, есть ли колонка name (миграция для старых БД)
            try:
                conn.execute("ALTER TABLE sessions ADD COLUMN name TEXT DEFAULT 'Чат'")
            except sqlite3.OperationalError:
                pass  # колонка уже существует

            conn.execute('''
                CREATE TABLE IF NOT EXISTS conversations (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id  TEXT    NOT NULL,
                    role        TEXT    NOT NULL,
                    content     TEXT    NOT NULL,
                    timestamp   TEXT    NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                )
            ''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_session   ON conversations(session_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_timestamp ON conversations(timestamp)')

    def new_session(self, name: Optional[str] = None) -> str:
        """Создаёт новую сессию с заданным именем (или генерирует 'Чат N')."""
        session_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        if name is None:
            # Вычисляем следующий номер чата
            all_sessions = self.get_all_sessions()
            count = len(all_sessions)
            name = f"Чат {count + 1}"
        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    "INSERT INTO sessions (session_id, name, created_at, last_activity) VALUES (?, ?, ?, ?)",
                    (session_id, name, now, now)
                )
                self.current_session = session_id
        logger.info("Создана новая сессия: %s (%s)", session_id, name)
        return session_id

    def switch_session(self, session_id: str) -> bool:
        with self._lock:
            with self._get_connection() as conn:
                row = conn.execute(
                    "SELECT 1 FROM sessions WHERE session_id=? LIMIT 1",
                    (session_id,)
                ).fetchone()
                if row:
                    self.current_session = session_id
                    now = datetime.utcnow().isoformat()
                    conn.execute(
                        "UPDATE sessions SET last_activity=? WHERE session_id=?",
                        (now, session_id)
                    )
                    logger.info("Переключились на сессию %s", session_id)
                    return True
                logger.warning("Сессия %s не найдена", session_id)
                return False

    def ensure_session(self) -> str:
        """Если нет текущей сессии, создаёт новую с именем 'Чат 1' (или следующим)."""
        if self.current_session is None:
            # Проверяем, есть ли вообще сессии в БД
            all_sessions = self.get_all_sessions()
            if all_sessions:
                # Берём последнюю созданную или первую
                self.current_session = all_sessions[-1]['session_id']
            else:
                # Создаём первую
                self.new_session("Чат 1")
        return self.current_session

    def get_session_name(self, session_id: Optional[str] = None) -> str:
        """Возвращает имя сессии."""
        target = session_id or self.current_session
        if not target:
            return "Безымянный чат"
        with self._lock:
            with self._get_connection() as conn:
                row = conn.execute(
                    "SELECT name FROM sessions WHERE session_id=?",
                    (target,)
                ).fetchone()
                if row:
                    return row['name']
                return "Безымянный чат"

    def rename_session(self, session_id: str, new_name: str) -> bool:
        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    "UPDATE sessions SET name=? WHERE session_id=?",
                    (new_name, session_id)
                )
                return True

    def add_message(self, role: str, content: str, session_id: Optional[str] = None) -> None:
        self._validate_role(role)
        content = self._sanitize_content(content)
        target = session_id or self.current_session
        if not target:
            # Если нет сессии, создаём новую с именем по умолчанию
            target = self.new_session()
        timestamp = datetime.utcnow().isoformat()
        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    "UPDATE sessions SET last_activity=? WHERE session_id=?",
                    (timestamp, target)
                )
                conn.execute(
                    "INSERT INTO conversations (session_id, role, content, timestamp) VALUES (?,?,?,?)",
                    (target, role, content, timestamp)
                )

    def get_history(self, session_id: Optional[str] = None,
                    limit: int = DEFAULT_HISTORY_LIMIT) -> List[Dict[str, str]]:
        target = session_id or self.current_session
        if not target:
            return []
        with self._lock:
            with self._get_connection() as conn:
                rows = conn.execute(
                    "SELECT role, content FROM conversations WHERE session_id=? "
                    "ORDER BY timestamp DESC LIMIT ?",
                    (target, limit)
                ).fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

    def get_context(self, limit: int = SESSION_CONTEXT_LIMIT) -> str:
        history = self.get_history(limit=limit)
        return "\n".join(f"{m['role']}: {m['content']}" for m in history)

    def clear_session(self, session_id: Optional[str] = None) -> None:
        target = session_id or self.current_session
        if not target:
            return
        with self._lock:
            with self._get_connection() as conn:
                conn.execute("DELETE FROM conversations WHERE session_id=?", (target,))
        logger.info("Сообщения сессии %s очищены", target)

    def delete_session(self, session_id: Optional[str] = None) -> bool:
        target = session_id or self.current_session
        if not target:
            return False
        with self._lock:
            with self._get_connection() as conn:
                conn.execute("DELETE FROM conversations WHERE session_id=?", (target,))
                conn.execute("DELETE FROM sessions WHERE session_id=?", (target,))
            if target == self.current_session:
                self.current_session = None
            logger.info("Сессия %s удалена", target)
            return True

    def save_session(self, session_id: Optional[str] = None,
                     filename: Optional[str] = None) -> bool:
        target = session_id or self.current_session
        if not target:
            return False
        history = self.get_history(target, limit=100000)
        if not history:
            logger.warning("Нет сообщений для сохранения в сессии %s", target)
            return False
        filename = filename or f"chat_{target[:8]}.json"
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(history, f, ensure_ascii=False, indent=2)
            logger.info("Сессия %s сохранена в %s", target, filename)
            return True
        except Exception:
            logger.exception("Не удалось сохранить сессию %s", target)
            return False

    def load_session(self, filename: str) -> Optional[str]:
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            logger.exception("Ошибка чтения файла %s", filename)
            return None
        if not data:
            return None
        session_id = self.new_session()
        for msg in data:
            if isinstance(msg, dict) and 'role' in msg and 'content' in msg:
                self.add_message(msg['role'], msg['content'], session_id)
        logger.info("Загружено %d сообщений в сессию %s", len(data), session_id)
        return session_id

    def get_all_sessions(self) -> List[Dict[str, str]]:
        with self._lock:
            with self._get_connection() as conn:
                rows = conn.execute(
                    "SELECT session_id, name, created_at, last_activity FROM sessions ORDER BY created_at DESC"
                ).fetchall()
        return [{"session_id": r["session_id"], "name": r["name"], "created": r["created_at"], "last_activity": r["last_activity"]} for r in rows]


_skill = MemorySkill()


def init(name: str) -> None:
    """Инициализация навыка: не создаём сессию, только подключаем БД."""
    logger.info("MemorySkill '%s' инициализирован. Текущая сессия: %s", name, _skill.current_session)


def handle_message(message: str) -> str:
    message = message.strip()
    if not message:
        return "OK"

    if message.startswith('/'):
        parts = message.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ''

        if cmd == '/new':
            # Создаём новую сессию с именем по умолчанию (автоматически)
            sid = _skill.new_session()
            name = _skill.get_session_name(sid)
            return f"Создан новый чат: {name}"

        if cmd == '/list':
            sessions = _skill.get_all_sessions()
            if not sessions:
                return "Нет сохранённых сессий"
            lines = ["Список чатов:"]
            for s in sessions:
                lines.append(f"  {s['name']} ({s['session_id'][:8]})")
            return "\n".join(lines)

        if cmd == '/switch':
            if not arg:
                return "Ошибка: укажите ID сессии"
            ok = _skill.switch_session(arg.strip())
            if ok:
                name = _skill.get_session_name()
                return f"Переключено на чат: {name}"
            else:
                return "Ошибка: сессия не найдена"

        if cmd == '/save':
            filename = arg.strip() if arg else None
            ok = _skill.save_session(filename=filename)
            return "Сохранено" if ok else "Ошибка сохранения"

        if cmd == '/load':
            if not arg:
                return "Ошибка: укажите имя файла"
            sid = _skill.load_session(arg.strip())
            return f"Загружено в сессию {sid}" if sid else "Ошибка загрузки"

        if cmd == '/clear':
            _skill.clear_session()
            return "Сообщения чата очищены"

        if cmd == '/delete':
            sid = arg.strip() if arg else None
            ok = _skill.delete_session(sid)
            return "Чат удалён" if ok else "Ошибка удаления"

        if cmd == '/get_context':
            ctx = _skill.get_context()
            return ctx if ctx else "Контекст пуст"

        if cmd == '/rename':
            if not arg:
                return "Ошибка: укажите новое имя"
            sid = _skill.current_session
            if sid:
                _skill.rename_session(sid, arg)
                return f"Чат переименован в '{arg}'"
            else:
                return "Нет активного чата"

        return f"Неизвестная команда: {cmd}"

    # Если сообщение не начинается с '/', считаем, что это добавление сообщения пользователя
    _skill.add_message('user', message)
    return "OK"


def shutdown(name: Optional[str] = None) -> None:
    try:
        _skill.save_session()
    except Exception:
        logger.exception("Ошибка автосохранения при shutdown")
    logger.info("MemorySkill выгружен")