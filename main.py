import asyncio
import os
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, CommandObject
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiocryptopay import AioCryptoPay, Networks
from google import genai
from database import (
    init_db, add_user, get_user_balance, update_user_balance, deduct_user_balance,
    add_channel, get_all_channels, save_ad, get_active_ads, create_withdrawal
)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
CRYPTO_TOKEN = "639734:AAyANr5PBtEHPO5344cjssr6BQ5yGI6I7jA"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

ADMIN_ID = 6179388927
AD_PRICE = 1.00
MIN_WITHDRAW = 5.00

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
crypto = AioCryptoPay(token=CRYPTO_TOKEN, network=Networks.MAIN_NET)

ai_client = None
if GEMINI_API_KEY:
    ai_client = genai.Client(api_key=GEMINI_API_KEY)

class BotStates(StatesGroup):
    waiting_for_channel = State()
    waiting_for_ad_channel = State()
    waiting_for_ad_text = State()
    waiting_for_withdraw_amount = State()
    waiting_for_withdraw_wallet = State()
    waiting_for_ai_prompt = State()

async def handle_ping(request):
    return web.Response(text="Bot is running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"Web server started on port {port}")

main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📢 Advertise"), KeyboardButton(text="➕ Add Channel")],
        [KeyboardButton(text="💰 Balance"), KeyboardButton(text="👥 Referral")],
        [KeyboardButton(text="💳 Deposit"), KeyboardButton(text="🏧 Withdraw")],
        [KeyboardButton(text="📊 My Ads"), KeyboardButton(text="🤖 AI Chat")]
    ],
    resize_keyboard=True
)

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
        parse_mode="Markdown"
    )

# ----------------- 🤖 AI CHAT (Gemini 3.8 Flash) -----------------
@dp.message(F.text == "🤖 AI Chat")
async def ai_chat_start(message: types.Message, state: FSMContext):
    await state.set_state(BotStates.waiting_for_ai_prompt)
    cancel_btn = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🔙 Back to Menu")]],
        resize_keyboard=True
    )
    await message.answer(
        "🤖 **የ AI ረዳት ክፍል (Gemini 3.8 Flash)**\n\n"
        "የሚፈልጉትን ማንኛውንም ጥያቄ፣ ለማስታወቂያ የሚሆን የጽሑፍ ሃሳብ ወይም ማንኛውንም ርዕስ ይጠይቁኝ፦\n"
        "*(ለመውጣት '🔙 Back to Menu' የሚለውን ይጫኑ)*",
        reply_markup=cancel_btn,
        parse_mode="Markdown"
    )

@dp.message(BotStates.waiting_for_ai_prompt, F.text == "🔙 Back to Menu")
async def ai_chat_exit(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("ወደ ዋናው ሜኑ ተመልሰዋል፦", reply_markup=main_menu)

@dp.message(BotStates.waiting_for_ai_prompt)
async def ai_chat_response(message: types.Message):
    if not ai_client:
        await message.answer("⚠️ GEMINI_API_KEY አልተገኘም። እባክዎ Render ላይ Environment Variable መግባቱን ያረጋግጡ።")
        return

    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    
    # መጀመሪያ 3.8 Flash ይሞክራል፤ በጎግል በኩል 503 ጫና ካለ ወደ 2.5 Flash ይቀይራል
    models_to_try = ["gemini-3.8-flash", "gemini-2.5-flash"]
    for model_name in models_to_try:
        try:
            response = await asyncio.to_thread(
                ai_client.models.generate_content,
                model=model_name,
                contents=message.text
            )
            if response and response.text:
                await message.answer(response.text)
                return
        except Exception as e:
            print(f"Error on {model_name}: {e}")
            continue

    await message.answer("❌ በአሁኑ ሰዓት በ AI ሰርቨር ላይ ከፍተኛ ጫና ስላለ ምላሽ መስጠት አልተቻለም። እባክዎ ጥቂት ቆይተው እንደገና ይሞክሩ።")

# ----------------- 💳 DEPOSIT (CRYPTO PAY) -----------------
@dp.message(F.text == "💳 Deposit")
async def deposit_handler(message: types.Message):
    invoice = await crypto.create_invoice(asset='USDT', amount=1.0)
    pay_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Pay 1.00 USDT", url=invoice.bot_invoice_url)],
        [InlineKeyboardButton(text="🔄 Verify Payment", callback_data=f"verify_pay:{invoice.invoice_id}:1.0")]
    ])
    await message.answer(
        "💳 **Crypto Deposit (USDT)**\n\n"
        "ወደ ሂሳብዎ **1.00 USDT** ለመጨመር ከታች ያለውን **Pay 1.00 USDT** የሚለውን ቁልፍ ተጭነው ይክፈሉ።\n\n"
        "ክፍያውን እንደፈጸሙ **Verify Payment** የሚለውን በመጫን ያረጋግጡ።",
        reply_markup=pay_keyboard,
        parse_mode="Markdown"
    )

