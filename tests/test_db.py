import aiosqlite
import pytest

from bot.db import Database


@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    await database.upsert_user(1, "alice", "Alice")
    await database.upsert_user(2, None, "Боб")
    yield database
    await database.close()


async def test_add_drink_is_case_insensitive_unique(db):
    first = await db.add_drink("Кока-Кола", "газировка", 1)
    assert first is not None
    assert await db.add_drink("кока-кола", None, 2) is None
    assert (await db.find_drink_by_name("КОКА-КОЛА")).id == first


async def test_scores_and_average(db):
    drink_id = await db.add_drink("Спрайт", None, 1)
    await db.set_score(1, drink_id, 8)
    await db.set_score(2, drink_id, 5)
    await db.set_score(1, drink_id, 10)  # переоценка заменяет старую оценку
    drink = await db.get_drink(drink_id)
    assert drink.ratings_count == 2
    assert drink.avg_score == pytest.approx(7.5)


async def test_review_keeps_score(db):
    drink_id = await db.add_drink("Фанта", None, 1)
    await db.set_score(1, drink_id, 7)
    await db.set_review(1, drink_id, "Слишком сладко")
    assert await db.get_user_rating(1, drink_id) == (7, "Слишком сладко")
    await db.set_review(2, drink_id, "Норм")  # отзыв без оценки
    reviews = await db.get_reviews(drink_id, 0, 10)
    assert {r.author for r in reviews} == {"@alice", "Боб"}
    assert (await db.get_drink(drink_id)).ratings_count == 1


async def test_search_cyrillic_any_case(db):
    await db.add_drink("Квас Очаковский", "квас", 1)
    await db.add_drink("Pepsi", "газировка", 1)
    assert [d.name for d in await db.search_drinks("очак")] == ["Квас Очаковский"]
    assert [d.name for d in await db.search_drinks("ГАЗИР")] == ["Pepsi"]


async def test_personal_and_global_tiers_are_separate(db):
    a = await db.add_drink("A", None, 1)
    b = await db.add_drink("B", None, 1)
    await db.set_personal_tier(1, a, "S")
    await db.set_personal_tier(2, a, "F")
    await db.set_global_tier(b, "A", 1)
    assert (await db.personal_tier_list(1))["S"] == ["A"]
    assert (await db.personal_tier_list(2))["F"] == ["A"]
    assert (await db.global_tier_list())["A"] == ["B"]
    await db.set_personal_tier(1, a, None)
    assert not any((await db.personal_tier_list(1)).values())


async def test_delete_cascades(db):
    drink_id = await db.add_drink("Тархун", None, 1)
    await db.set_score(1, drink_id, 9)
    await db.set_personal_tier(1, drink_id, "S")
    await db.set_global_tier(drink_id, "S", 1)
    assert await db.delete_drink(drink_id)
    assert await db.get_user_rating(1, drink_id) == (None, None)
    assert not any((await db.personal_tier_list(1)).values())
    assert not any((await db.global_tier_list()).values())


async def test_top_drinks_order(db):
    a = await db.add_drink("A", None, 1)
    b = await db.add_drink("B", None, 1)
    await db.add_drink("Без оценок", None, 1)
    await db.set_score(1, a, 6)
    await db.set_score(1, b, 9)
    assert [d.name for d in await db.top_drinks()] == ["B", "A"]


async def test_review_photo(db):
    drink_id = await db.add_drink("Лимонад", None, 1)
    await db.set_review(1, drink_id, "Кисло", "file123")
    review = await db.get_review(1, drink_id)
    assert (review.text, review.photo_id, review.user_id) == ("Кисло", "file123", 1)
    assert (await db.get_reviews(drink_id, 0, 10))[0].photo_id == "file123"
    assert await db.get_review(2, drink_id) is None


async def test_old_database_gets_photo_column(tmp_path):
    path = str(tmp_path / "old.db")
    # база в формате первой версии бота, без колонки photo_id
    async with aiosqlite.connect(path) as conn:
        await conn.executescript("""
            CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, full_name TEXT NOT NULL,
                                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE drinks (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                                 name_key TEXT NOT NULL UNIQUE, category TEXT, created_by INTEGER,
                                 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE ratings (user_id INTEGER NOT NULL, drink_id INTEGER NOT NULL,
                                  score INTEGER, review TEXT,
                                  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                                  PRIMARY KEY (user_id, drink_id));
            INSERT INTO users (id, full_name) VALUES (1, 'Alice');
            INSERT INTO drinks (name, name_key) VALUES ('Квас', 'квас');
            INSERT INTO ratings (user_id, drink_id, score, review) VALUES (1, 1, 8, 'Старый отзыв');
        """)
        await conn.commit()
    database = Database(path)
    await database.connect()
    try:
        review = await database.get_review(1, 1)
        assert (review.text, review.photo_id) == ("Старый отзыв", None)
        await database.set_review(1, 1, "Новый", "pic")
        assert (await database.get_review(1, 1)).photo_id == "pic"
    finally:
        await database.close()
    # повторное подключение не ломается на уже добавленной колонке
    await database.connect()
    await database.close()
