import asyncio
import os
import traceback

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

# Gemini
from google import genai
from google.genai import types as genai_types

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

ADMIN_ID = 6179388927

AD_PRICE = 1.00
MIN_WITHDRAW = 5.00

# Main Gemini model
GEMINI_MODEL = "gemini-3.8-flash"

# Fallback model
GEMINI_FALLBACK_MODEL = "gemini-2.5-flash"


# ============================================================
# BASIC CHECKS
# ============================================================

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN is missing. Add BOT_TOKEN to Render Environment Variables."
    )


# ============================================================
# TELEGRAM
# ============================================================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# ============================================================
# CRYPTO PAY
# ============================================================

crypto = None

if CRYPTO_TOKEN:
    try:
        crypto = AioCryptoPay(
            token=CRYPTO_TOKEN,
            network=Networks.MAIN_NET,
        )
        print("CryptoPay enabled.")
    except Exception as e:
        print("CryptoPay initialization error:", e)
        crypto = None
else:
    print("WARNING: CRYPTO_TOKEN is missing.")


# ============================================================
# GEMINI
# ============================================================

ai_client = None

if GEMINI_API_KEY:
    try:
        ai_client = genai.Client(
            api_key=GEMINI_API_KEY
        )
        print("Gemini client initialized.")
    except Exception as e:
        print("Gemini initialization error:", e)
        ai_client = None
else:
    print("WARNING: GEMINI_API_KEY is missing.")


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
# WEB SERVER - RENDER HEALTH CHECK
# ============================================================

async def handle_ping(request):
    return web.Response(
        text="Digital Pro Ads Bot is running!"
    )


async def start_web_server():
    app = web.Application()

    app.router.add_get("/", handle_ping)

    runner = web.AppRunner(app)
    await runner.setup()

    port = int(
        os.environ.get("PORT", "10000")
    )

    site = web.TCPSite(
        runner,
        "0.0.0.0",
        port,
    )

    await site.start()

    print(
        f"Web server started on port {port}"
    )


# ============================================================
# MAIN MENU
# ============================================================

main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="📢 Advertise"),
            KeyboardButton(text="➕ Add Channel"),
        ],
        [
            KeyboardButton(text="💰 Balance"),
            KeyboardButton(text="👥 Referral"),
        ],
        [
            KeyboardButton(text="💳 Deposit"),
            KeyboardButton(text="🏧 Withdraw"),
        ],
        [
            KeyboardButton(text="📊 My Ads"),
            KeyboardButton(text="🤖 AI Chat"),
        ],
    ],
    resize_keyboard=True,
)


# ============================================================
# START
# ============================================================

@dp.message(CommandStart())
async def start_handler(
    message: types.Message,
    command: CommandObject,
):

    user_id = message.from_user.id

    referrer_id = None

    if command.args and command.args.isdigit():

        potential_ref = int(command.args)

        if potential_ref != user_id:
            referrer_id = potential_ref

    await add_user(
        user_id,
        referrer_id
    )

    await message.answer(
        f"ሰላም {message.from_user.first_name}! "
        f"ወደ **Global Ad Network Bot** በደህና መጡ።\n\n"
        "📢 ማስታወቂያ ለማስተዋወቅ ወይም "
        "የራስዎን ቻናል ለመመዝገብ "
        "ከታች ያሉትን አዝራሮች ይጠቀሙ።",
        reply_markup=main_menu,
        parse_mode="Markdown",
    )


# ============================================================
# 🤖 AI CHAT START
# ============================================================

@dp.message(F.text == "🤖 AI Chat")
async def ai_chat_start(
    message: types.Message,
    state: FSMContext,
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
        "ለምሳሌ፦\n"
        "• ለTelegram channel ማስታወቂያ ጻፍልኝ\n"
        "• Give me a business idea\n"
        "• Write an advertising post\n"
        "• Explain AI\n\n"
        "ለመውጣት **🔙 Back to Menu** ይጫኑ።",
        reply_markup=cancel_btn,
        parse_mode="Markdown",
    )


# ============================================================
# AI EXIT
# ============================================================

