import asyncio
import os
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, CommandObject
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from database import init_db, add_user, get_user_balance, add_channel, get_all_channels, save_ad, get_active_ads

BOT_TOKEN = os.environ.get("BOT_TOKEN")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ደረጃዎችን መቆጣጠሪያ (FSM States)
class BotStates(StatesGroup):
    waiting_for_channel = State()
    waiting_for_ad_channel = State()
    waiting_for_ad_text = State()

# Render እንዳይዘጋ የሚያስችል
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

# ዋናው ሜኑ (➕ Add Channel ተጨምሮበታል)
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

# ----------------- 1. የቻናል ምዝገባ (ADD CHANNEL) -----------------
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
        # ቦቱ በቻናሉ ላይ Admin መሆኑን ማረጋገጥ
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

# ----------------- 2. ማስታወቂያ ማስያዝ (ADVERTISE) -----------------
@dp.message(F.text == "📢 Advertise")
async def choose_channel_to_advertise(message: types.Message):
    channels = await get_all_channels()
    if not channels:
        await message.answer("⚠️ በአሁኑ ሰዓት የተመዘገበ ቻናል የለም። እባክዎ ቆየት ብለው ይሞክሩ ወይም በ '➕ Add Channel' በኩል የራስዎን ቻናል ይመዝግቡ።")
        return

    # የተመዘገቡ ቻናሎችን በአዝራር ማሳየት
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
    await callback.message.answer(f"📝 ወደ **{target_channel}** የሚለጠፈውን የማስታወቂያ ጽሑፍ እዚህ ይላኩ፦", parse_mode="Markdown")
    await callback.answer()

@dp.message(BotStates.waiting_for_ad_text)
async def process_ad_submission(message: types.Message, state: FSMContext):
    data = await state.get_data()
    target_channel = data.get("target_channel")
    ad_content = message.text

    await save_ad(message.from_user.id, target_channel, ad_content)
    await state.clear()
    await message.answer(
        f"✅ ማስታወቂያዎ ተመዝግቧል!\nበቀን 3 ጊዜ ወደ **{target_channel}** በራስ-ሰር ይለጠፋል።",
        reply_markup=main_menu,
        parse_mode="Markdown"
    )

# ----------------- 3. ራስ-ሰር ፖስተር (በየ 8 ሰዓቱ) -----------------
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
    await message.answer(f"💰 ቀሪ ሂሳብዎ፦ **{balance:.2f} ETB**", parse_mode="Markdown")

@dp.message(F.text == "👥 Referral")
async def referral_handler(message: types.Message):
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={message.from_user.id}"
    await message.answer(f"👥 **የመጋበዣ ሊንክዎ**፦\n`{ref_link}`", parse_mode="Markdown")

async def main():
    await init_db()
    await start_web_server()

    # በየ 8 ሰዓቱ (በቀን 3 ጊዜ) ማስታወቂያዎችን እንዲለጥፍ
    scheduler = AsyncIOScheduler()
    scheduler.add_job(post_ads_to_channels, 'interval', hours=8)
    scheduler.start()

    print("ቦቱ ስራ ጀምሯል...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
