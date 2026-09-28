import aiosqlite

DB_NAME = "bot_database.db"

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                referrer_id INTEGER,
                balance REAL DEFAULT 0.0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS ads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                ad_text TEXT,
                status TEXT DEFAULT 'pending'
            )
        """)
        await db.commit()

async def add_user(user_id: int, referrer_id: int = None):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
        user = await cursor.fetchone()
        
        if not user:
            await db.execute(
                "INSERT INTO users (user_id, referrer_id) VALUES (?, ?)", 
                (user_id, referrer_id)
            )
            if referrer_id:
                await db.execute(
                    "UPDATE users SET balance = balance + 0.50 WHERE user_id = ?", 
                    (referrer_id,)
                )
            await db.commit()
            return True
        return False

async def get_user_balance(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        result = await cursor.fetchone()
        return result[0] if result else 0.0

async def save_ad(user_id: int, text: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT INTO ads (user_id, ad_text, status) VALUES (?, ?, 'active')", (user_id, text))
        await db.commit()

async def get_all_active_ads():
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT ad_text FROM ads WHERE status = 'active'")
        return await cursor.fetchall()
