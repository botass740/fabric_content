"""
Research data storage for Dzen crawler — collected articles, channels, metrics.

Separate SQLite database from the main app database (app/database/db.py).
Stored at data/research.db by default.

Usage:
    from research.storage import ResearchStorage
    storage = ResearchStorage()
    channel_id = storage.upsert_channel("fainmanomica", url="https://dzen.ru/fainmanomica")
    storage.close()
"""

import sqlite3
import logging
import threading
from pathlib import Path
from datetime import datetime
from contextlib import contextmanager
from typing import Any


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helper — not a method so it won't be confused with table-level operations
# ---------------------------------------------------------------------------


def _dictify_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    """Convert a sqlite3.Row to a plain dict, or return None if row is None."""
    return dict(row) if row is not None else None


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


class ResearchStorage:
    """SQLite-backed storage for research data collected from Dzen.

    Thread-safe: uses a threading.Lock around all public methods so multiple
    threads (e.g. background crawler + bot health check) can safely share one
    instance.
    """

    def __init__(self, db_path: str = "data/research.db") -> None:
        """Open (or create) the research database.

        Args:
            db_path: Path to the SQLite file.  ``data/`` is created if absent.
        """
        self._lock = threading.Lock()
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(
            str(self._db_path),
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row

        # Performance & integrity
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")

        self._create_tables()
        logger.info("ResearchStorage opened: %s", self._db_path)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """Execute a single SQL statement (must be called while holding the lock)."""
        return self._conn.execute(sql, params)

    @contextmanager
    def _transaction(self):
        """Context manager wrapping a COMMIT/ROLLBACK block.

        Must be called while holding ``self._lock``.
        """
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _create_tables(self) -> None:
        """Create tables and indexes if they don't already exist."""
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS channels (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                slug            TEXT UNIQUE NOT NULL,
                url             TEXT NOT NULL,
                title           TEXT,
                description     TEXT,
                subscribers     INTEGER DEFAULT 0,
                category        TEXT,
                is_active       BOOLEAN DEFAULT 1,
                last_crawled_at TIMESTAMP,
                articles_count  INTEGER DEFAULT 0,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS articles (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                dzen_id           TEXT UNIQUE NOT NULL,
                channel_id        INTEGER REFERENCES channels(id),
                url               TEXT NOT NULL,
                title             TEXT NOT NULL,
                text              TEXT,
                text_length       INTEGER DEFAULT 0,
                word_count        INTEGER DEFAULT 0,
                published_at      TIMESTAMP,
                collected_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                views             INTEGER,
                likes             INTEGER,
                comments          INTEGER,
                shares            INTEGER,
                has_images        BOOLEAN DEFAULT 0,
                images_count      INTEGER DEFAULT 0,
                has_video         BOOLEAN DEFAULT 0,
                paragraphs_count  INTEGER DEFAULT 0,
                headers_count     INTEGER DEFAULT 0,
                is_parsed         BOOLEAN DEFAULT 0,
                is_analyzed       BOOLEAN DEFAULT 0,
                created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS article_images (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                article_id  INTEGER REFERENCES articles(id),
                url         TEXT NOT NULL,
                position    INTEGER DEFAULT 0,
                is_cover    BOOLEAN DEFAULT 0,
                width       INTEGER,
                height      INTEGER,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS crawl_sessions (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                finished_at    TIMESTAMP,
                channels_count INTEGER DEFAULT 0,
                articles_found INTEGER DEFAULT 0,
                articles_new   INTEGER DEFAULT 0,
                errors_count   INTEGER DEFAULT 0,
                status         TEXT DEFAULT 'running',
                notes          TEXT
            );

            CREATE TABLE IF NOT EXISTS word_frequencies (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                word        TEXT NOT NULL UNIQUE,
                frequency   INTEGER DEFAULT 0,
                tf_idf      REAL DEFAULT 0,
                in_titles   INTEGER DEFAULT 0,
                in_texts    INTEGER DEFAULT 0,
                updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_channels_slug ON channels(slug);

            CREATE INDEX IF NOT EXISTS idx_articles_dzen_id ON articles(dzen_id);
            CREATE INDEX IF NOT EXISTS idx_articles_channel_id ON articles(channel_id);
            CREATE INDEX IF NOT EXISTS idx_articles_published_at ON articles(published_at);
            CREATE INDEX IF NOT EXISTS idx_articles_is_parsed ON articles(is_parsed);

            CREATE INDEX IF NOT EXISTS idx_word_frequencies_word ON word_frequencies(word);
            CREATE INDEX IF NOT EXISTS idx_word_frequencies_frequency ON word_frequencies(frequency);
        """
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Channels
    # ------------------------------------------------------------------

    def upsert_channel(self, slug: str, **kwargs: Any) -> int:
        """Insert a new channel or update an existing one.

        Only the columns whose keys appear in ``kwargs`` are touched on
        conflict; ``updated_at`` is always refreshed.

        Args:
            slug: Dzen channel slug, e.g. ``"fainmanomica"``.
            **kwargs: Column values — ``url``, ``title``, ``description``,
                      ``subscribers``, ``category``, ``is_active``.

        Returns:
            The channel's ``id`` (primary key).
        """
        columns = ["slug", "updated_at"]
        values: list[Any] = [slug, datetime.utcnow().isoformat()]
        set_parts: list[str] = ["updated_at = excluded.updated_at"]

        for col in (
            "url",
            "title",
            "description",
            "subscribers",
            "category",
            "is_active",
        ):
            if col in kwargs:
                columns.append(col)
                values.append(kwargs[col])
                set_parts.append(f"{col} = excluded.{col}")

        sql = (
            f"INSERT INTO channels ({', '.join(columns)}) "
            f"VALUES ({', '.join('?' for _ in columns)}) "
            f"ON CONFLICT(slug) DO UPDATE SET {', '.join(set_parts)}"
        )

        with self._lock:
            with self._transaction():
                cursor = self._execute(sql, tuple(values))
                # Fetch the real id (works for both INSERT and UPDATE)
                cursor.execute("SELECT id FROM channels WHERE slug = ?", (slug,))
                row = cursor.fetchone()
                channel_id = row["id"] if row else cursor.lastrowid

        logger.debug("Upserted channel '%s' → id=%s", slug, channel_id)
        return int(channel_id)

    def get_channel(self, slug: str) -> dict[str, Any] | None:
        """Return a single channel by slug, or ``None``."""
        with self._lock:
            row = self._execute("SELECT * FROM channels WHERE slug = ?", (slug,)).fetchone()
        return _dictify_row(row)

    def get_all_channels(self, active_only: bool = True) -> list[dict[str, Any]]:
        """Return all channels, optionally filtering to active ones."""
        with self._lock:
            if active_only:
                rows = self._execute(
                    "SELECT * FROM channels WHERE is_active = 1 ORDER BY slug"
                ).fetchall()
            else:
                rows = self._execute(
                    "SELECT * FROM channels ORDER BY slug"
                ).fetchall()
        return [dict(r) for r in rows]

    def update_channel_stats(self, channel_id: int, articles_count: int) -> None:
        """Refresh the cached ``articles_count`` for a channel."""
        with self._lock:
            with self._transaction():
                self._execute(
                    "UPDATE channels SET articles_count = ?, updated_at = ? WHERE id = ?",
                    (articles_count, datetime.utcnow().isoformat(), channel_id),
                )
        logger.debug(
            "Channel #%d articles_count → %d", channel_id, articles_count
        )

    # ------------------------------------------------------------------
    # Articles
    # ------------------------------------------------------------------

    def upsert_article(self, dzen_id: str, **kwargs: Any) -> int:
        """Insert a new article or return the existing id (no overwrite).

        If the article is new the channel's ``articles_count`` is
        recalculated from the database (accurate even after duplicates).

        Args:
            dzen_id: Unique Dzen article id extracted from the URL.
            **kwargs: Columns: ``channel_id``, ``url``, ``title``,
                      ``text``, ``text_length``, ``word_count``,
                      ``published_at``, ``views``, ``likes``, ``comments``,
                      ``shares``, ``has_images``, ``images_count``,
                      ``has_video``.

        Returns:
            Article id (existing or newly assigned).
        """
        with self._lock:
            # Check for existing article
            existing = self._execute(
                "SELECT id, channel_id FROM articles WHERE dzen_id = ?", (dzen_id,)
            ).fetchone()
            if existing:
                logger.debug("Article '%s' already exists → id=%s", dzen_id, existing["id"])
                return int(existing["id"])

            # Build INSERT
            allowed = {
                "channel_id",
                "url",
                "title",
                "text",
                "text_length",
                "word_count",
                "published_at",
                "views",
                "likes",
                "comments",
                "shares",
                "has_images",
                "images_count",
                "has_video",
            }
            columns = ["dzen_id"]
            values: list[Any] = [dzen_id]
            for col in sorted(kwargs):
                if col in allowed:
                    columns.append(col)
                    values.append(kwargs[col])

            sql = (
                f"INSERT INTO articles ({', '.join(columns)}) "
                f"VALUES ({', '.join('?' for _ in columns)})"
            )

            with self._transaction():
                cursor = self._execute(sql, tuple(values))
                article_id = int(cursor.lastrowid)

                # Update channel's article count
                channel_id = kwargs.get("channel_id")
                if channel_id:
                    self._execute(
                        """UPDATE channels SET
                               articles_count = (SELECT COUNT(*) FROM articles WHERE channel_id = ?),
                               updated_at = ?
                           WHERE id = ?""",
                        (channel_id, datetime.utcnow().isoformat(), channel_id),
                    )

        logger.info("New article '%s' → id=%s", dzen_id, article_id)
        return article_id

    def get_article(self, dzen_id: str) -> dict[str, Any] | None:
        """Return a single article by ``dzen_id``, or ``None``."""
        with self._lock:
            row = self._execute(
                "SELECT * FROM articles WHERE dzen_id = ?", (dzen_id,)
            ).fetchone()
        return _dictify_row(row)

    def get_unparsed_articles(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return articles whose text hasn't been extracted yet."""
        with self._lock:
            rows = self._execute(
                "SELECT * FROM articles WHERE is_parsed = 0 ORDER BY collected_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def mark_as_parsed(
        self,
        article_id: int,
        text: str,
        word_count: int,
        paragraphs_count: int,
        headers_count: int,
        has_images: bool,
        images_count: int,
    ) -> None:
        """Persist extracted article content and structural stats."""
        with self._lock:
            with self._transaction():
                self._execute(
                    """UPDATE articles SET
                           text = ?,
                           text_length = ?,
                           word_count = ?,
                           paragraphs_count = ?,
                           headers_count = ?,
                           has_images = ?,
                           images_count = ?,
                           is_parsed = 1
                       WHERE id = ?""",
                    (
                        text,
                        len(text),
                        word_count,
                        paragraphs_count,
                        headers_count,
                        int(has_images),
                        images_count,
                        article_id,
                    ),
                )
        logger.info("Article #%d marked as parsed (%d words)", article_id, word_count)

    def get_articles_stats(self) -> dict[str, Any]:
        """Return article counts: total, parsed, unparsed, by_channel."""
        with self._lock:
            total = self._execute("SELECT COUNT(*) FROM articles").fetchone()[0]
            parsed = self._execute(
                "SELECT COUNT(*) FROM articles WHERE is_parsed = 1"
            ).fetchone()[0]
            by_channel_rows = self._execute(
                """SELECT c.slug, c.title, COUNT(a.id) AS cnt
                   FROM articles a
                   JOIN channels c ON c.id = a.channel_id
                   GROUP BY a.channel_id
                   ORDER BY cnt DESC"""
            ).fetchall()
        return {
            "total": total,
            "parsed": parsed,
            "unparsed": total - parsed,
            "by_channel": [dict(r) for r in by_channel_rows],
        }

    # ------------------------------------------------------------------
    # Crawl sessions
    # ------------------------------------------------------------------

    def start_session(self) -> int:
        """Create a new crawl session and return its id."""
        now = datetime.utcnow().isoformat()
        with self._lock:
            with self._transaction():
                cursor = self._execute(
                    "INSERT INTO crawl_sessions (started_at, status) VALUES (?, 'running')",
                    (now,),
                )
                session_id = int(cursor.lastrowid)
        logger.info("Crawl session #%d started", session_id)
        return session_id

    def finish_session(self, session_id: int, **stats: int) -> None:
        """Mark a session as done and record aggregates.

        Accepted kwargs: ``channels_count``, ``articles_found``,
        ``articles_new``, ``errors_count``.
        """
        set_parts = ["finished_at = ?", "status = 'done'"]
        params: list[Any] = [datetime.utcnow().isoformat()]

        for col in ("channels_count", "articles_found", "articles_new", "errors_count"):
            if col in stats:
                set_parts.append(f"{col} = ?")
                params.append(stats[col])

        params.append(session_id)
        sql = f"UPDATE crawl_sessions SET {', '.join(set_parts)} WHERE id = ?"

        with self._lock:
            with self._transaction():
                self._execute(sql, tuple(params))
        logger.info("Crawl session #%d finished", session_id)

    def fail_session(self, session_id: int, error: str) -> None:
        """Mark a session as failed with an error note."""
        now = datetime.utcnow().isoformat()
        with self._lock:
            with self._transaction():
                self._execute(
                    """UPDATE crawl_sessions
                       SET finished_at = ?, status = 'failed', notes = ?
                       WHERE id = ?""",
                    (now, error, session_id),
                )
        logger.warning("Crawl session #%d failed: %s", session_id, error)

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def get_summary(self) -> dict[str, Any]:
        """Quick overview: channel / article counts, last crawl info."""
        with self._lock:
            channels_count = self._execute("SELECT COUNT(*) FROM channels").fetchone()[0]
            articles_count = self._execute("SELECT COUNT(*) FROM articles").fetchone()[0]
            parsed_count = self._execute(
                "SELECT COUNT(*) FROM articles WHERE is_parsed = 1"
            ).fetchone()[0]
            last_crawl = self._execute(
                """SELECT * FROM crawl_sessions
                   WHERE status = 'done'
                   ORDER BY finished_at DESC LIMIT 1"""
            ).fetchone()
        return {
            "channels": channels_count,
            "articles": articles_count,
            "parsed": parsed_count,
            "last_crawl": _dictify_row(last_crawl),
        }

    def close(self) -> None:
        """Close the database connection."""
        try:
            self._conn.close()
            logger.info("ResearchStorage closed: %s", self._db_path)
        except Exception:
            logger.exception("Error closing ResearchStorage")