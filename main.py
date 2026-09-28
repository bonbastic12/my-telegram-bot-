import asyncio
import os
import traceback
import hashlib
import hmac
import json
import time
import urllib.parse

from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, CommandObject
from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiocryptopay import AioCryptoPay, Networks
from google import genai

from database import (
    init_db,
    add_user,
    get_user_balance,
    update_user_balance,
    deduct_user_balance,
    add_channel,
    get_all_channels,
    save_ad,
    get_active_ads,
    create_withdrawal,
)


# ============================================================
# ENVIRONMENT VARIABLES
# ============================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CRYPTO_TOKEN = os.environ.get("CRYPTO_TOKEN", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# Render → Environment Variables
# Example:
# https://your-app.onrender.com/miniapp
WEBAPP_URL = os.environ.get("WEBAPP_URL", "").strip()

ADMIN_ID = 6179388927

AD_PRICE = 1.00
MIN_WITHDRAW = 5.00

GEMINI_MODEL = "gemini-3.8-flash"
GEMINI_FALLBACK_MODEL = "gemini-2.5-flash"


# ============================================================
# PATHS
# ============================================================

BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

WEBAPP_FILE = os.path.join(
    BASE_DIR,
    "webapp",
    "index.html"
)


# ============================================================
# BASIC CHECK
# ============================================================

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN is missing. "
        "Add BOT_TOKEN to Render Environment Variables."
    )


# ============================================================
# TELEGRAM
# ============================================================

bot = Bot(
    token=BOT_TOKEN
)

dp = Dispatcher()


# ============================================================
# CRYPTOPAY
# ============================================================

crypto = None

if CRYPTO_TOKEN:
    try:
        crypto = AioCryptoPay(
            token=CRYPTO_TOKEN,
            network=Networks.MAIN_NET,
        )

        print("CryptoPay: ENABLED")

    except Exception as e:

        print(
            "CryptoPay initialization error:",
            type(e).__name__,
            str(e)
        )

        crypto = None

else:

    print(
        "CryptoPay: DISABLED - CRYPTO_TOKEN missing"
    )


# ============================================================
# GEMINI
# ============================================================

ai_client = None

if GEMINI_API_KEY:

    try:

        ai_client = genai.Client(
            api_key=GEMINI_API_KEY
        )

        print(
            "Gemini client: INITIALIZED"
        )

    except Exception as e:

        print(
            "Gemini initialization error:",
            type(e).__name__,
            str(e)
        )

        ai_client = None

else:

    print(
        "Gemini AI: DISABLED - GEMINI_API_KEY missing"
    )


# ============================================================
# PAYMENT PROTECTION
# ============================================================

processed_invoices = set()

# Mini App invoices created during current runtime
pending_invoices = {}


# ============================================================
# STATES
# ============================================================

class BotStates(StatesGroup):

    waiting_for_channel = State()

    waiting_for_ad_channel = State()

    waiting_for_ad_text = State()

    waiting_for_withdraw_amount = State()

    waiting_for_withdraw_wallet = State()

    waiting_for_ai_prompt = State()


# ============================================================
# TELEGRAM MINI APP VALIDATION
# ============================================================

def validate_telegram_init_data(
    init_data: str
):
    """
    Verify Telegram WebApp initData.

    Returns Telegram user dict if valid.
    Returns None if invalid.
    """

    if not init_data or not BOT_TOKEN:
        return None

    try:

        parsed = urllib.parse.parse_qsl(
            init_data,
            keep_blank_values=True
        )

        data = dict(parsed)

        received_hash = data.pop(
            "hash",
            None
        )

        if not received_hash:
            return None

        data_check_string = "\n".join(
            f"{key}={data[key]}"
            for key in sorted(data)
        )

        secret_key = hmac.new(
            b"WebAppData",
            BOT_TOKEN.encode(),
            hashlib.sha256
        ).digest()

        calculated_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(
            calculated_hash,
            received_hash
        ):
            return None

        auth_date = int(
            data.get(
                "auth_date",
                "0"
            )
        )

        # Reject very old sessions
        if time.time() - auth_date > 86400:
            return None

        user_json = data.get("user")

        if not user_json:
            return None

        return json.loads(user_json)

    except Exception as e:

        print(
            "Mini App validation error:",
            type(e).__name__,
            str(e)
        )

        return None


def get_miniapp_user(request):
    """
    Get authenticated Telegram user
    from Mini App request.
    """

    init_data = request.headers.get(
        "X-Telegram-Init-Data",
        ""
    )

    return validate_telegram_init_data(
        init_data
    )


def unauthorized():
    return web.json_response(
        {
            "error": "Unauthorized. Open the Mini App from Telegram."
        },
        status=401
    )


# ============================================================
# RENDER PING
# ============================================================

async def handle_ping(request):

    return web.Response(
        text="Digital Pro Ads Bot is running!"
    )


# ============================================================
# MINI APP PAGE
# ============================================================

async def miniapp_page(request):

    if not os.path.exists(WEBAPP_FILE):

        return web.Response(
            text=(
                "Mini App file not found. "
                "Create webapp/index.html"
            ),
            status=500
        )

    return web.FileResponse(
        WEBAPP_FILE
    )


