import sqlite3
import logging
from pathlib import Path
from datetime import datetime

# Статусы
STATUS_GENERATED = "generated"
STATUS_APPROVED = "approved"
STATUS_PUBLISHED = "published"
STATUS_REJECTED = "rejected"

ALL_STATUSES = {STATUS_GENERATED, STATUS_APPROVED, STATUS_PUBLISHED, STATUS_REJECTED}


class Database:

    def __init__(self, db_path: Path, logger: logging.Logger | None = None):
        self.db_path = db_path
        self.logger = logger or logging.getLogger(__name__)
        self.init_schema()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self) -> None:
        self.logger.info(f"Initializing SQLite schema at {self.db_path}")
        conn = self.connect()
        try:
            cursor = conn.cursor()
            cursor.executescript("""
                CREATE TABLE IF NOT EXISTS articles (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    title       TEXT NOT NULL,
                    content     TEXT NOT NULL,
                    image_path  TEXT,
                    status      TEXT NOT NULL,
                    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    published_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_articles_status
                    ON articles(status);

                CREATE INDEX IF NOT EXISTS idx_articles_created_at
                    ON articles(created_at);

                CREATE TABLE IF NOT EXISTS used_combinations (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    hero       TEXT NOT NULL,
                    emotion    TEXT NOT NULL,
                    format     TEXT NOT NULL,
                    trigger    TEXT NOT NULL,
                    hook_type  TEXT NOT NULL,
                    topic      TEXT,
                    article_id INTEGER,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_used_combinations_created_at
                    ON used_combinations(created_at);

                CREATE TABLE IF NOT EXISTS used_topics (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic      TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_used_topics_created_at
                    ON used_topics(created_at);

                CREATE TABLE IF NOT EXISTS autogen_slots (
                    slot_key   TEXT PRIMARY KEY,
                    article_id INTEGER,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.commit()
            self.logger.info("Database schema initialized")
        finally:
            conn.close()

    def register_combination(
        self,
        *,
        hero: str,
        emotion: str,
        format: str,
        trigger: str,
        hook_type: str,
        topic: str | None = None,
        article_id: int | None = None,
    ) -> int:
        conn = self.connect()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO used_combinations
                   (hero, emotion, format, trigger, hook_type, topic, article_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (hero, emotion, format, trigger, hook_type, topic, article_id),
            )
            conn.commit()
            combo_id = cursor.lastrowid
            self.logger.info(
                f"Registered combination #{combo_id}: {hero} / {emotion} / {format} / {trigger} / {hook_type}"
            )
            if topic:
                cursor.execute(
                    "INSERT INTO used_topics (topic) VALUES (?)",
                    (topic,),
                )
                conn.commit()
            return combo_id
        finally:
            conn.close()

    def recent_combinations(self, days: int = 30) -> list[dict]:
        conn = self.connect()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT hero, emotion, format, trigger, hook_type, created_at
                   FROM used_combinations
                   WHERE created_at >= datetime('now', ?)""",
                (f"-{int(days)} days",),
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def recent_topics(self, limit: int = 30) -> list[str]:
        conn = self.connect()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT topic FROM used_topics ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
            return [row["topic"] for row in cursor.fetchall() if row["topic"]]
        finally:
            conn.close()

    def create_article(
        self,
        title: str,
        content: str,
        image_path: str | None = None,
        status: str = STATUS_GENERATED,
    ) -> int:
        if status not in ALL_STATUSES:
            raise ValueError(f"Unknown status: {status}")
        conn = self.connect()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO articles (title, content, image_path, status, created_at)
                   VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                (title, content, image_path, status),
            )
            conn.commit()
            article_id = cursor.lastrowid
            self.logger.info(f"Created article #{article_id}: {title[:50]}")
            return article_id
        finally:
            conn.close()

    def mark_autogen_slot(self, slot_key: str, article_id: int) -> None:
        """Record that today's autogen slot produced an article (idempotent)."""
        conn = self.connect()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO autogen_slots (slot_key, article_id, created_at)
                   VALUES (?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(slot_key) DO UPDATE SET article_id = excluded.article_id""",
                (slot_key, article_id),
            )
            conn.commit()
            self.logger.info(f"Autogen slot {slot_key} marked done (article #{article_id})")
        finally:
            conn.close()

    def autogen_slot_done(self, slot_key: str) -> bool:
        conn = self.connect()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM autogen_slots WHERE slot_key = ?", (slot_key,)
            )
            return cursor.fetchone() is not None
        finally:
            conn.close()

    def backfill_autogen_slots(
        self, slot_windows_utc: list[tuple[str, str, str]]
    ) -> None:
        """Seed today's fulfilled autogen slots from existing articles.

        Migration safety net: on first run of the catch-up feature, the new
        autogen_slots table is empty, so an already-generated morning/afternoon
        article would otherwise be mistaken for a "missed" slot and re-generated.
        Each tuple is (slot_key, start_utc, end_utc); a slot is marked done if any
        article was created inside that UTC window. Idempotent.
        """
        conn = self.connect()
        try:
            cursor = conn.cursor()
            for slot_key, start_utc, end_utc in slot_windows_utc:
                cursor.execute(
                    "SELECT 1 FROM autogen_slots WHERE slot_key = ?", (slot_key,)
                )
                if cursor.fetchone():
                    continue
                cursor.execute(
                    "SELECT id FROM articles "
                    "WHERE created_at >= ? AND created_at <= ? "
                    "ORDER BY id LIMIT 1",
                    (start_utc, end_utc),
                )
                row = cursor.fetchone()
                if row:
                    cursor.execute(
                        "INSERT OR IGNORE INTO autogen_slots (slot_key, article_id) "
                        "VALUES (?, ?)",
                        (slot_key, row["id"]),
                    )
                    self.logger.info(
                        f"Autogen backfill: slot {slot_key} <- article #{row['id']}"
                    )
            conn.commit()
        finally:
            conn.close()

    def get_article(self, article_id: int) -> dict | None:
        conn = self.connect()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM articles WHERE id = ?", (article_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def update_article(
        self,
        article_id: int,
        *,
        title: str | None = None,
        content: str | None = None,
        image_path: str | None = None,
    ) -> None:
        updates = []
        params = []
        if title is not None:
            updates.append("title = ?")
            params.append(title)
        if content is not None:
            updates.append("content = ?")
            params.append(content)
        if image_path is not None:
            updates.append("image_path = ?")
            params.append(image_path)
        if not updates:
            return
        params.append(article_id)
        conn = self.connect()
        try:
            cursor = conn.cursor()
            cursor.execute(
                f"UPDATE articles SET {', '.join(updates)} WHERE id = ?",
                params,
            )
            conn.commit()
            self.logger.info(f"Updated article #{article_id}")
        finally:
            conn.close()

    def set_status(self, article_id: int, status: str) -> None:
        if status not in ALL_STATUSES:
            raise ValueError(f"Unknown status: {status}")
        conn = self.connect()
        try:
            cursor = conn.cursor()
            if status == STATUS_PUBLISHED:
                now = datetime.utcnow().isoformat()
                cursor.execute(
                    "UPDATE articles SET status = ?, published_at = ? WHERE id = ?",
                    (status, now, article_id),
                )
            else:
                cursor.execute(
                    "UPDATE articles SET status = ? WHERE id = ?",
                    (status, article_id),
                )
            conn.commit()
            self.logger.info(f"Article #{article_id} status → {status}")
        finally:
            conn.close()

    def list_articles(
        self,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict]:
        conn = self.connect()
        try:
            cursor = conn.cursor()
            if status is None:
                cursor.execute(
                    "SELECT * FROM articles ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                )
            else:
                if status not in ALL_STATUSES:
                    raise ValueError(f"Unknown status: {status}")
                cursor.execute(
                    "SELECT * FROM articles WHERE status = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (status, limit, offset),
                )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def list_queue(self, limit: int = 20) -> list[dict]:
        conn = self.connect()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT * FROM articles
                   WHERE status IN (?, ?)
                   ORDER BY
                       CASE WHEN status = ? THEN 0 ELSE 1 END,
                       created_at DESC
                   LIMIT ?""",
                (STATUS_GENERATED, STATUS_APPROVED, STATUS_GENERATED, limit),
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_last(self, status: str | None = None) -> dict | None:
        conn = self.connect()
        try:
            cursor = conn.cursor()
            if status is None:
                cursor.execute(
                    "SELECT * FROM articles ORDER BY created_at DESC LIMIT 1"
                )
            else:
                if status not in ALL_STATUSES:
                    raise ValueError(f"Unknown status: {status}")
                cursor.execute(
                    "SELECT * FROM articles WHERE status = ? ORDER BY created_at DESC LIMIT 1",
                    (status,),
                )
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def delete_article(self, article_id: int) -> None:
        conn = self.connect()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM articles WHERE id = ?", (article_id,))
            conn.commit()
            self.logger.info(f"Deleted article #{article_id}")
        finally:
            conn.close()