@dp.message(
    BotStates.waiting_for_ai_prompt,
    F.text == "🔙 Back to Menu",
)
async def ai_chat_exit(
    message: types.Message,
    state: FSMContext,
):

    await state.clear()

    await message.answer(
        "ወደ ዋናው ሜኑ ተመልሰዋል።",
        reply_markup=main_menu,
    )


# ============================================================
# TELEGRAM TEXT SPLITTER
# ============================================================

def split_telegram_text(
    text: str,
    max_length: int = 4000,
):

    if not text:
        return []

    return [
        text[i:i + max_length]
        for i in range(
            0,
            len(text),
            max_length,
        )
    ]


# ============================================================
# 🤖 GEMINI AI RESPONSE
# ============================================================

@dp.message(BotStates.waiting_for_ai_prompt)
async def ai_chat_response(
    message: types.Message,
    state: FSMContext,
):

    # --------------------------------------------------------
    # Check API key
    # --------------------------------------------------------

    if not GEMINI_API_KEY:

        await message.answer(
            "⚠️ Gemini API Key አልተገኘም።\n\n"
            "Render → Environment Variables ይሂዱና "
            "`GEMINI_API_KEY` ያስገቡ።"
        )

        return


    # --------------------------------------------------------
    # Check client
    # --------------------------------------------------------

    if ai_client is None:

        await message.answer(
            "⚠️ Gemini client ሊጀምር አልቻለም።\n\n"
            "Render Logs ይመልከቱ።"
        )

        return


    # --------------------------------------------------------
    # Get prompt
    # --------------------------------------------------------

    prompt = (
        message.text or ""
    ).strip()

    if not prompt:

        await message.answer(
            "⚠️ እባክዎ ጥያቄ ያስገቡ።"
        )

        return


    # --------------------------------------------------------
    # Typing
    # --------------------------------------------------------

    try:

        await bot.send_chat_action(
            chat_id=message.chat.id,
            action="typing",
        )

    except Exception:
        pass


    # --------------------------------------------------------
    # System instruction
    # --------------------------------------------------------

    system_instruction = (
        "You are Digital Pro Ads AI Assistant. "
        "Answer naturally, clearly and accurately. "

        "If the user writes in Amharic, "
        "answer in natural Amharic. "

        "If the user writes in English, "
        "answer in English. "

        "If the user mixes Amharic and English, "
        "you may naturally use both. "

        "Help users with advertising, business, "
        "technology, coding, writing, marketing, "
        "social media and general questions. "

        "For advertising requests, provide "
        "ready-to-use practical text. "

        "Do not unnecessarily mention that you are an AI."
    )


    # --------------------------------------------------------
    # Models
    # --------------------------------------------------------

    models_to_try = [
        GEMINI_MODEL,
        GEMINI_FALLBACK_MODEL,
    ]

    answer = None


    # --------------------------------------------------------
    # Try Gemini
    # --------------------------------------------------------

    for model_name in models_to_try:

        try:

            print(
                f"Trying Gemini model: {model_name}"
            )

            # IMPORTANT:
            # Keep the first request simple.
            # This avoids SDK/config compatibility problems.

            response = await asyncio.to_thread(
                ai_client.models.generate_content,
                model=model_name,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    system_instruction=system_instruction,
                ),
            )


            if response and response.text:

                answer = response.text.strip()

                print(
                    f"Gemini success: {model_name}"
                )

                break


            print(
                f"Gemini returned empty response: {model_name}"
            )


        except Exception as e:

            print(
                "=========================================="
            )

            print(
                f"Gemini ERROR - {model_name}"
            )

            print(
                f"Error type: {type(e).__name__}"
            )

            print(
                f"Error: {str(e)}"
            )

            traceback.print_exc()

            print(
                "=========================================="
            )

            await asyncio.sleep(1)


    # --------------------------------------------------------
    # No response
    # --------------------------------------------------------

    if not answer:

        await message.answer(
            "⚠️ **AI ምላሽ ማግኘት አልተቻለም።**\n\n"
            "Gemini API Key፣ API access ወይም quota "
            "ላይ ችግር ሊኖር ይችላል።\n\n"
            "እባክዎ ትንሽ ቆይተው እንደገና ይሞክሩ።",
            parse_mode="Markdown",
        )

        return


    # --------------------------------------------------------
    # Send answer
    # --------------------------------------------------------

    for part in split_telegram_text(answer):

        try:

            await message.answer(
                part
            )

        except Exception as e:

            print(
                "Telegram AI response error:",
                e
            )

            break