# ============================================================
# API: ME
# ============================================================

async def api_me(request):

    user = get_miniapp_user(request)

    if not user:
        return unauthorized()

    user_id = int(
        user["id"]
    )

    try:

        await add_user(
            user_id,
            None
        )

        balance = await get_user_balance(
            user_id
        )

        return web.json_response(
            {
                "id": user_id,
                "first_name": user.get(
                    "first_name",
                    ""
                ),
                "username": user.get(
                    "username",
                    ""
                ),
                "balance": float(
                    balance or 0
                )
            }
        )

    except Exception as e:

        print(
            "API /me error:",
            type(e).__name__,
            str(e)
        )

        return web.json_response(
            {
                "error": "Could not load account."
            },
            status=500
        )


# ============================================================
# API: ACTIVE ADS
# ============================================================

async def api_my_ads(request):

    user = get_miniapp_user(request)

    if not user:
        return unauthorized()

    try:

        ads = await get_active_ads()

        result = []

        for channel, text in ads:

            result.append(
                {
                    "channel": channel,
                    "text": text
                }
            )

        return web.json_response(
            {
                "ads": result
            }
        )

    except Exception as e:

        print(
            "API /my-ads error:",
            type(e).__name__,
            str(e)
        )

        return web.json_response(
            {
                "error": "Could not load ads."
            },
            status=500
        )


# ============================================================
# API: REFERRAL
# ============================================================

async def api_referral(request):

    user = get_miniapp_user(request)

    if not user:
        return unauthorized()

    try:

        bot_info = await bot.get_me()

        link = (
            f"https://t.me/"
            f"{bot_info.username}"
            f"?start={user['id']}"
        )

        return web.json_response(
            {
                "link": link
            }
        )

    except Exception as e:

        print(
            "API referral error:",
            e
        )

        return web.json_response(
            {
                "error": "Could not create referral link."
            },
            status=500
        )


# ============================================================
# API: CHANNELS
# ============================================================

async def api_channels(request):

    user = get_miniapp_user(request)

    if not user:
        return unauthorized()

    try:

        body = await request.json()

    except Exception:

        return web.json_response(
            {
                "error": "Invalid JSON."
            },
            status=400
        )

    username = str(
        body.get(
            "username",
            ""
        )
    ).strip()

    if not username:

        return web.json_response(
            {
                "error": "Channel username is required."
            },
            status=400
        )

    if not username.startswith("@"):

        username = "@" + username

    try:

        chat = await bot.get_chat(
            username
        )

        me = await bot.get_me()

        member = await bot.get_chat_member(
            chat.id,
            me.id
        )

        if member.status not in [
            "administrator",
            "creator"
        ]:

            return web.json_response(
                {
                    "error": (
                        "Make the bot an administrator "
                        "of the channel first."
                    )
                },
                status=400
            )

        success = await add_channel(
            int(user["id"]),
            username,
            chat.title
        )

        if success:

            return web.json_response(
                {
                    "message": (
                        f"{chat.title} registered successfully."
                    )
                }
            )

        return web.json_response(
            {
                "message": "Channel already registered."
            }
        )

    except Exception as e:

        print(
            "Mini App channel error:",
            type(e).__name__,
            str(e)
        )

        return web.json_response(
            {
                "error": (
                    "Channel not found or "
                    "bot is not an admin."
                )
            },
            status=400
        )


# ============================================================
# API: ADVERTISE
# ============================================================

async def api_advertise(request):

    user = get_miniapp_user(request)

    if not user:
        return unauthorized()

    try:

        body = await request.json()

    except Exception:

        return web.json_response(
            {
                "error": "Invalid JSON."
            },
            status=400
        )

    user_id = int(
        user["id"]
    )

    channel = str(
        body.get(
            "channel",
            ""
        )
    ).strip()

    ad_text = str(
        body.get(
            "text",
            ""
        )
    ).strip()

    if not channel:

        return web.json_response(
            {
                "error": "Channel is required."
            },
            status=400
        )

    if not ad_text:

        return web.json_response(
            {
                "error": "Advertisement text is required."
            },
            status=400
        )

    if not channel.startswith("@"):

        channel = "@" + channel

    balance = await get_user_balance(
        user_id
    )

    if balance < AD_PRICE:

        return web.json_response(
            {
                "error": (
                    f"Insufficient balance. "
                    f"Required: {AD_PRICE:.2f} USDT."
                )
            },
            status=400
        )

    deducted = await deduct_user_balance(
        user_id,
        AD_PRICE
    )

    if not deducted:

        return web.json_response(
            {
                "error": "Could not deduct balance."
            },
            status=400
        )

    try:

        await save_ad(
            user_id,
            channel,
            ad_text
        )

    except Exception as e:

        print(
            "Mini App save ad error:",
            type(e).__name__,
            str(e)
        )

        # Refund if saving failed
        try:

            await update_user_balance(
                user_id,
                AD_PRICE
            )

        except Exception as refund_error:

            print(
                "Refund error:",
                type(refund_error).__name__,
                str(refund_error)
            )

        return web.json_response(
            {
                "error": (
                    "Advertisement could not be saved. "
                    "Your balance was refunded."
                )
            },
            status=500
        )

    new_balance = await get_user_balance(
        user_id
    )

    return web.json_response(
        {
            "message": (
                "Advertisement submitted successfully."
            ),
            "charged": AD_PRICE,
            "balance": float(
                new_balance or 0
            )
        }
    )


