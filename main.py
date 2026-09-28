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
    WebAppInfo,
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
CRYPTO_TOKEN = os.environ.get("CRYPTO_TOKEN", "639734:AAyANr5PBtEHPO5344cjssr6BQ5yGI6I7jA")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# Render ላይ የሚገኘው የዌብሳይት ሊንክ
RENDER_APP_URL = os.environ.get("RENDER_EXTERNAL_URL", "https://digital-pro-ads.onrender.com")

ADMIN_ID = 6179388927
AD_PRICE = 1.00
MIN_WITHDRAW = 5.00

# የነፃ ኮታ ገደብ (limit: 20) እንዳያስቸግር ዋናው ሞዴል
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_FALLBACK_MODEL = "gemini-1.5-flash"

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing. Add BOT_TOKEN to Render Environment Variables.")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

crypto = None
if CRYPTO_TOKEN:
    try:
        crypto = AioCryptoPay(token=CRYPTO_TOKEN, network=Networks.MAIN_NET)
        print("CryptoPay: ENABLED")
    except Exception as e:
        print("CryptoPay error:", e)

ai_client = None
if GEMINI_API_KEY:
    try:
        ai_client = genai.Client(api_key=GEMINI_API_KEY)
        print("Gemini client: INITIALIZED")
    except Exception as e:
        print("Gemini error:", e)

processed_invoices = set()


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
# WEB SERVER - HTML & RENDER HEALTH CHECK
# ============================================================
async def handle_ping(request):
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            return web.Response(text=f.read(), content_type="text/html")
    return web.Response(text="Digital Pro Ads Bot is running!")


async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)

    runner = web.AppRunner(app)
    await runner.setup()

    port = int(os.environ.get("PORT", "10000"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Web server started on port {port}")


# ============================================================
# MAIN MENU
# ============================================================
main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(
                text="🌐 Open App",
                web_app=WebAppInfo(url=RENDER_APP_URL)
            )
        ],
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
async def start_handler(message: types.Message, command: CommandObject):
    user_id = message.from_user.id
    referrer_id = None

    if command.args and command.args.isdigit():
        potential_ref = int(command.args)
        if potential_ref != user_id:
            referrer_id = potential_ref

    await add_user(user_id, referrer_id)

    await message.answer(
        f"ሰላም {message.from_user.first_name}! ወደ **Global Ad Network Bot** በደህና መጡ።\n\n"
        "📢 ማስታወቂያ ለማስተዋወቅ ወይም የራስዎን ቻናል ለመመዝገብ ከታች ያሉትን አዝራሮች ይጠቀሙ።",
        reply_markup=main_menu,
        parse_mode="Markdown",
    )


# ============================================================
# ➕ ADD CHANNEL (ማንኛውንም Add Channel ጽሑፍ ይቀበላል)
# ============================================================
@dp.message(F.text.contains("Add Channel"))
async def register_channel_start(message: types.Message, state: FSMContext):
    await state.set_state(BotStates.waiting_for_channel)
    await message.answer(
        "📌 **ቻናልዎን ለመመዝገብ፦**\n\n"
        "1. መጀመሪያ ይህን ቦት ወደ ቻናልዎ አስገብተው **Admin** ያድርጉት።\n"
        "2. ከዚያ የቻናልዎን Username (ለምሳሌ፦ `@my_channel`) እዚህ ይላኩ።",
        parse_mode="Markdown",
    )


@dp.message(BotStates.waiting_for_channel)
async def process_channel_username(message: types.Message, state: FSMContext):
    channel_username = (message.text or "").strip()

    if not channel_username:
        await message.answer("❌ Channel username ያስገቡ።")
        return

    if not channel_username.startswith("@"):
        channel_username = f"@{channel_username}"

    try:
        chat = await bot.get_chat(channel_username)
        me = await bot.get_me()
        member = await bot.get_chat_member(chat.id, me.id)

        if member.status not in ["administrator", "creator"]:
            await message.answer("❌ እባክዎ መጀመሪያ ቦቱን በቻናሉ ላይ Admin ያድርጉት!")
            return

        success = await add_channel(message.from_user.id, channel_username, chat.title)

        if success:
            await message.answer(
                f"✅ **{chat.title}** ({channel_username}) በተሳካ ሁኔታ ተመዝግቧል!",
                reply_markup=main_menu,
                parse_mode="Markdown",
            )
        else:
            await message.answer("⚠️ ይህ ቻናል አስቀድሞ ተመዝግቧል።")

        await state.clear()

    except Exception as e:
        print("Channel registration error:", e)
        await message.answer("❌ ቻናሉን ማግኘት አልተቻለም። Username ትክክል መሆኑንና ቦቱ Admin መደረጉን ያረጋግጡ።")


# ============================================================
# 🤖 AI CHAT
# ============================================================
@dp.message(F.text.contains("AI Chat"))
async def ai_chat_start(message: types.Message, state: FSMContext):
    await state.set_state(BotStates.waiting_for_ai_prompt)

    cancel_btn = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🔙 Back to Menu")]],
        resize_keyboard=True,
    )

    await message.answer(
        "🤖 **Digital Pro Ads AI Assistant**\n\n"
        "ጥያቄዎን በአማርኛ ወይም English ይጻፉ።\n\n"
        "ለመውጣት **🔙 Back to Menu** ይጫኑ።",
        reply_markup=cancel_btn,
        parse_mode="Markdown",
    )


