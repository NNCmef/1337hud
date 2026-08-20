from pathlib import Path

import aiosqlite


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    async def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS tracked_products (
                    user_id INTEGER NOT NULL,
                    article INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    last_price INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, article)
                )
                """
            )
            await db.commit()

    async def add_product(
        self, user_id: int, article: int, name: str, price: int
    ) -> bool:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                """
                INSERT OR IGNORE INTO tracked_products
                    (user_id, article, name, last_price)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, article, name, price),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def remove_product(self, user_id: int, article: int) -> bool:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "DELETE FROM tracked_products WHERE user_id = ? AND article = ?",
                (user_id, article),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def remove_all(self, user_id: int) -> int:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "DELETE FROM tracked_products WHERE user_id = ?", (user_id,)
            )
            await db.commit()
            return cursor.rowcount

    async def list_for_user(self, user_id: int) -> list[aiosqlite.Row]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT article, name, last_price
                FROM tracked_products
                WHERE user_id = ?
                ORDER BY created_at
                """,
                (user_id,),
            )
            return await cursor.fetchall()

    async def list_all(self) -> list[aiosqlite.Row]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT user_id, article, name, last_price FROM tracked_products"
            )
            return await cursor.fetchall()

    async def update_price(self, user_id: int, article: int, price: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                UPDATE tracked_products
                SET last_price = ?, updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ? AND article = ?
                """,
                (price, user_id, article),
            )
            await db.commit()