# ============================================================
# API: WITHDRAW
# ============================================================

async def api_withdraw(request):

    user = get_miniapp_user(request)

    if not user:
        return unauthorized()

    try:

        body = await request.json()

    except Exception:

        return web.json_response(
            {
                "error": "Invalid JSON."
            },
            status=400
        )

    user_id = int(
        user["id"]
    )

    wallet = str(
        body.get(
            "wallet",
            ""
        )
    ).strip()

    try:

        amount = float(
            body.get(
                "amount"
            )
        )

    except Exception:

        return web.json_response(
            {
                "error": "Invalid withdrawal amount."
            },
            status=400
        )

    balance = await get_user_balance(
        user_id
    )

    if amount < MIN_WITHDRAW:

        return web.json_response(
            {
                "error": (
                    f"Minimum withdrawal is "
                    f"{MIN_WITHDRAW:.2f} USDT."
                )
            },
            status=400
        )

    if amount > balance:

        return web.json_response(
            {
                "error": (
                    f"Insufficient balance. "
                    f"Available: {balance:.2f} USDT."
                )
            },
            status=400
        )

    if not wallet:

        return web.json_response(
            {
                "error": "Wallet is required."
            },
            status=400
        )

    deducted = await deduct_user_balance(
        user_id,
        amount
    )

    if not deducted:

        return web.json_response(
            {
                "error": "Could not process withdrawal."
            },
            status=400
        )

    try:

        await create_withdrawal(
            user_id,
            amount,
            wallet
        )

    except Exception as e:

        print(
            "Create withdrawal error:",
            type(e).__name__,
            str(e)
        )

        # Refund
        try:

            await update_user_balance(
                user_id,
                amount
            )

        except Exception:
            pass

        return web.json_response(
            {
                "error": (
                    "Withdrawal could not be created. "
                    "Your balance was refunded."
                )
            },
            status=500
        )

    # Notify admin
    try:

        await bot.send_message(

            chat_id=ADMIN_ID,

            text=(
                "🚨 New Mini App withdrawal\n\n"
                f"User: {user.get('first_name', '')}\n"
                f"ID: {user_id}\n"
                f"Amount: {amount:.2f} USDT\n"
                f"Wallet: {wallet}"
            )

        )

    except Exception as e:

        print(
            "Admin notification error:",
            e
        )

    return web.json_response(
        {
            "message": (
                "Withdrawal request submitted successfully."
            ),
            "amount": amount
        }
    )


# ============================================================
# API: CREATE DEPOSIT
# ============================================================

async def api_deposit(request):

    user = get_miniapp_user(request)

    if not user:
        return unauthorized()

    if crypto is None:

        return web.json_response(
            {
                "error": (
                    "CryptoPay is not configured."
                )
            },
            status=503
        )

    try:

        invoice = await crypto.create_invoice(
            asset="USDT",
            amount=1.0
        )

        invoice_id = int(
            invoice.invoice_id
        )

        pending_invoices[
            invoice_id
        ] = int(
            user["id"]
        )

        return web.json_response(
            {
                "url": invoice.bot_invoice_url,
                "invoice_id": invoice_id,
                "amount": 1.0
            }
        )

    except Exception as e:

        print(
            "Mini App deposit error:",
            type(e).__name__,
            str(e)
        )

        return web.json_response(
            {
                "error": (
                    "Could not create deposit invoice."
                )
            },
            status=500
        )


# ============================================================
# API: VERIFY DEPOSIT
# ============================================================

async def api_verify_deposit(request):

    user = get_miniapp_user(request)

    if not user:
        return unauthorized()

    if crypto is None:

        return web.json_response(
            {
                "error": "CryptoPay unavailable."
            },
            status=503
        )

    try:

        body = await request.json()

        invoice_id = int(
            body.get(
                "invoice_id"
            )
        )

    except Exception:

        return web.json_response(
            {
                "error": "Invalid invoice ID."
            },
            status=400
        )

    user_id = int(
        user["id"]
    )

    # Make sure this invoice belongs to this user
    if pending_invoices.get(
        invoice_id
    ) != user_id:

        return web.json_response(
            {
                "error": "Invoice does not belong to this account."
            },
            status=403
        )

    if invoice_id in processed_invoices:

        return web.json_response(
            {
                "message": "Payment already credited."
            }
        )

    try:

        invoices = await crypto.get_invoices(
            invoice_ids=[
                invoice_id
            ]
        )

        if not invoices:

            return web.json_response(
                {
                    "error": "Invoice not found."
                },
                status=404
            )

        invoice = invoices[0]

        if invoice.status != "paid":

            return web.json_response(
                {
                    "paid": False,
                    "message": (
                        "Payment is not completed yet."
                    )
                }
            )

        actual_amount = float(
            invoice.amount
        )

        await update_user_balance(
            user_id,
            actual_amount
        )

        processed_invoices.add(
            invoice_id
        )

        pending_invoices.pop(
            invoice_id,
            None
        )

        return web.json_response(
            {
                "paid": True,
                "amount": actual_amount,
                "message": (
                    "Payment verified and balance credited."
                )
            }
        )

    except Exception as e:

        print(
            "Mini App payment verification error:",
            type(e).__name__,
            str(e)
        )

        return web.json_response(
            {
                "error": "Payment verification failed."
            },
            status=500
        )