# ============================================================
# 💳 DEPOSIT
# ============================================================

@dp.message(F.text == "💳 Deposit")
async def deposit_handler(
    message: types.Message,
):

    if crypto is None:

        await message.answer(
            "⚠️ Crypto Deposit አሁን አይገኝም።\n\n"
            "Render → Environment Variables ላይ "
            "`CRYPTO_TOKEN` ያስገቡ።"
        )

        return


    try:

        invoice = await crypto.create_invoice(
            asset="USDT",
            amount=1.0,
        )


        pay_keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="💳 Pay 1.00 USDT",
                        url=invoice.bot_invoice_url,
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🔄 Verify Payment",
                        callback_data=(
                            f"verify_pay:"
                            f"{invoice.invoice_id}:1.0"
                        ),
                    )
                ],
            ]
        )


        await message.answer(
            "💳 **Crypto Deposit (USDT)**\n\n"
            "ወደ ሂሳብዎ **1.00 USDT** "
            "ለመጨመር ከታች ያለውን "
            "**Pay 1.00 USDT** ይጫኑ።\n\n"
            "ክፍያውን ከፈጸሙ በኋላ "
            "**Verify Payment** ይጫኑ።",
            reply_markup=pay_keyboard,
            parse_mode="Markdown",
        )


    except Exception as e:

        print(
            "Crypto invoice error:",
            e
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
    callback: types.CallbackQuery,
):

    if crypto is None:

        await callback.answer(
            "Crypto service አይገኝም።",
            show_alert=True,
        )

        return


    try:

        _, invoice_id, amount = (
            callback.data.split(":")
        )

        invoices = await crypto.get_invoices(
            invoice_ids=[int(invoice_id)]
        )


        if invoices and invoices[0].status == "paid":

            await update_user_balance(
                callback.from_user.id,
                float(amount),
            )


            await callback.message.answer(
                f"✅ ክፍያዎ ተረጋግጧል!\n\n"
                f"💵 **{amount} USDT** "
                f"ወደ ሂሳብዎ ተጨምሯል።",
                parse_mode="Markdown",
            )

            await callback.answer()


        else:

            await callback.answer(
                "❌ ክፍያው ገና አልተጠናቀቀም።",
                show_alert=True,
            )


    except Exception as e:

        print(
            "Payment verification error:",
            e
        )

        await callback.answer(
            "⚠️ Payment verification failed.",
            show_alert=True,
        )


# ============================================================
# 🏧 WITHDRAW
# ============================================================

@dp.message(F.text == "🏧 Withdraw")
async def withdraw_start(
    message: types.Message,
    state: FSMContext,
):

    balance = await get_user_balance(
        message.from_user.id
    )


    if balance < MIN_WITHDRAW:

        await message.answer(
            f"⚠️ **ዝቅተኛው ማውጣት "
            f"የሚቻለው {MIN_WITHDRAW:.2f} USDT ነው።**\n\n"
            f"የእርስዎ ቀሪ ሂሳብ፦ "
            f"**{balance:.2f} USDT**",
            parse_mode="Markdown",
        )

        return


    await state.set_state(
        BotStates.waiting_for_withdraw_amount
    )


    await message.answer(
        f"🏧 **ገንዘብ ማውጫ**\n\n"
        f"ቀሪ ሂሳብዎ፦ **{balance:.2f} USDT**\n\n"
        f"ማውጣት የሚፈልጉትን "
        f"መጠን ያስገቡ፦\n"
        f"(ዝቅተኛው {MIN_WITHDRAW:.2f} USDT)",
        parse_mode="Markdown",
    )