@dp.message(BotStates.waiting_for_ai_prompt, F.text == "🔙 Back to Menu")
async def ai_chat_exit(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("ወደ ዋናው ሜኑ ተመልሰዋል።", reply_markup=main_menu)


def split_telegram_text(text: str, max_length: int = 4000):
    if not text:
        return []
    return [text[i:i + max_length] for i in range(0, len(text), max_length)]


@dp.message(BotStates.waiting_for_ai_prompt)
async def ai_chat_response(message: types.Message, state: FSMContext):
    if not GEMINI_API_KEY or not ai_client:
        await message.answer(
            "⚠️ Gemini API Key አልተገኘም።\n\nRender → Environment Variables ላይ `GEMINI_API_KEY` ያስገቡ።"
        )
        return

    prompt = (message.text or "").strip()
    if not prompt:
        await message.answer("⚠️ እባክዎ ጥያቄ ያስገቡ።")
        return

    try:
        await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    except Exception:
        pass

    full_prompt = (
        "System: You are Digital Pro Ads AI Assistant. "
        "Answer naturally, accurately and helpfully in Amharic or English depending on user input.\n\n"
        f"User: {prompt}"
    )

    models_to_try = [GEMINI_MODEL, GEMINI_FALLBACK_MODEL]
    answer = None

    for model_name in models_to_try:
        try:
            response = await asyncio.to_thread(
                ai_client.models.generate_content,
                model=model_name,
                contents=full_prompt,
            )
            if response and response.text:
                answer = response.text.strip()
                break
        except Exception as e:
            print(f"Gemini Error ({model_name}): {e}")
            await asyncio.sleep(1)

    if not answer:
        await message.answer("⚠️ AI ምላሽ ማግኘት አልተቻለም። እባክዎ ጥቂት ቆይተው ይሞክሩ።")
        return

    for part in split_telegram_text(answer):
        await message.answer(part)


# ============================================================
# 📢 ADVERTISE
# ============================================================
@dp.message(F.text.contains("Advertise"))
async def choose_channel_to_advertise(message: types.Message):
    channels = await get_all_channels()

    if not channels:
        await message.answer("⚠️ የተመዘገበ ቻናል የለም። በ **➕ Add Channel** የራስዎን ቻናል ይመዝግቡ።")
        return

    keyboard = [
        [InlineKeyboardButton(text=f"📢 {title} ({username})", callback_data=f"adto:{username}")]
        for username, title in channels
    ]

    markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
    await message.answer("🎯 ማስታወቂያዎ እንዲለጠፍበት የሚፈልጉትን ቻናል ይምረጡ፦", reply_markup=markup)


@dp.callback_query(F.data.startswith("adto:"))
async def target_channel_selected(callback: types.CallbackQuery, state: FSMContext):
    target_channel = callback.data.split(":", 1)[1]
    await state.update_data(target_channel=target_channel)
    await state.set_state(BotStates.waiting_for_ad_text)

    await callback.message.answer(
        f"📝 ወደ **{target_channel}** የሚለጠፈውን የማስታወቂያ ጽሑፍ ይላኩ።\n\n"
        f"💰 የአንድ ማስታወቂያ ዋጋ **{AD_PRICE:.2f} USDT** ነው።",
        parse_mode="Markdown",
    )
    await callback.answer()


@dp.message(BotStates.waiting_for_ad_text)
async def process_ad_submission(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    ad_content = (message.text or "").strip()

    if not ad_content:
        await message.answer("❌ የማስታወቂያ ጽሑፍ ያስገቡ።")
        return

    data = await state.get_data()
    target_channel = data.get("target_channel")

    balance = await get_user_balance(user_id)
    if balance < AD_PRICE:
        await state.clear()
        deposit_btn = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="💳 Deposit", callback_data="go_to_deposit")]]
        )
        await message.answer(
            f"❌ **ቀሪ ሂሳብዎ በቂ አይደለም!**\n\n"
            f"ዋጋ፦ **{AD_PRICE:.2f} USDT**\n"
            f"ቀሪ ሂሳብ፦ **{balance:.2f} USDT**",
            reply_markup=deposit_btn,
            parse_mode="Markdown",
        )
        return

    deducted = await deduct_user_balance(user_id, AD_PRICE)
    if not deducted:
        await state.clear()
        await message.answer("⚠️ ክፍያውን መፈጸም አልተቻለም።")
        return

    await save_ad(user_id, target_channel, ad_content)
    await state.clear()

    new_balance = await get_user_balance(user_id)
    await message.answer(
        f"✅ **ማስታወቂያዎ ተመዝግቧል!**\n\n"
        f"💰 የተቆረጠ፦ **{AD_PRICE:.2f} USDT**\n"
        f"💳 አዲሱ ቀሪ ሂሳብ፦ **{new_balance:.2f} USDT**\n\n"
        f"🎯 ቻናል፦ **{target_channel}**",
        reply_markup=main_menu,
        parse_mode="Markdown",
    )