# ============================================================
# API: AI
# ============================================================

async def api_ai(request):

    user = get_miniapp_user(request)

    if not user:
        return unauthorized()

    if not ai_client:

        return web.json_response(
            {
                "error": (
                    "Gemini AI is not configured."
                )
            },
            status=503
        )

    try:

        body = await request.json()

    except Exception:

        return web.json_response(
            {
                "error": "Invalid JSON."
            },
            status=400
        )

    prompt = str(
        body.get(
            "prompt",
            ""
        )
    ).strip()

    if not prompt:

        return web.json_response(
            {
                "error": "Enter a question."
            },
            status=400
        )

    system_instruction = (
        "You are Digital Pro Ads AI Assistant. "
        "Answer naturally, accurately and helpfully. "
        "If the user writes in Amharic, answer in Amharic. "
        "If English, answer in English. "
        "If mixed, respond naturally. "
        "Help with business, advertising, marketing, "
        "technology, coding, writing and general questions. "
        "Keep answers clear and useful."
    )

    full_prompt = (
        f"{system_instruction}\n\n"
        f"User:\n{prompt}"
    )

    for model_name in [
        GEMINI_MODEL,
        GEMINI_FALLBACK_MODEL
    ]:

        try:

            print(
                f"Mini App Gemini: {model_name}"
            )

            response = await asyncio.to_thread(

                ai_client.models.generate_content,

                model=model_name,

                contents=full_prompt,
            )

            if response and response.text:

                return web.json_response(
                    {
                        "answer": response.text.strip()
                    }
                )

        except Exception as e:

            print(
                f"Mini App Gemini error "
                f"{model_name}:",
                type(e).__name__,
                str(e)
            )

            await asyncio.sleep(1)

    return web.json_response(
        {
            "error": (
                "Gemini quota, API access "
                "or model error."
            )
        },
        status=503
    )


# ============================================================
# START WEB SERVER
# ============================================================

async def start_web_server():

    app = web.Application()

    # Main Render health page
    app.router.add_get(
        "/",
        handle_ping
    )

    # Telegram Mini App
    app.router.add_get(
        "/miniapp",
        miniapp_page
    )

    # Mini App APIs
    app.router.add_get(
        "/api/me",
        api_me
    )

    app.router.add_get(
        "/api/my-ads",
        api_my_ads
    )

    app.router.add_get(
        "/api/referral",
        api_referral
    )

    app.router.add_post(
        "/api/channels",
        api_channels
    )

    app.router.add_post(
        "/api/advertise",
        api_advertise
    )

    app.router.add_post(
        "/api/withdraw",
        api_withdraw
    )

    app.router.add_post(
        "/api/deposit",
        api_deposit
    )

    app.router.add_post(
        "/api/deposit/verify",
        api_verify_deposit
    )

    app.router.add_post(
        "/api/ai",
        api_ai
    )

    runner = web.AppRunner(
        app
    )

    await runner.setup()

    port = int(
        os.environ.get(
            "PORT",
            "10000"
        )
    )

    site = web.TCPSite(
        runner,
        "0.0.0.0",
        port
    )

    await site.start()

    print(
        f"Web server started on port {port}"
    )

    print(
        f"Mini App URL: "
        f"{WEBAPP_URL or 'NOT SET'}"
    )


# ============================================================
# MAIN MENU
# ============================================================

main_menu = ReplyKeyboardMarkup(

    keyboard=[

        [
            KeyboardButton(
                text="📢 Advertise"
            ),
            KeyboardButton(
                text="➕ Add Channel"
            ),
        ],

        [
            KeyboardButton(
                text="💰 Balance"
            ),
            KeyboardButton(
                text="👥 Referral"
            ),
        ],

        [
            KeyboardButton(
                text="💳 Deposit"
            ),
            KeyboardButton(
                text="🏧 Withdraw"
            ),
        ],

        [
            KeyboardButton(
                text="📊 My Ads"
            ),
            KeyboardButton(
                text="🤖 AI Chat"
            ),
        ],

    ],

    resize_keyboard=True,
)


# ============================================================
# START COMMAND
# ============================================================

