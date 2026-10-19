"""Работа с базой данных SQLite."""

from dataclasses import dataclass

import aiosqlite

TIERS = ("S", "A", "B", "C", "D", "F")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id         INTEGER PRIMARY KEY,
    username   TEXT,
    full_name  TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS drinks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    -- casefold() от названия: COLLATE NOCASE в SQLite не понимает кириллицу.
    name_key   TEXT NOT NULL UNIQUE,
    category   TEXT,
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Одна запись на пару (пользователь, напиток): оценка и/или отзыв.
CREATE TABLE IF NOT EXISTS ratings (
    user_id    INTEGER NOT NULL REFERENCES users(id),
    drink_id   INTEGER NOT NULL REFERENCES drinks(id) ON DELETE CASCADE,
    score      INTEGER CHECK (score BETWEEN 1 AND 10),
    review     TEXT,
    photo_id   TEXT,  -- file_id фото из Telegram, необязательно
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, drink_id)
);

-- Личный тир-лист каждого пользователя.
CREATE TABLE IF NOT EXISTS personal_tiers (
    user_id    INTEGER NOT NULL REFERENCES users(id),
    drink_id   INTEGER NOT NULL REFERENCES drinks(id) ON DELETE CASCADE,
    tier       TEXT NOT NULL CHECK (tier IN ('S','A','B','C','D','F')),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, drink_id)
);