@dp.callback_query(F.data.startswith("verify_pay:"))
async def check_payment_status(callback: types.CallbackQuery):
    _, invoice_id, amount = callback.data.split(":")
    invoices = await crypto.get_invoices(invoice_ids=[int(invoice_id)])
    if invoices and invoices[0].status == 'paid':
        await update_user_balance(callback.from_user.id, float(amount))
        await callback.message.answer(f"✅ ክፍያዎ ተረጋግጧል! **${amount} USDT** ወደ ሂሳብዎ ተጨምሯል።")
        await callback.answer()
    else:
        await callback.answer("❌ ክፍያው ገና አልተጠናቀቀም። እባክዎ ከከፈሉ በኋላ ደግመው ይሞክሩ።", show_alert=True)

# ----------------- 🏧 WITHDRAW -----------------
@dp.message(F.text == "🏧 Withdraw")
async def withdraw_start(message: types.Message, state: FSMContext):
    balance = await get_user_balance(message.from_user.id)
    if balance < MIN_WITHDRAW:
        await message.answer(
            f"⚠️ **ዝቅተኛው ማውጣት የሚቻለው መጠን {MIN_WITHDRAW:.2f} USDT ነው።**\n\n"
            f"የእርስዎ ቀሪ ሂሳብ፦ **{balance:.2f} USDT**",
            parse_mode="Markdown"
        )
        return

    await state.set_state(BotStates.waiting_for_withdraw_amount)
    await message.answer(
        f"🏧 **ገንዘብ ማውጫ**\n\n"
        f"ቀሪ ሂሳብዎ፦ **{balance:.2f} USDT**\n"
        f"ማውጣት የሚፈልጉትን የገንዘብ መጠን ያስገቡ (ዝቅተኛው {MIN_WITHDRAW:.2f})፦"
    )

@dp.message(BotStates.waiting_for_withdraw_amount)
async def process_withdraw_amount(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text.strip())
    except ValueError:
        await message.answer("❌ እባክዎ ትክክለኛ የቁጥር መጠን ያስገቡ።")
        return

    balance = await get_user_balance(message.from_user.id)
    if amount < MIN_WITHDRAW:
        await message.answer(f"❌ ማውጣት የሚቻለው ዝቅተኛው መጠን **{MIN_WITHDRAW:.2f} USDT** ነው።")
        return
    if amount > balance:
        await message.answer(f"❌ በቂ ቀሪ ሂሳብ የለዎትም። ያለዎት፦ **{balance:.2f} USDT**")
        return

    await state.update_data(withdraw_amount=amount)
    await state.set_state(BotStates.waiting_for_withdraw_wallet)
    await message.answer("📝 ገንዘቡ እንዲላክበት የሚፈልጉትን **USDT Wallet Address** ወይም **@CryptoBot Username** ያስገቡ፦")