@dp.message(CommandStart())
async def start_handler(
    message: types.Message,
    command: CommandObject
):

    user_id = message.from_user.id

    referrer_id = None

    if command.args and command.args.isdigit():

        potential_ref = int(
            command.args
        )

        if potential_ref != user_id:

            referrer_id = potential_ref

    await add_user(
        user_id,
        referrer_id
    )

    mini_button = None

    if WEBAPP_URL:

        mini_button = InlineKeyboardMarkup(

            inline_keyboard=[

                [

                    InlineKeyboardButton(
                        text="📱 Open Digital Pro Ads",
                        web_app=types.WebAppInfo(
                            url=WEBAPP_URL
                        )
                    )

                ]

            ]

        )

    await message.answer(

        f"ሰላም {message.from_user.first_name}! "
        f"ወደ **Global Ad Network Bot** "
        f"በደህና መጡ።\n\n"

        "📢 ማስታወቂያ\n"
        "💰 Balance\n"
        "💳 Deposit\n"
        "🏧 Withdraw\n"
        "🤖 AI Assistant\n"
        "➕ Add Channel",

        reply_markup=mini_button or main_menu,

        parse_mode="Markdown",
    )


# ============================================================
# AI CHAT START
# ============================================================

@dp.message(F.text == "🤖 AI Chat")
async def ai_chat_start(
    message: types.Message,
    state: FSMContext
):

    await state.set_state(
        BotStates.waiting_for_ai_prompt
    )

    cancel_btn = ReplyKeyboardMarkup(

        keyboard=[

            [
                KeyboardButton(
                    text="🔙 Back to Menu"
                )
            ]

        ],

        resize_keyboard=True,
    )

    await message.answer(

        "🤖 **Digital Pro Ads AI Assistant**\n\n"

        "ጥያቄዎን በአማርኛ ወይም English ይጻፉ።\n\n"

        "ለመውጣት "
        "**🔙 Back to Menu** ይጫኑ።",

        reply_markup=cancel_btn,

        parse_mode="Markdown",
    )


# ============================================================
# AI EXIT
# ============================================================

@dp.message(
    BotStates.waiting_for_ai_prompt,
    F.text == "🔙 Back to Menu"
)
async def ai_chat_exit(
    message: types.Message,
    state: FSMContext
):

    await state.clear()

    await message.answer(
        "ወደ ዋናው ሜኑ ተመልሰዋል።",
        reply_markup=main_menu
    )


# ============================================================
# AI RESPONSE
# ============================================================

@dp.message(
    BotStates.waiting_for_ai_prompt
)
async def ai_chat_response(
    message: types.Message,
    state: FSMContext
):

    if not ai_client:

        await message.answer(
            "⚠️ Gemini AI አልተዘጋጀም።"
        )

        return

    prompt = (
        message.text or ""
    ).strip()

    if not prompt:

        await message.answer(
            "⚠️ ጥያቄ ያስገቡ።"
        )

        return

    system_instruction = (
        "You are Digital Pro Ads AI Assistant. "
        "Answer naturally and accurately. "
        "If the user writes Amharic, answer Amharic. "
        "If English, answer English. "
        "If mixed, respond naturally. "
        "Help with business, advertising, marketing, "
        "technology, coding and general questions."
    )

    full_prompt = (
        f"{system_instruction}\n\n"
        f"User:\n{prompt}"
    )

    answer = None

    for model_name in [
        GEMINI_MODEL,
        GEMINI_FALLBACK_MODEL
    ]:

        try:

            response = await asyncio.to_thread(

                ai_client.models.generate_content,

                model=model_name,

                contents=full_prompt
            )

            if response and response.text:

                answer = response.text.strip()

                break

        except Exception as e:

            print(
                f"Gemini error {model_name}:",
                type(e).__name__,
                str(e)
            )

    if not answer:

        await message.answer(
            "⚠️ AI ምላሽ ማግኘት አልተቻለም። "
            "Gemini quota/API access ያረጋግጡ።"
        )

        return

    for i in range(
        0,
        len(answer),
        4000
    ):

        await message.answer(
            answer[i:i + 4000]
        )


# ============================================================
# DEPOSIT
# ============================================================

@dp.message(F.text == "💳 Deposit")
async def deposit_handler(
    message: types.Message
):

    if crypto is None:

        await message.answer(
            "⚠️ CryptoPay አልተዘጋጀም።"
        )

        return

    try:

        invoice = await crypto.create_invoice(
            asset="USDT",
            amount=1.0
        )

        keyboard = InlineKeyboardMarkup(

            inline_keyboard=[

                [
                    InlineKeyboardButton(
                        text="💳 Pay 1.00 USDT",
                        url=invoice.bot_invoice_url
                    )
                ],

                [
                    InlineKeyboardButton(
                        text="🔄 Verify Payment",
                        callback_data=(
                            f"verify_pay:"
                            f"{invoice.invoice_id}:1.0"
                        )
                    )
                ]

            ]
        )

        await message.answer(

            "💳 **Crypto Deposit**\n\n"
            "1.00 USDT ለመጨመር "
            "**Pay 1.00 USDT** ይጫኑ።\n\n"
            "ከከፈሉ በኋላ "
            "**Verify Payment** ይጫኑ።",

            reply_markup=keyboard,
            parse_mode="Markdown"
        )

    except Exception as e:

        print(
            "Deposit error:",
            type(e).__name__,
            str(e)
        )

        await message.answer(
            "⚠️ Deposit invoice መፍጠር አልተቻለም።"
        )