# ============================================================
# 💳 DEPOSIT & VERIFY
# ============================================================
@dp.message(F.text.contains("Deposit"))
async def deposit_handler(message: types.Message):
    if crypto is None:
        await message.answer("⚠️ Crypto Deposit አሁን አይገኝም። `CRYPTO_TOKEN` መኖሩን ያረጋግጡ።")
        return

    try:
        invoice = await crypto.create_invoice(asset="USDT", amount=1.0)
        pay_keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="💳 Pay 1.00 USDT", url=invoice.bot_invoice_url)],
                [InlineKeyboardButton(text="🔄 Verify Payment", callback_data=f"verify_pay:{invoice.invoice_id}:1.0")],
            ]
        )
        await message.answer(
            "💳 **Crypto Deposit (USDT)**\n\n"
            "ወደ ሂሳብዎ **1.00 USDT** ለመጨመር **Pay 1.00 USDT** ይጫኑ።\n\n"
            "ክፍያውን ከፈጸሙ በኋላ **Verify Payment** ይጫኑ።",
            reply_markup=pay_keyboard,
            parse_mode="Markdown",
        )
    except Exception as e:
        print("Crypto invoice error:", e)
        await message.answer("⚠️ Deposit invoice መፍጠር አልተቻለም።")


@dp.callback_query(F.data.startswith("verify_pay:"))
async def check_payment_status(callback: types.CallbackQuery):
    if crypto is None:
        await callback.answer("Crypto service አይገኝም።", show_alert=True)
        return

    try:
        _, invoice_id, amount = callback.data.split(":")
        inv_id = int(invoice_id)
        amt = float(amount)

        if inv_id in processed_invoices:
            await callback.answer("ይህ ክፍያ አስቀድሞ ተቆጥሯል።", show_alert=True)
            return

        invoices = await crypto.get_invoices(invoice_ids=[inv_id])
        if invoices and invoices[0].status == "paid":
            await update_user_balance(callback.from_user.id, amt)
            processed_invoices.add(inv_id)
            await callback.message.answer(
                f"✅ **ክፍያዎ ተረጋግጧል!**\n\n💵 **{amt:.2f} USDT** ወደ ሂሳብዎ ተጨምሯል።",
                parse_mode="Markdown",
            )
            await callback.answer()
        else:
            await callback.answer("❌ ክፍያው ገና አልተጠናቀቀም።", show_alert=True)
    except Exception as e:
        print("Verification error:", e)
        await callback.answer("⚠️ Verification failed.", show_alert=True)


