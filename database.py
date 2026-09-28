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
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id INTEGER,
                channel_username TEXT UNIQUE,
                title TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS ads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                advertiser_id INTEGER,
                target_channel TEXT,
                ad_text TEXT,
                status TEXT DEFAULT 'active'
            )
        """)
        # የገንዘብ ማውጣት ጥያቄዎች ሰንጠረዥ
        await db.execute("""
            CREATE TABLE IF NOT EXISTS withdrawals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount REAL,
                wallet_address TEXT,
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

async def update_user_balance(user_id: int, amount: float):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        await db.commit()

async def deduct_user_balance(user_id: int, amount: float):
    async with aiosqlite.connect(DB_NAME) as db:
        balance = await get_user_balance(user_id)
        if balance >= amount:
            await db.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, user_id))
            await db.commit()
            return True
        return False

async def add_channel(owner_id: int, username: str, title: str):
    async with aiosqlite.connect(DB_NAME) as db:
        try:
            await db.execute(
                "INSERT INTO channels (owner_id, channel_username, title) VALUES (?, ?, ?)",
                (owner_id, username, title)
            )
            await db.commit()
            return True
        except Exception:
            return False

async def get_all_channels():
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT channel_username, title FROM channels")
        return await cursor.fetchall()

async def save_ad(advertiser_id: int, target_channel: str, text: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT INTO ads (advertiser_id, target_channel, ad_text) VALUES (?, ?, ?)",
            (advertiser_id, target_channel, text)
        )
        await db.commit()

async def get_active_ads():
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT target_channel, ad_text FROM ads WHERE status = 'active'")
        return await cursor.fetchall()

# አዲስ የማውጣት ጥያቄ መመዝገቢያ
async def create_withdrawal(user_id: int, amount: float, wallet: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT INTO withdrawals (user_id, amount, wallet_address) VALUES (?, ?, ?)",
            (user_id, amount, wallet)
        )
        await db.commit()