# ============================================================
# VERIFY PAYMENT
# ============================================================

@dp.callback_query(
    F.data.startswith("verify_pay:")
)
async def check_payment_status(
    callback: types.CallbackQuery
):

    if crypto is None:

        await callback.answer(
            "CryptoPay unavailable.",
            show_alert=True
        )

        return

    try:

        parts = callback.data.split(":")

        invoice_id = int(
            parts[1]
        )

        if invoice_id in processed_invoices:

            await callback.answer(
                "Payment already credited.",
                show_alert=True
            )

            return

        invoices = await crypto.get_invoices(
            invoice_ids=[
                invoice_id
            ]
        )

        if not invoices:

            await callback.answer(
                "Invoice not found.",
                show_alert=True
            )

            return

        invoice = invoices[0]

        if invoice.status != "paid":

            await callback.answer(
                "❌ Payment not completed yet.",
                show_alert=True
            )

            return

        actual_amount = float(
            invoice.amount
        )

        await update_user_balance(
            callback.from_user.id,
            actual_amount
        )

        processed_invoices.add(
            invoice_id
        )

        try:

            await callback.message.edit_reply_markup(
                reply_markup=None
            )

        except Exception:
            pass

        await callback.message.answer(

            f"✅ **Payment verified!**\n\n"
            f"💵 **{actual_amount:.2f} USDT** "
            f"added to your balance.",

            parse_mode="Markdown"
        )

        await callback.answer(
            "Payment verified!"
        )

    except Exception as e:

        print(
            "Payment verification error:",
            type(e).__name__,
            str(e)
        )

        await callback.answer(
            "Payment verification failed.",
            show_alert=True
        )


# ============================================================
# WITHDRAW
# ============================================================

@dp.message(F.text == "🏧 Withdraw")
async def withdraw_start(
    message: types.Message,
    state: FSMContext
):

    balance = await get_user_balance(
        message.from_user.id
    )

    if balance < MIN_WITHDRAW:

        await message.answer(

            f"⚠️ Minimum withdrawal: "
            f"**{MIN_WITHDRAW:.2f} USDT**\n\n"
            f"Balance: **{balance:.2f} USDT**",

            parse_mode="Markdown"
        )

        return

    await state.set_state(
        BotStates.waiting_for_withdraw_amount
    )

    await message.answer(

        f"🏧 Withdrawal\n\n"
        f"Balance: **{balance:.2f} USDT**\n\n"
        f"Amount to withdraw "
        f"(minimum {MIN_WITHDRAW:.2f}):",

        parse_mode="Markdown"
    )


# ============================================================
# WITHDRAW AMOUNT
# ============================================================

@dp.message(
    BotStates.waiting_for_withdraw_amount
)
async def process_withdraw_amount(
    message: types.Message,
    state: FSMContext
):

    try:

        amount = float(
            message.text.strip()
        )

    except Exception:

        await message.answer(
            "❌ ትክክለኛ ቁጥር ያስገቡ።"
        )

        return

    balance = await get_user_balance(
        message.from_user.id
    )

    if amount < MIN_WITHDRAW:

        await message.answer(
            f"❌ Minimum: {MIN_WITHDRAW:.2f} USDT"
        )

        return

    if amount > balance:

        await message.answer(
            f"❌ Balance: {balance:.2f} USDT"
        )

        return

    await state.update_data(
        withdraw_amount=amount
    )

    await state.set_state(
        BotStates.waiting_for_withdraw_wallet
    )

    await message.answer(
        "📍 USDT Wallet Address "
        "ወይም @CryptoBot Username ያስገቡ።"
    )


# ============================================================
# WITHDRAW WALLET
# ============================================================

@dp.message(
    BotStates.waiting_for_withdraw_wallet
)
async def process_withdraw_wallet(
    message: types.Message,
    state: FSMContext
):

    wallet = (
        message.text or ""
    ).strip()

    if not wallet:

        await message.answer(
            "❌ Wallet address ያስገቡ።"
        )

        return

    data = await state.get_data()

    amount = data.get(
        "withdraw_amount"
    )

    user_id = message.from_user.id

    if not amount:

        await state.clear()

        await message.answer(
            "⚠️ Withdrawal session expired."
        )

        return

    deducted = await deduct_user_balance(
        user_id,
        amount
    )

    if not deducted:

        await state.clear()

        await message.answer(
            "⚠️ Withdrawal failed."
        )

        return

    try:

        await create_withdrawal(
            user_id,
            amount,
            wallet
        )

    except Exception as e:

        print(
            "Withdrawal save error:",
            e
        )

        try:

            await update_user_balance(
                user_id,
                amount
            )

        except Exception:
            pass

        await state.clear()

        await message.answer(
            "⚠️ Withdrawal failed. Balance refunded."
        )

        return

    await state.clear()

    await message.answer(

        f"✅ **Withdrawal request submitted!**\n\n"
        f"💵 {amount:.2f} USDT\n"
        f"📍 `{wallet}`",

        reply_markup=main_menu,
        parse_mode="Markdown"
    )

    try:

        await bot.send_message(

            ADMIN_ID,

            (
                "🚨 New Withdrawal\n\n"
                f"User: {message.from_user.first_name}\n"
                f"ID: {user_id}\n"
                f"Amount: {amount:.2f} USDT\n"
                f"Wallet: {wallet}"
            )
        )

    except Exception as e:

        print(
            "Admin notification error:",
            e
        )