@dp.callback_query(F.data == "go_to_deposit")
async def forward_to_deposit(callback: types.CallbackQuery):
    await callback.answer()
    await deposit_handler(callback.message)


# ============================================================
# 🏧 WITHDRAW
# ============================================================
@dp.message(F.text.contains("Withdraw"))
async def withdraw_start(message: types.Message, state: FSMContext):
    balance = await get_user_balance(message.from_user.id)

    if balance < MIN_WITHDRAW:
        await message.answer(
            f"⚠️ **ዝቅተኛው ማውጣት የሚቻለው {MIN_WITHDRAW:.2f} USDT ነው።**\n\n"
            f"የእርስዎ ቀሪ ሂሳብ፦ **{balance:.2f} USDT**",
            parse_mode="Markdown",
        )
        return

    await state.set_state(BotStates.waiting_for_withdraw_amount)
    await message.answer(
        f"🏧 **ገንዘብ ማውጫ**\n\nቀሪ ሂሳብዎ፦ **{balance:.2f} USDT**\n\n"
        f"ማውጣት የሚፈልጉትን መጠን ያስገቡ (ዝቅተኛው {MIN_WITHDRAW:.2f} USDT)፦",
        parse_mode="Markdown",
    )


@dp.message(BotStates.waiting_for_withdraw_amount)
async def process_withdraw_amount(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text.strip())
    except (ValueError, AttributeError):
        await message.answer("❌ እባክዎ ትክክለኛ የቁጥር መጠን ያስገቡ።")
        return

    balance = await get_user_balance(message.from_user.id)
    if amount < MIN_WITHDRAW:
        await message.answer(f"❌ ዝቅተኛው **{MIN_WITHDRAW:.2f} USDT** ነው።", parse_mode="Markdown")
        return

    if amount > balance:
        await message.answer(f"❌ በቂ ቀሪ ሂሳብ የለዎትም። ያለዎት፦ **{balance:.2f} USDT**", parse_mode="Markdown")
        return

    await state.update_data(withdraw_amount=amount)
    await state.set_state(BotStates.waiting_for_withdraw_wallet)
    await message.answer("📝 ገንዘቡ የሚላክበትን **USDT Wallet Address** ወይም **@CryptoBot Username** ያስገቡ፦")