@dp.message(BotStates.waiting_for_withdraw_wallet)
async def process_withdraw_wallet(message: types.Message, state: FSMContext):
    wallet = message.text.strip()
    data = await state.get_data()
    amount = data.get("withdraw_amount")
    user_id = message.from_user.id

    deducted = await deduct_user_balance(user_id, amount)
    if not deducted:
        await state.clear()
        await message.answer("⚠️ ክፍያውን መፈጸም አልተቻለም። እባክዎ ደግመው ይሞክሩ።")
        return

    await create_withdrawal(user_id, amount, wallet)
    await state.clear()

    await message.answer(
        f"✅ **የማውጣት ጥያቄዎ በተሳካ ሁኔታ ተልኳል!**\n\n"
        f"💵 መጠን፦ **{amount:.2f} USDT**\n"
        f"📍 አድራሻ፦ `{wallet}`\n\n"
        "አስተዳዳሪው ክፍያውን አረጋግጦ በጥቂት ደቂቃዎች ውስጥ ይልክልዎታል።",
        reply_markup=main_menu,
        parse_mode="Markdown"
    )

    try:
        await bot.send_message(
            chat_id=ADMIN_ID,
            text=f"🚨 **አዲስ የማውጣት ጥያቄ (Withdrawal Request)**\n\n"
                 f"👤 ተጠቃሚ፦ {message.from_user.first_name} (`{user_id}`)\n"
                 f"💵 መጠን፦ **{amount:.2f} USDT**\n"
                 f"📍 አድራሻ፦ `{wallet}`\n\n"
                 "እባክዎ ክፍያውን በ CryptoBot ወይም በ Wallet ይላኩላቸው።",
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Error alerting admin: {e}")

# ----------------- ➕ ADD CHANNEL -----------------
@dp.message(F.text == "➕ Add Channel")
async def register_channel_start(message: types.Message, state: FSMContext):
    await state.set_state(BotStates.waiting_for_channel)
    await message.answer(
        "📌 **ቻናልዎን ለመመዝገብ፦**\n\n"
        "1. መጀመሪያ ይህን ቦት ወደ ቻናልዎ አስገብተው **Admin** ያድርጉት።\n"
        "2. ከዚያ የቻናልዎን Username (ለምሳሌ፦ `@my_channel`) እዚህ ይላኩ።",
        parse_mode="Markdown"
    )

@dp.message(BotStates.waiting_for_channel)
async def process_channel_username(message: types.Message, state: FSMContext):
    channel_username = message.text.strip()
    if not channel_username.startswith("@"):
        channel_username = f"@{channel_username}"

    try:
        chat = await bot.get_chat(channel_username)
        member = await bot.get_chat_member(chat.id, (await bot.get_me()).id)
        if member.status not in ["administrator", "creator"]:
            await message.answer("❌ እባክዎ መጀመሪያ ቦቱን በቻናሉ ላይ Admin ያድርጉት!")
            return

        success = await add_channel(message.from_user.id, channel_username, chat.title)
        if success:
            await message.answer(f"✅ **{chat.title}** ({channel_username}) በተሳካ ሁኔታ ተመዝግቧል!", reply_markup=main_menu, parse_mode="Markdown")
            await state.clear()
        else:
            await message.answer("⚠️ ይህ ቻናል አስቀድሞ ተመዝግቧል።")
            await state.clear()

    except Exception:
        await message.answer("❌ ቻናሉን ማግኘት አልተቻለም። ስሙ ትክክል መሆኑንና ቦቱ Admin መደረጉን ያረጋግጡ።")

# ----------------- 📢 ADVERTISE -----------------
@dp.message(F.text == "📢 Advertise")
async def choose_channel_to_advertise(message: types.Message):
    channels = await get_all_channels()
    if not channels:
        await message.answer("⚠️ በአሁኑ ሰዓት የተመዘገበ ቻናል የለም። እባክዎ ቆየት ብለው ይሞክሩ ወይም በ '➕ Add Channel' በኩል የራስዎን ቻናል ይመዝግቡ።")
        return

    keyboard = []
    for username, title in channels:
        keyboard.append([InlineKeyboardButton(text=f"📢 {title} ({username})", callback_data=f"adto:{username}")])

    markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
    await message.answer("🎯 ማስታወቂያዎ እንዲለጠፍበት የሚፈልጉትን ቻናል ይምረጡ፦", reply_markup=markup)

@dp.callback_query(F.data.startswith("adto:"))
async def target_channel_selected(callback: types.CallbackQuery, state: FSMContext):
    target_channel = callback.data.split(":")[1]
    await state.update_data(target_channel=target_channel)
    await state.set_state(BotStates.waiting_for_ad_text)
    await callback.message.answer(
        f"📝 ወደ **{target_channel}** የሚለጠፈውን የማስታወቂያ ጽሑፍ እዚህ ይላኩ፦\n\n"
        f"*(ማስታወሻ፦ የአንድ ማስታወቂያ ዋጋ **{AD_PRICE:.2f} USDT** ሲሆን፣ ከሂሳብዎ ላይ በቀጥታ የሚቆረጥ ይሆናል።)*",
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.message(BotStates.waiting_for_ad_text)
async def process_ad_submission(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    balance = await get_user_balance(user_id)

    if balance < AD_PRICE:
        await state.clear()
        deposit_button = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Deposit", callback_data="go_to_deposit")]
        ])
        await message.answer(
            f"❌ **ቀሪ ሂሳብዎ በቂ አይደለም!**\n\n"
            f"የአንድ ማስታወቂያ ዋጋ፦ **{AD_PRICE:.2f} USDT**\n"
            f"የእርስዎ ቀሪ ሂሳብ፦ **{balance:.2f} USDT**\n\n"
            "እባክዎ መጀመሪያ ሂሳብዎን ይሙሉ፦",
            reply_markup=deposit_button,
            parse_mode="Markdown"
        )
        return

    deducted = await deduct_user_balance(user_id, AD_PRICE)
    if not deducted:
        await state.clear()
        await message.answer("⚠️ ክፍያውን መፈጸም አልተቻለም። እባክዎ ደግመው ይሞክሩ።")
        return

    data = await state.get_data()
    target_channel = data.get("target_channel")
    ad_content = message.text

    await save_ad(user_id, target_channel, ad_content)
    await state.clear()
    
    new_balance = await get_user_balance(user_id)
    await message.answer(
        f"✅ **ማስታወቂያዎ በተሳካ ሁኔታ ተመዝግቧል!**\n\n"
        f"💰 የተቆረጠ ሂሳብ፦ **{AD_PRICE:.2f} USDT**\n"
        f"💳 አዲሱ ቀሪ ሂሳብዎ፦ **{new_balance:.2f} USDT**\n\n"
        f"በቀን 3 ጊዜ ወደ **{target_channel}** በራስ-ሰር ይለጠፋል።",
        reply_markup=main_menu,
        parse_mode="Markdown"
    )

@dp.callback_query(F.data == "go_to_deposit")
async def forward_to_deposit(callback: types.CallbackQuery):
    await callback.answer()
    await deposit_handler(callback.message)

# ----------------- ራስ-ሰር ፖስተር -----------------
async def post_ads_to_channels():
    ads = await get_active_ads()
    for target_channel, text in ads:
        try:
            await bot.send_message(chat_id=target_channel, text=f"📢 **Sponsored Ad**\n\n{text}")
            await asyncio.sleep(5)
        except Exception as e:
            print(f"Error posting to {target_channel}: {e}")

# ----------------- ሌሎች አዝራሮች -----------------
@dp.message(F.text == "💰 Balance")
async def balance_handler(message: types.Message):
    balance = await get_user_balance(message.from_user.id)
    await message.answer(f"💰 ቀሪ ሂሳብዎ፦ **{balance:.2f} USDT**", parse_mode="Markdown")

@dp.message(F.text == "👥 Referral")
async def referral_handler(message: types.Message):
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={message.from_user.id}"
    await message.answer(f"👥 **የመጋበዣ ሊንክዎ**፦\n`{ref_link}`", parse_mode="Markdown")

async def run_bot():
    await init_db()
    scheduler = AsyncIOScheduler()
    scheduler.add_job(post_ads_to_channels, 'interval', hours=8)
    scheduler.start()
    print("ቦቱ ስራ ጀምሯል...")
    await dp.start_polling(bot)

async def main():
    await asyncio.gather(
        start_web_server(),
        run_bot()
    )

if __name__ == "__main__":
    asyncio.run(main())