# ============================================================
# ADD CHANNEL
# ============================================================

@dp.message(F.text == "➕ Add Channel")
async def register_channel_start(
    message: types.Message,
    state: FSMContext
):

    await state.set_state(
        BotStates.waiting_for_channel
    )

    await message.answer(

        "📌 **Add Channel**\n\n"
        "1. Bot-ን ወደ channel ያስገቡ።\n"
        "2. Admin ያድርጉት።\n"
        "3. @channel_username ይላኩ።",

        parse_mode="Markdown"
    )


# ============================================================
# PROCESS CHANNEL
# ============================================================

@dp.message(
    BotStates.waiting_for_channel
)
async def process_channel_username(
    message: types.Message,
    state: FSMContext
):

    username = (
        message.text or ""
    ).strip()

    if not username:

        await message.answer(
            "❌ Channel username ያስገቡ።"
        )

        return

    if not username.startswith("@"):

        username = "@" + username

    try:

        chat = await bot.get_chat(
            username
        )

        me = await bot.get_me()

        member = await bot.get_chat_member(
            chat.id,
            me.id
        )

        if member.status not in [
            "administrator",
            "creator"
        ]:

            await message.answer(
                "❌ Bot-ን Admin ያድርጉት።"
            )

            return

        success = await add_channel(
            message.from_user.id,
            username,
            chat.title
        )

        await state.clear()

        if success:

            await message.answer(

                f"✅ **{chat.title}** "
                f"ተመዝግቧል።",

                reply_markup=main_menu,
                parse_mode="Markdown"
            )

        else:

            await message.answer(
                "⚠️ Channel አስቀድሞ ተመዝግቧል።",
                reply_markup=main_menu
            )

    except Exception as e:

        print(
            "Channel error:",
            type(e).__name__,
            str(e)
        )

        await message.answer(
            "❌ Channel ማግኘት አልተቻለም።"
        )


# ============================================================
# ADVERTISE
# ============================================================

@dp.message(F.text == "📢 Advertise")
async def choose_channel_to_advertise(
    message: types.Message
):

    channels = await get_all_channels()

    if not channels:

        await message.answer(
            "⚠️ የተመዘገበ Channel የለም።"
        )

        return

    keyboard = []

    for username, title in channels:

        keyboard.append(

            [
                InlineKeyboardButton(
                    text=f"📢 {title}",
                    callback_data=f"adto:{username}"
                )
            ]

        )

    await message.answer(

        "🎯 ማስታወቂያ የሚለጠፍበትን Channel ይምረጡ።",

        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=keyboard
        )
    )


# ============================================================
# SELECT AD CHANNEL
# ============================================================

@dp.callback_query(
    F.data.startswith("adto:")
)
async def target_channel_selected(
    callback: types.CallbackQuery,
    state: FSMContext
):

    target_channel = callback.data.split(
        ":",
        1
    )[1]

    await state.update_data(
        target_channel=target_channel
    )

    await state.set_state(
        BotStates.waiting_for_ad_text
    )

    await callback.message.answer(

        f"📝 ወደ **{target_channel}** "
        f"የሚለጠፈውን ማስታወቂያ ይላኩ።\n\n"
        f"💰 Price: **{AD_PRICE:.2f} USDT**",

        parse_mode="Markdown"
    )

    await callback.answer()


# ============================================================
# SUBMIT AD
# ============================================================

@dp.message(
    BotStates.waiting_for_ad_text
)
async def process_ad_submission(
    message: types.Message,
    state: FSMContext
):

    user_id = message.from_user.id

    ad_content = (
        message.text or ""
    ).strip()

    if not ad_content:

        await message.answer(
            "❌ Advertisement text ያስገቡ።"
        )

        return

    data = await state.get_data()

    target_channel = data.get(
        "target_channel"
    )

    if not target_channel:

        await state.clear()

        await message.answer(
            "⚠️ Channel session አልተገኘም።"
        )

        return

    balance = await get_user_balance(
        user_id
    )

    if balance < AD_PRICE:

        await state.clear()

        await message.answer(

            f"❌ Balance በቂ አይደለም።\n\n"
            f"Price: {AD_PRICE:.2f} USDT\n"
            f"Balance: {balance:.2f} USDT",

            parse_mode="Markdown"
        )

        return

    deducted = await deduct_user_balance(
        user_id,
        AD_PRICE
    )

    if not deducted:

        await state.clear()

        await message.answer(
            "⚠️ Balance deduction failed."
        )

        return

    try:

        await save_ad(
            user_id,
            target_channel,
            ad_content
        )

    except Exception as e:

        print(
            "Save ad error:",
            type(e).__name__,
            str(e)
        )

        # Refund
        try:

            await update_user_balance(
                user_id,
                AD_PRICE
            )

        except Exception:
            pass

        await state.clear()

        await message.answer(
            "⚠️ Ad save failed. Balance refunded."
        )

        return

    await state.clear()

    new_balance = await get_user_balance(
        user_id
    )

    await message.answer(

        f"✅ **Advertisement submitted!**\n\n"
        f"💵 Charged: {AD_PRICE:.2f} USDT\n"
        f"💰 Balance: {new_balance:.2f} USDT\n"
        f"🎯 Channel: {target_channel}",

        reply_markup=main_menu,
        parse_mode="Markdown"
    )