-- Общий тир-лист, который ведут админы.
CREATE TABLE IF NOT EXISTS global_tiers (
    drink_id   INTEGER PRIMARY KEY REFERENCES drinks(id) ON DELETE CASCADE,
    tier       TEXT NOT NULL CHECK (tier IN ('S','A','B','C','D','F')),
    set_by     INTEGER REFERENCES users(id),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


@dataclass
class Drink:
    id: int
    name: str
    category: str | None
    avg_score: float | None
    ratings_count: int


@dataclass
class Review:
    author: str
    score: int | None
    text: str
    photo_id: str | None = None
    user_id: int | None = None


@dataclass
class TierEntry:
    tier: str
    name: str
    score: float | None
    photo_id: str | None


# Фото напитка для картинки: свежее фото из отзывов (своё — в приоритете для личного списка).
_LATEST_PHOTO = """
(SELECT p.photo_id FROM ratings p
 WHERE p.drink_id = d.id AND p.photo_id IS NOT NULL
 ORDER BY p.user_id = ? DESC, p.updated_at DESC LIMIT 1)
"""


_DRINK_SELECT = """
SELECT d.id, d.name, d.category,
       AVG(r.score) AS avg_score,
       COUNT(r.score) AS ratings_count
FROM drinks d
LEFT JOIN ratings r ON r.drink_id = d.id
"""


def _drink(row) -> Drink:
    return Drink(row[0], row[1], row[2], row[3], row[4])


class Database:
    def __init__(self, path: str):
        self.path = path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self.path)
        await self._conn.execute("PRAGMA foreign_keys = ON")
        await self._conn.executescript(SCHEMA)
        await self._migrate()
        await self._conn.commit()

    async def _migrate(self) -> None:
        """Докидывает новые колонки в базы, созданные старыми версиями бота."""
        cur = await self._conn.execute("PRAGMA table_info(ratings)")
        columns = {row[1] for row in await cur.fetchall()}
        if "photo_id" not in columns:
            await self._conn.execute("ALTER TABLE ratings ADD COLUMN photo_id TEXT")

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        assert self._conn is not None, "Database.connect() не вызван"
        return self._conn

    # --- пользователи ---

    async def upsert_user(self, user_id: int, username: str | None, full_name: str) -> None:
        await self.conn.execute(
            """
            INSERT INTO users (id, username, full_name) VALUES (?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET username = excluded.username,
                                          full_name = excluded.full_name
            """,
            (user_id, username, full_name),
        )
        await self.conn.commit()

    # --- напитки ---

    async def add_drink(self, name: str, category: str | None, user_id: int) -> int | None:
        """Возвращает id нового напитка или None, если такой уже есть."""
        try:
            cur = await self.conn.execute(
                "INSERT INTO drinks (name, name_key, category, created_by) VALUES (?, ?, ?, ?)",
                (name, name.casefold(), category, user_id),
            )
        except aiosqlite.IntegrityError:
            return None
        await self.conn.commit()
        return cur.lastrowid

    async def get_drink(self, drink_id: int) -> Drink | None:
        cur = await self.conn.execute(
            _DRINK_SELECT + " WHERE d.id = ? GROUP BY d.id", (drink_id,)
        )
        row = await cur.fetchone()
        return _drink(row) if row else None

    async def find_drink_by_name(self, name: str) -> Drink | None:
        cur = await self.conn.execute(
            _DRINK_SELECT + " WHERE d.name_key = ? GROUP BY d.id", (name.casefold(),)
        )
        row = await cur.fetchone()
        return _drink(row) if row else None

    async def count_drinks(self) -> int:
        cur = await self.conn.execute("SELECT COUNT(*) FROM drinks")
        return (await cur.fetchone())[0]

    async def list_drinks(self, offset: int, limit: int) -> list[Drink]:
        cur = await self.conn.execute(
            _DRINK_SELECT + " GROUP BY d.id ORDER BY d.name_key LIMIT ? OFFSET ?",
            (limit, offset),
        )
        return [_drink(r) for r in await cur.fetchall()]

    async def search_drinks(self, query: str, limit: int = 20) -> list[Drink]:
        # LIKE в SQLite не понимает регистр кириллицы, поэтому фильтруем в Python.
        cur = await self.conn.execute(
            _DRINK_SELECT + " GROUP BY d.id ORDER BY d.name_key"
        )
        q = query.casefold()
        found = [
            _drink(r)
            for r in await cur.fetchall()
            if q in r[1].casefold() or (r[2] and q in r[2].casefold())
        ]
        return found[:limit]

    async def top_drinks(self, limit: int = 10) -> list[Drink]:
        cur = await self.conn.execute(
            _DRINK_SELECT
            + """ GROUP BY d.id HAVING COUNT(r.score) > 0
                  ORDER BY avg_score DESC, ratings_count DESC, d.name_key
                  LIMIT ?""",
            (limit,),
        )
        return [_drink(r) for r in await cur.fetchall()]

    async def delete_drink(self, drink_id: int) -> bool:
        cur = await self.conn.execute("DELETE FROM drinks WHERE id = ?", (drink_id,))
        await self.conn.commit()
        return cur.rowcount > 0

    # --- оценки и отзывы ---

    async def set_score(self, user_id: int, drink_id: int, score: int) -> None:
        await self.conn.execute(
            """
            INSERT INTO ratings (user_id, drink_id, score) VALUES (?, ?, ?)
            ON CONFLICT(user_id, drink_id) DO UPDATE
                SET score = excluded.score, updated_at = CURRENT_TIMESTAMP
            """,
            (user_id, drink_id, score),
        )
        await self.conn.commit()

    async def set_review(self, user_id: int, drink_id: int, text: str,
                         photo_id: str | None = None) -> None:
        """Новый отзыв заменяет старый вместе с фото."""
        await self.conn.execute(
            """
            INSERT INTO ratings (user_id, drink_id, review, photo_id) VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, drink_id) DO UPDATE
                SET review = excluded.review, photo_id = excluded.photo_id,
                    updated_at = CURRENT_TIMESTAMP
            """,
            (user_id, drink_id, text, photo_id),
        )
        await self.conn.commit()

    async def delete_review(self, user_id: int, drink_id: int) -> bool:
        """Удаляет отзыв и фото; оценка остаётся, если она была."""
        cur = await self.conn.execute(
            """
            UPDATE ratings SET review = NULL, photo_id = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ? AND drink_id = ? AND review IS NOT NULL
            """,
            (user_id, drink_id),
        )
        await self.conn.execute(
            "DELETE FROM ratings WHERE user_id = ? AND drink_id = ? AND score IS NULL AND review IS NULL",
            (user_id, drink_id),
        )
        await self.conn.commit()
        return cur.rowcount > 0

    async def get_user_rating(self, user_id: int, drink_id: int) -> tuple[int | None, str | None]:
        cur = await self.conn.execute(
            "SELECT score, review FROM ratings WHERE user_id = ? AND drink_id = ?",
            (user_id, drink_id),
        )
        row = await cur.fetchone()
        return (row[0], row[1]) if row else (None, None)

    async def get_review(self, user_id: int, drink_id: int) -> Review | None:
        cur = await self.conn.execute(
            """
            SELECT COALESCE('@' || u.username, u.full_name), r.score, r.review,
                   r.photo_id, r.user_id
            FROM ratings r JOIN users u ON u.id = r.user_id
            WHERE r.user_id = ? AND r.drink_id = ? AND r.review IS NOT NULL
            """,
            (user_id, drink_id),
        )
        row = await cur.fetchone()
        return Review(*row) if row else None

    async def count_reviews(self, drink_id: int) -> int:
        cur = await self.conn.execute(
            "SELECT COUNT(*) FROM ratings WHERE drink_id = ? AND review IS NOT NULL",
            (drink_id,),
        )
        return (await cur.fetchone())[0]

    async def get_reviews(self, drink_id: int, offset: int, limit: int) -> list[Review]:
        cur = await self.conn.execute(
            """
            SELECT COALESCE('@' || u.username, u.full_name), r.score, r.review,
                   r.photo_id, r.user_id
            FROM ratings r JOIN users u ON u.id = r.user_id
            WHERE r.drink_id = ? AND r.review IS NOT NULL
            ORDER BY r.updated_at DESC
            LIMIT ? OFFSET ?
            """,
            (drink_id, limit, offset),
        )
        return [Review(*r) for r in await cur.fetchall()]

    # --- тир-листы ---

    async def set_personal_tier(self, user_id: int, drink_id: int, tier: str | None) -> None:
        if tier is None:
            await self.conn.execute(
                "DELETE FROM personal_tiers WHERE user_id = ? AND drink_id = ?",
                (user_id, drink_id),
            )
        else:
            await self.conn.execute(
                """
                INSERT INTO personal_tiers (user_id, drink_id, tier) VALUES (?, ?, ?)
                ON CONFLICT(user_id, drink_id) DO UPDATE
                    SET tier = excluded.tier, updated_at = CURRENT_TIMESTAMP
                """,
                (user_id, drink_id, tier),
            )
        await self.conn.commit()

    async def set_global_tier(self, drink_id: int, tier: str | None, admin_id: int) -> None:
        if tier is None:
            await self.conn.execute("DELETE FROM global_tiers WHERE drink_id = ?", (drink_id,))
        else:
            await self.conn.execute(
                """
                INSERT INTO global_tiers (drink_id, tier, set_by) VALUES (?, ?, ?)
                ON CONFLICT(drink_id) DO UPDATE
                    SET tier = excluded.tier, set_by = excluded.set_by,
                        updated_at = CURRENT_TIMESTAMP
                """,
                (drink_id, tier, admin_id),
            )
        await self.conn.commit()

    async def get_personal_tier(self, user_id: int, drink_id: int) -> str | None:
        cur = await self.conn.execute(
            "SELECT tier FROM personal_tiers WHERE user_id = ? AND drink_id = ?",
            (user_id, drink_id),
        )
        row = await cur.fetchone()
        return row[0] if row else None

    async def get_global_tier(self, drink_id: int) -> str | None:
        cur = await self.conn.execute(
            "SELECT tier FROM global_tiers WHERE drink_id = ?", (drink_id,)
        )
        row = await cur.fetchone()
        return row[0] if row else None

    async def personal_tier_list(self, user_id: int) -> dict[str, list[str]]:
        cur = await self.conn.execute(
            """
            SELECT t.tier, d.name FROM personal_tiers t JOIN drinks d ON d.id = t.drink_id
            WHERE t.user_id = ? ORDER BY d.name_key
            """,
            (user_id,),
        )
        return _group(await cur.fetchall())

    async def personal_tier_entries(self, user_id: int) -> list[TierEntry]:
        """Личный тир-лист для картинки: под фото — своя оценка."""
        cur = await self.conn.execute(
            f"""
            SELECT t.tier, d.name, r.score, {_LATEST_PHOTO}
            FROM personal_tiers t JOIN drinks d ON d.id = t.drink_id
            LEFT JOIN ratings r ON r.drink_id = d.id AND r.user_id = t.user_id
            WHERE t.user_id = ? ORDER BY d.name_key
            """,
            (user_id, user_id),
        )
        return [TierEntry(*r) for r in await cur.fetchall()]

    async def global_tier_entries(self) -> list[TierEntry]:
        """Общий тир-лист для картинки: под фото — средняя оценка."""
        cur = await self.conn.execute(
            f"""
            SELECT t.tier, d.name, (SELECT AVG(score) FROM ratings WHERE drink_id = d.id),
                   {_LATEST_PHOTO}
            FROM global_tiers t JOIN drinks d ON d.id = t.drink_id
            ORDER BY d.name_key
            """,
            (0,),
        )
        return [TierEntry(*r) for r in await cur.fetchall()]

    async def global_tier_list(self) -> dict[str, list[str]]:
        cur = await self.conn.execute(
            """
            SELECT t.tier, d.name FROM global_tiers t JOIN drinks d ON d.id = t.drink_id
            ORDER BY d.name_key
            """
        )
        return _group(await cur.fetchall())


def _group(rows) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {t: [] for t in TIERS}
    for tier, name in rows:
        result[tier].append(name)
    return result
