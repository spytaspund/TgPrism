import aiosqlite, config, os.path
from contextlib import asynccontextmanager

cfg = config.Config()
DB_NAME = os.path.join(cfg.SESSIONS_DIR, "prism.db")

@asynccontextmanager
async def get_db():
    db = await aiosqlite.connect(DB_NAME, timeout=30)
    try:
        db.row_factory = aiosqlite.Row
        yield db
    finally:
        await db.close()

async def init_db():
    async with aiosqlite.connect(DB_NAME, timeout=30) as db:
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.execute("PRAGMA synchronous=NORMAL;")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                aes_key BLOB NOT NULL,
                session_string TEXT,
                last_used INTEGER DEFAULT (strftime('%s','now'))
            )
        """)
        await db.commit()

async def create_pending_session(session_id: str, aes_key: bytes):
    async with get_db() as db:
        await db.execute(
            "INSERT INTO sessions (session_id, aes_key) VALUES (?, ?)",
            (session_id, aes_key)
        )
        await db.commit()

async def save_session_string(session_id: str, session_str: str):
    async with get_db() as db:
        await db.execute(
            "UPDATE sessions SET session_string = ?, last_used = (strftime('%s','now')) WHERE session_id = ?",
            (session_str, session_id)
        )
        await db.commit()

async def get_session_data(session_id: str):
    async with get_db() as db:
        async with db.execute(
            "SELECT aes_key, session_string FROM sessions WHERE session_id = ? AND session_string IS NOT NULL", 
            (session_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return (row["aes_key"], row["session_string"])
            return None

async def update_last_used(session_id: str):
    async with get_db() as db:
        await db.execute("UPDATE sessions SET last_used = (strftime('%s','now')) WHERE session_id = ?", (session_id,))
        await db.commit()

async def delete_session(session_id: str): # manual logout via /logout route
    async with get_db() as db:
        await db.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        await db.commit()

async def cleanup_old_sessions(days_inactive: int = 30): # automatic logout via garbage collector
    seconds_in_day = 86400
    threshold = days_inactive * seconds_in_day
    async with get_db() as db:
        await db.execute("DELETE FROM sessions WHERE last_used < (strftime('%s','now') - ?)", (threshold,))
        await db.commit()