# ============================================================
# MY ADS
# ============================================================

@dp.message(F.text == "📊 My Ads")
async def my_ads_handler(
    message: types.Message
):

    ads = await get_active_ads()

    if not ads:

        await message.answer(
            "📊 Active ads የሉም።"
        )

        return

    text_msg = (
        "📊 **Active Ads**\n\n"
    )

    for i, (
        channel,
        text
    ) in enumerate(
        ads[:5],
        start=1
    ):

        preview = (
            text[:50]
            + (
                "..."
                if len(text) > 50
                else ""
            )
        )

        text_msg += (
            f"{i}. 🎯 {channel}\n"
            f"📝 {preview}\n\n"
        )

    await message.answer(
        text_msg,
        parse_mode="Markdown"
    )


# ============================================================
# AUTO POST ADS
# ============================================================

async def post_ads_to_channels():

    print(
        "Running automatic ad poster..."
    )

    try:

        ads = await get_active_ads()

    except Exception as e:

        print(
            "Could not get ads:",
            e
        )

        return

    for target_channel, text in ads:

        try:

            await bot.send_message(

                chat_id=target_channel,

                text=(
                    "📢 Sponsored Ad\n\n"
                    f"{text}"
                )
            )

            await asyncio.sleep(5)

        except Exception as e:

            print(
                f"Error posting to "
                f"{target_channel}:",
                type(e).__name__,
                str(e)
            )


# ============================================================
# BALANCE
# ============================================================

@dp.message(F.text == "💰 Balance")
async def balance_handler(
    message: types.Message
):

    balance = await get_user_balance(
        message.from_user.id
    )

    await message.answer(

        f"💰 **Balance:** "
        f"{balance:.2f} USDT",

        parse_mode="Markdown"
    )


# ============================================================
# REFERRAL
# ============================================================

@dp.message(F.text == "👥 Referral")
async def referral_handler(
    message: types.Message
):

    bot_info = await bot.get_me()

    link = (
        f"https://t.me/"
        f"{bot_info.username}"
        f"?start="
        f"{message.from_user.id}"
    )

    await message.answer(

        "👥 **Referral Link**\n\n"
        f"`{link}`",

        parse_mode="Markdown"
    )


# ============================================================
# RUN BOT
# ============================================================

async def run_bot():

    await init_db()

    # --------------------------------------------------------
    # Telegram Mini App Menu Button
    # --------------------------------------------------------

    if WEBAPP_URL:

        try:

            await bot.set_chat_menu_button(

                menu_button=types.MenuButtonWebApp(

                    text="📱 Mini App",

                    web_app=types.WebAppInfo(
                        url=WEBAPP_URL
                    )
                )
            )

            print(
                "Telegram Mini App menu button: ENABLED"
            )

        except Exception as e:

            print(
                "Mini App menu button error:",
                type(e).__name__,
                str(e)
            )

    else:

        print(
            "WEBAPP_URL missing - Mini App button disabled"
        )

    # --------------------------------------------------------
    # Scheduler
    # --------------------------------------------------------

    scheduler = AsyncIOScheduler()

    scheduler.add_job(
        post_ads_to_channels,
        "interval",
        hours=8
    )

    scheduler.start()

    print(
        "===================================="
    )

    print(
        "Digital Pro Ads Bot started!"
    )

    print(
        f"Gemini model: {GEMINI_MODEL}"
    )

    print(
        "Gemini AI:",
        "ENABLED" if ai_client else "DISABLED"
    )

    print(
        "CryptoPay:",
        "ENABLED" if crypto else "DISABLED"
    )

    print(
        "Mini App:",
        "ENABLED" if WEBAPP_URL else "DISABLED"
    )

    print(
        "===================================="
    )

    await dp.start_polling(
        bot
    )


# ============================================================
# MAIN
# ============================================================

async def main():

    print(
        "Starting Digital Pro Ads..."
    )

    await start_web_server()

    await run_bot()


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    try:

        asyncio.run(
            main()
        )

    except KeyboardInterrupt:

        print(
            "Bot stopped."
        )

    except Exception:

        print(
            "FATAL ERROR:"
        )

        traceback.print_exc()

        raise