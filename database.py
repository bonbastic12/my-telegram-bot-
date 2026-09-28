import aiosqlite

DB_NAME = "bot_database.db"


# ============================================================
# INIT DATABASE
# ============================================================

async def init_db():

    async with aiosqlite.connect(DB_NAME) as db:

        # USERS
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                referrer_id INTEGER,
                balance REAL DEFAULT 0.0
            )
        """)

        # CHANNELS
        await db.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id INTEGER,
                channel_username TEXT UNIQUE,
                title TEXT
            )
        """)

        # ADS
        await db.execute("""
            CREATE TABLE IF NOT EXISTS ads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                advertiser_id INTEGER,
                target_channel TEXT,
                ad_text TEXT,
                status TEXT DEFAULT 'active'
            )
        """)

        # WITHDRAWALS
        await db.execute("""
            CREATE TABLE IF NOT EXISTS withdrawals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount REAL,
                wallet_address TEXT,
                status TEXT DEFAULT 'pending'
            )
        """)

        # DEPOSITS
        await db.execute("""
            CREATE TABLE IF NOT EXISTS deposits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_id INTEGER UNIQUE,
                user_id INTEGER,
                amount REAL,
                status TEXT DEFAULT 'pending'
            )
        """)

        await db.commit()


# ============================================================
# USER
# ============================================================

async def add_user(
    user_id: int,
    referrer_id: int = None
):

    async with aiosqlite.connect(DB_NAME) as db:

        cursor = await db.execute(
            """
            SELECT user_id
            FROM users
            WHERE user_id = ?
            """,
            (user_id,)
        )

        user = await cursor.fetchone()

        if user:
            return False

        await db.execute(
            """
            INSERT INTO users
            (
                user_id,
                referrer_id,
                balance
            )
            VALUES (?, ?, 0.0)
            """,
            (
                user_id,
                referrer_id
            )
        )

        # Referral bonus
        if referrer_id:

            await db.execute(
                """
                UPDATE users
                SET balance = balance + 0.50
                WHERE user_id = ?
                """,
                (referrer_id,)
            )

        await db.commit()

        return True


# ============================================================
# BALANCE
# ============================================================

async def get_user_balance(
    user_id: int
):

    async with aiosqlite.connect(DB_NAME) as db:

        cursor = await db.execute(
            """
            SELECT balance
            FROM users
            WHERE user_id = ?
            """,
            (user_id,)
        )

        result = await cursor.fetchone()

        if result:
            return float(result[0])

        return 0.0


# ============================================================
# ADD BALANCE
# ============================================================

async def update_user_balance(
    user_id: int,
    amount: float
):

    async with aiosqlite.connect(DB_NAME) as db:

        await db.execute(
            """
            UPDATE users
            SET balance = balance + ?
            WHERE user_id = ?
            """,
            (
                amount,
                user_id
            )
        )

        await db.commit()


# ============================================================
# DEDUCT BALANCE
# ============================================================

async def deduct_user_balance(
    user_id: int,
    amount: float
):

    async with aiosqlite.connect(DB_NAME) as db:

        cursor = await db.execute(
            """
            SELECT balance
            FROM users
            WHERE user_id = ?
            """,
            (user_id,)
        )

        result = await cursor.fetchone()

        if not result:
            return False

        balance = float(result[0])

        if balance < amount:
            return False

        await db.execute(
            """
            UPDATE users
            SET balance = balance - ?
            WHERE user_id = ?
            """,
            (
                amount,
                user_id
            )
        )

        await db.commit()

        return True


# ============================================================
# CHANNEL
# ============================================================

async def add_channel(
    owner_id: int,
    username: str,
    title: str
):

    async with aiosqlite.connect(DB_NAME) as db:

        try:

            await db.execute(
                """
                INSERT INTO channels
                (
                    owner_id,
                    channel_username,
                    title
                )
                VALUES (?, ?, ?)
                """,
                (
                    owner_id,
                    username,
                    title
                )
            )

            await db.commit()

            return True

        except Exception:

            return False


# ============================================================
# ALL CHANNELS
# ============================================================

async def get_all_channels():

    async with aiosqlite.connect(DB_NAME) as db:

        cursor = await db.execute(
            """
            SELECT
                channel_username,
                title
            FROM channels
            """
        )

        return await cursor.fetchall()


# ============================================================
# USER CHANNELS
# ============================================================