@dp.message(
    BotStates.waiting_for_withdraw_amount
)
async def process_withdraw_amount(
    message: types.Message,
    state: FSMContext,
):

    try:

        amount = float(
            message.text.strip()
        )

    except (ValueError, AttributeError):

        await message.answer(
            "❌ እባክዎ ትክክለኛ የቁጥር "
            "መጠን ያስገቡ።"
        )

        return


    balance = await get_user_balance(
        message.from_user.id
    )


    if amount < MIN_WITHDRAW:

        await message.answer(
            f"❌ ዝቅተኛው "
            f"**{MIN_WITHDRAW:.2f} USDT** ነው።",
            parse_mode="Markdown",
        )

        return


    if amount > balance:

        await message.answer(
            f"❌ በቂ ቀሪ ሂሳብ የለዎትም።\n\n"
            f"ያለዎት፦ **{balance:.2f} USDT**",
            parse_mode="Markdown",
        )

        return


    await state.update_data(
        withdraw_amount=amount
    )

    await state.set_state(
        BotStates.waiting_for_withdraw_wallet
    )


    await message.answer(
        "📝 ገንዘቡ እንዲላክበት "
        "የሚፈልጉትን **USDT Wallet Address** "
        "ወይም **@CryptoBot Username** ያስገቡ፦",
        parse_mode="Markdown",
    )


@dp.message(
    BotStates.waiting_for_withdraw_wallet
)
async def process_withdraw_wallet(
    message: types.Message,
    state: FSMContext,
):

    wallet = (
        message.text or ""
    ).strip()

    data = await state.get_data()

    amount = data.get(
        "withdraw_amount"
    )

    user_id = message.from_user.id


    if not amount:

        await state.clear()

        await message.answer(
            "⚠️ Withdrawal session አልተገኘም።"
        )

        return


    deducted = await deduct_user_balance(
        user_id,
        amount,
    )


    if not deducted:

        await state.clear()

        await message.answer(
            "⚠️ ክፍያውን መፈጸም "
            "አልተቻለም።"
        )

        return


    await create_withdrawal(
        user_id,
        amount,
        wallet,
    )

    await state.clear()


    await message.answer(
        f"✅ **የማውጣት ጥያቄዎ ተልኳል!**\n\n"
        f"💵 መጠን፦ **{amount:.2f} USDT**\n"
        f"📍 አድራሻ፦ `{wallet}`\n\n"
        "አስተዳዳሪው ክፍያውን "
        "አረጋግጦ ይልክልዎታል።",
        reply_markup=main_menu,
        parse_mode="Markdown",
    )


    try:

        await bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                f"🚨 **አዲስ የማውጣት ጥያቄ**\n\n"
                f"👤 ተጠቃሚ፦ "
                f"{message.from_user.first_name} "
                f"(`{user_id}`)\n"
                f"💵 መጠን፦ "
                f"**{amount:.2f} USDT**\n"
                f"📍 አድራሻ፦ `{wallet}`"
            ),
            parse_mode="Markdown",
        )


    except Exception as e:

        print(
            "Error alerting admin:",
            e
        )


# ============================================================
# ➕ ADD CHANNEL
# ============================================================

@dp.message(F.text == "➕ Add Channel")
async def register_channel_start(
    message: types.Message,
    state: FSMContext,
):

    await state.set_state(
        BotStates.waiting_for_channel
    )


    await message.answer(
        "📌 **ቻናልዎን ለመመዝገብ፦**\n\n"
        "1. ቦቱን ወደ ቻናልዎ ያስገቡ።\n"
        "2. **Admin** ያድርጉት።\n"
        "3. የቻናልዎን Username "
        "(ለምሳሌ `@my_channel`) ይላኩ።",
        parse_mode="Markdown",
    )