@dp.message(BotStates.waiting_for_withdraw_wallet)
async def process_withdraw_wallet(message: types.Message, state: FSMContext):
    wallet = (message.text or "").strip()
    data = await state.get_data()
    amount = data.get("withdraw_amount")
    user_id = message.from_user.id

    if not amount or not wallet:
        await state.clear()
        await message.answer("⚠️ Session አልተገኘም።")
        return

    deducted = await deduct_user_balance(user_id, amount)
    if not deducted:
        await state.clear()
        await message.answer("⚠️ ክፍያውን መፈጸም አልተቻለም።")
        return

    await create_withdrawal(user_id, amount, wallet)
    await state.clear()

    await message.answer(
        f"✅ **የማውጣት ጥያቄዎ ተልኳል!**\n\n💵 መጠን፦ **{amount:.2f} USDT**\n📍 አድራሻ፦ `{wallet}`",
        reply_markup=main_menu,
        parse_mode="Markdown",
    )

    try:
        await bot.send_message(
            chat_id=ADMIN_ID,
            text=f"🚨 **አዲስ የማውጣት ጥያቄ**\n\n👤 ተጠቃሚ፦ {message.from_user.first_name} (`{user_id}`)\n💵 መጠን፦ **{amount:.2f} USDT**\n📍 አድራሻ፦ `{wallet}`",
            parse_mode="Markdown",
        )
    except Exception as e:
        print("Alert error:", e)


# ============================================================
# 📊 MY ADS, 💰 BALANCE, 👥 REFERRAL
# ============================================================
@dp.message(F.text.contains("My Ads"))
async def my_ads_handler(message: types.Message):
    ads = await get_active_ads()
    if not ads:
        await message.answer("📊 በአሁኑ ወቅት ንቁ የሆነ ማስታወቂያ የለዎትም።")
        return

    text_msg = "📊 **ንቁ ማስታወቂያዎች፦**\n\n"
    for i, (channel, text) in enumerate(ads[:5], start=1):
        clean_preview = text[:50] + ("..." if len(text) > 50 else "")
        text_msg += f"{i}. 🎯 **ቻናል፦** {channel}\n📝 **ጽሑፍ፦** {clean_preview}\n\n"
    await message.answer(text_msg, parse_mode="Markdown")


@dp.message(F.text.contains("Balance"))
async def balance_handler(message: types.Message):
    balance = await get_user_balance(message.from_user.id)
    await message.answer(f"💰 ቀሪ ሂሳብዎ፦ **{balance:.2f} USDT**", parse_mode="Markdown")


@dp.message(F.text.contains("Referral"))
async def referral_handler(message: types.Message):
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={message.from_user.id}"
    await message.answer(f"👥 **የመጋበዣ ሊንክዎ፦**\n\n`{ref_link}`", parse_mode="Markdown")


# Web App Data Handler
@dp.message(F.web_app_data)
async def web_app_data_handler(message: types.Message, state: FSMContext):
    action = message.web_app_data.data
    if "Advertise" in action:
        await choose_channel_to_advertise(message)
    elif "Add Channel" in action:
        await register_channel_start(message, state)
    elif "Deposit" in action:
        await deposit_handler(message)
    elif "Withdraw" in action:
        await withdraw_start(message, state)
    elif "My Ads" in action:
        await my_ads_handler(message)
    elif "Balance" in action:
        await balance_handler(message)
    elif "AI Chat" in action:
        await ai_chat_start(message, state)


# ============================================================
# AUTO AD POSTER
# ============================================================
async def post_ads_to_channels():
    print("Running automatic ad poster...")
    try:
        ads = await get_active_ads()
    except Exception as e:
        print("Ad poster fetch error:", e)
        return

    for target_channel, text in ads:
        try:
            await bot.send_message(chat_id=target_channel, text=f"📢 Sponsored Ad\n\n{text}")
            await asyncio.sleep(5)
        except Exception as e:
            print(f"Error posting to {target_channel}: {e}")


# ============================================================
# ENTRY POINT
# ============================================================
async def run_bot():
    await init_db()

    scheduler = AsyncIOScheduler()
    scheduler.add_job(post_ads_to_channels, "interval", hours=8)
    scheduler.start()

    print("====================================")
    print("Digital Pro Ads Bot started!")
    print(f"Gemini model: {GEMINI_MODEL}")
    print("====================================")

    await dp.start_polling(bot)


async def main():
    print("Starting Digital Pro Ads...")
    await start_web_server()
    await run_bot()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped.")
    except Exception:
        traceback.print_exc()
        raise