async def get_user_channels(
    owner_id: int
):

    async with aiosqlite.connect(DB_NAME) as db:

        cursor = await db.execute(
            """
            SELECT
                channel_username,
                title
            FROM channels
            WHERE owner_id = ?
            """,
            (owner_id,)
        )

        return await cursor.fetchall()


# ============================================================
# SAVE AD
# ============================================================

async def save_ad(
    advertiser_id: int,
    target_channel: str,
    text: str
):

    async with aiosqlite.connect(DB_NAME) as db:

        await db.execute(
            """
            INSERT INTO ads
            (
                advertiser_id,
                target_channel,
                ad_text,
                status
            )
            VALUES (?, ?, ?, 'active')
            """,
            (
                advertiser_id,
                target_channel,
                text
            )
        )

        await db.commit()


# ============================================================
# ALL ACTIVE ADS
# ============================================================

async def get_active_ads():

    async with aiosqlite.connect(DB_NAME) as db:

        cursor = await db.execute(
            """
            SELECT
                target_channel,
                ad_text
            FROM ads
            WHERE status = 'active'
            """
        )

        return await cursor.fetchall()


# ============================================================
# USER ACTIVE ADS
# ============================================================

async def get_user_active_ads(
    user_id: int
):

    async with aiosqlite.connect(DB_NAME) as db:

        cursor = await db.execute(
            """
            SELECT
                target_channel,
                ad_text,
                status
            FROM ads
            WHERE advertiser_id = ?
            AND status = 'active'
            ORDER BY id DESC
            """,
            (user_id,)
        )

        return await cursor.fetchall()


# ============================================================
# DEPOSIT
# ============================================================

async def create_deposit(
    invoice_id: int,
    user_id: int,
    amount: float
):

    async with aiosqlite.connect(DB_NAME) as db:

        try:

            await db.execute(
                """
                INSERT INTO deposits
                (
                    invoice_id,
                    user_id,
                    amount,
                    status
                )
                VALUES (?, ?, ?, 'pending')
                """,
                (
                    invoice_id,
                    user_id,
                    amount
                )
            )

            await db.commit()

            return True

        except Exception:

            return False


# ============================================================
# GET DEPOSIT
# ============================================================

async def get_deposit(
    invoice_id: int
):

    async with aiosqlite.connect(DB_NAME) as db:

        cursor = await db.execute(
            """
            SELECT
                invoice_id,
                user_id,
                amount,
                status
            FROM deposits
            WHERE invoice_id = ?
            """,
            (invoice_id,)
        )

        return await cursor.fetchone()


# ============================================================
# COMPLETE DEPOSIT
# ============================================================

async def complete_deposit(
    invoice_id: int
):

    async with aiosqlite.connect(DB_NAME) as db:

        cursor = await db.execute(
            """
            SELECT
                user_id,
                amount,
                status
            FROM deposits
            WHERE invoice_id = ?
            """,
            (invoice_id,)
        )

        deposit = await cursor.fetchone()

        if not deposit:
            return False

        user_id = deposit[0]
        amount = float(deposit[1])
        status = deposit[2]

        # Already credited
        if status == "paid":
            return False

        # Credit balance
        await db.execute(
            """
            UPDATE users
            SET balance = balance + ?
            WHERE user_id = ?
            """,
            (
                amount,
                user_id
            )
        )

        # Mark invoice as paid
        await db.execute(
            """
            UPDATE deposits
            SET status = 'paid'
            WHERE invoice_id = ?
            """,
            (invoice_id,)
        )

        await db.commit()

        return True


# ============================================================
# WITHDRAWAL
# ============================================================

async def create_withdrawal(
    user_id: int,
    amount: float,
    wallet: str
):

    async with aiosqlite.connect(DB_NAME) as db:

        await db.execute(
            """
            INSERT INTO withdrawals
            (
                user_id,
                amount,
                wallet_address,
                status
            )
            VALUES (?, ?, ?, 'pending')
            """,
            (
                user_id,
                amount,
                wallet
            )
        )

        await db.commit()


# ============================================================
# USER WITHDRAWALS
# ============================================================

async def get_user_withdrawals(
    user_id: int
):

    async with aiosqlite.connect(DB_NAME) as db:

        cursor = await db.execute(
            """
            SELECT
                amount,
                wallet_address,
                status
            FROM withdrawals
            WHERE user_id = ?
            ORDER BY id DESC
            """,
            (user_id,)
        )

        return await cursor.fetchall()