@dp.message(
    BotStates.waiting_for_channel
)
async def process_channel_username(
    message: types.Message,
    state: FSMContext,
):

    channel_username = (
        message.text or ""
    ).strip()


    if not channel_username.startswith("@"):

        channel_username = (
            f"@{channel_username}"
        )


    try:

        chat = await bot.get_chat(
            channel_username
        )

        me = await bot.get_me()

        member = await bot.get_chat_member(
            chat.id,
            me.id,
        )


        if member.status not in [
            "administrator",
            "creator",
        ]:

            await message.answer(
                "❌ እባክዎ መጀመሪያ "
                "ቦቱን በቻናሉ ላይ Admin ያድርጉት!"
            )

            return


        success = await add_channel(
            message.from_user.id,
            channel_username,
            chat.title,
        )


        if success:

            await message.answer(
                f"✅ **{chat.title}** "
                f"({channel_username}) "
                f"በተሳካ ሁኔታ ተመዝግቧል!",
                reply_markup=main_menu,
                parse_mode="Markdown",
            )

        else:

            await message.answer(
                "⚠️ ይህ ቻናል "
                "አስቀድሞ ተመዝግቧል።"
            )


        await state.clear()


    except Exception as e:

        print(
            "Channel registration error:",
            e
        )

        await message.answer(
            "❌ ቻናሉን ማግኘት አልተቻለም።\n\n"
            "Username ትክክል መሆኑንና "
            "ቦቱ Admin መደረጉን ያረጋግጡ።"
        )


# ============================================================
# 📢 ADVERTISE
# ============================================================

@dp.message(F.text == "📢 Advertise")
async def choose_channel_to_advertise(
    message: types.Message,
):

    channels = await get_all_channels()


    if not channels:

        await message.answer(
            "⚠️ የተመዘገበ ቻናል የለም።\n\n"
            "በ **➕ Add Channel** የራስዎን "
            "ቻናል ይመዝግቡ።",
            parse_mode="Markdown",
        )

        return


    keyboard = []


    for username, title in channels:

        keyboard.append(
            [
                InlineKeyboardButton(
                    text=f"📢 {title} ({username})",
                    callback_data=f"adto:{username}",
                )
            ]
        )


    markup = InlineKeyboardMarkup(
        inline_keyboard=keyboard
    )


    await message.answer(
        "🎯 ማስታወቂያዎ እንዲለጠፍበት "
        "የሚፈልጉትን ቻናል ይምረጡ፦",
        reply_markup=markup,
    )


@dp.callback_query(
    F.data.startswith("adto:")
)
async def target_channel_selected(
    callback: types.CallbackQuery,
    state: FSMContext,
):

    target_channel = (
        callback.data.split(
            ":",
            1,
        )[1]
    )


    await state.update_data(
        target_channel=target_channel
    )


    await state.set_state(
        BotStates.waiting_for_ad_text
    )


    await callback.message.answer(
        f"📝 ወደ **{target_channel}** "
        "የሚለጠፈውን የማስታወቂያ "
        "ጽሑፍ ይላኩ።\n\n"
        f"💰 የአንድ ማስታወቂያ ዋጋ "
        f"**{AD_PRICE:.2f} USDT** ነው።",
        parse_mode="Markdown",
    )


    await callback.answer()


# ============================================================
# SAVE AD
# ============================================================

@dp.message(
    BotStates.waiting_for_ad_text
)
async def process_ad_submission(
    message: types.Message,
    state: FSMContext,
):

    user_id = message.from_user.id

    balance = await get_user_balance(
        user_id
    )


    if balance < AD_PRICE:

        await state.clear()


        deposit_button = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="💳 Deposit",
                        callback_data="go_to_deposit",
                    )
                ]
            ]
        )


        await message.answer(
            f"❌ **ቀሪ ሂሳብዎ በቂ አይደለም!**\n\n"
            f"ዋጋ፦ **{AD_PRICE:.2f} USDT**\n"
            f"ቀሪ ሂሳብ፦ **{balance:.2f} USDT**",
            reply_markup=deposit_button,
            parse_mode="Markdown",
        )

        return


    deducted = await deduct_user_balance(
        user_id,
        AD_PRICE,
    )


    if not deducted:

        await state.clear()

        await message.answer(
            "⚠️ ክፍያውን መፈጸም "
            "አልተቻለም።"
        )

        return


    data = await state.get_data()

    target_channel = data.get(
        "target_channel"
    )

    ad_content = (
        message.text or ""
    ).strip()


    await save_ad(
        user_id,
        target_channel,
        ad_content,
    )


    await state.clear()


    new_balance = await get_user_balance(
        user_id
    )


    await message.answer(
        f"✅ **ማስታወቂያዎ ተመዝግቧል!**\n\n"
        f"💰 የተቆረጠ፦ "
        f"**{AD_PRICE:.2f} USDT**\n"
        f"💳 አዲሱ ቀሪ ሂሳብ፦ "
        f"**{new_balance:.2f} USDT**\n\n"
        f"🎯 ቻናል፦ **{target_channel}**",
        reply_markup=main_menu,
        parse_mode="Markdown",
    )


