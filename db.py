import aiosqlite
from contextlib import asynccontextmanager

DB_NAME = "prism.db"

@asynccontextmanager
async def get_db():
    db = await aiosqlite.connect(DB_NAME, timeout=30)
    try:
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.execute("PRAGMA synchronous=NORMAL;")
        db.row_factory = aiosqlite.Row
        yield db
    finally:
        await db.close()

async def init_db():
    async with get_db() as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                aes_key BLOB NOT NULL,
                tg_session_file TEXT NOT NULL,
                is_active INTEGER DEFAULT 0
            )
        """)
        await db.commit()

async def create_pending_session(session_id: str, aes_key: bytes, tg_session_file: str):
    async with get_db() as db:
        await db.execute(
            "INSERT INTO sessions (session_id, aes_key, tg_session_file, is_active) VALUES (?, ?, ?, 0)",
            (session_id, aes_key, tg_session_file)
        )
        await db.commit()

async def activate_session(session_id: str):
    async with get_db() as db:
        await db.execute("UPDATE sessions SET is_active = 1 WHERE session_id = ?", (session_id,))
        await db.commit()

async def get_session_data(session_id: str):
    async with get_db() as db:
        async with db.execute(
            "SELECT aes_key, tg_session_file FROM sessions WHERE session_id = ? AND is_active = 1", 
            (session_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return (row["aes_key"], row["tg_session_file"])
            return None