# ============================================================
# GO TO DEPOSIT
# ============================================================

@dp.callback_query(
    F.data == "go_to_deposit"
)
async def forward_to_deposit(
    callback: types.CallbackQuery,
):

    await callback.answer()

    await deposit_handler(
        callback.message
    )


# ============================================================
# 📊 MY ADS
# ============================================================

@dp.message(F.text == "📊 My Ads")
async def my_ads_handler(
    message: types.Message,
):

    ads = await get_active_ads()


    if not ads:

        await message.answer(
            "📊 በአሁኑ ወቅት ንቁ "
            "የሆነ ማስታወቂያ የለዎትም።"
        )

        return


    text_msg = (
        "📊 **ንቁ ማስታወቂያዎች፦**\n\n"
    )


    for i, (channel, text) in enumerate(
        ads[:5],
        start=1,
    ):

        clean_preview = (
            text[:50]
            + ("..." if len(text) > 50 else "")
        )


        text_msg += (
            f"{i}. 🎯 **ቻናል፦** "
            f"{channel}\n"
            f"📝 **ጽሑፍ፦** "
            f"{clean_preview}\n\n"
        )


    await message.answer(
        text_msg,
        parse_mode="Markdown",
    )


# ============================================================
# AUTO AD POSTER
# ============================================================

async def post_ads_to_channels():

    print(
        "Running automatic ad poster..."
    )


    ads = await get_active_ads()


    for target_channel, text in ads:

        try:

            await bot.send_message(
                chat_id=target_channel,
                text=(
                    f"📢 Sponsored Ad\n\n"
                    f"{text}"
                ),
            )

            await asyncio.sleep(5)


        except Exception as e:

            print(
                f"Error posting to "
                f"{target_channel}: {e}"
            )


# ============================================================
# 💰 BALANCE
# ============================================================

@dp.message(F.text == "💰 Balance")
async def balance_handler(
    message: types.Message,
):

    balance = await get_user_balance(
        message.from_user.id
    )


    await message.answer(
        f"💰 ቀሪ ሂሳብዎ፦ "
        f"**{balance:.2f} USDT**",
        parse_mode="Markdown",
    )


# ============================================================
# 👥 REFERRAL
# ============================================================

@dp.message(F.text == "👥 Referral")
async def referral_handler(
    message: types.Message,
):

    bot_info = await bot.get_me()


    ref_link = (
        f"https://t.me/"
        f"{bot_info.username}"
        f"?start="
        f"{message.from_user.id}"
    )


    await message.answer(
        f"👥 **የመጋበዣ ሊንክዎ፦**\n\n"
        f"`{ref_link}`",
        parse_mode="Markdown",
    )


# ============================================================
# RUN BOT
# ============================================================

async def run_bot():

    await init_db()


    scheduler = AsyncIOScheduler()


    scheduler.add_job(
        post_ads_to_channels,
        "interval",
        hours=8,
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

    if GEMINI_API_KEY:

        print(
            "Gemini AI: ENABLED"
        )

    else:

        print(
            "Gemini AI: DISABLED "
            "(GEMINI_API_KEY missing)"
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


    # Start Render web server first
    await start_web_server()


    # Start Telegram bot
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