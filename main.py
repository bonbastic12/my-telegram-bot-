import asyncio
import os
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, CommandObject
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from database import init_db, add_user, get_user_balance, save_ad, get_all_active_ads

BOT_TOKEN = os.environ.get("BOT_TOKEN")
# ማስታወቂያው የሚለጠፍበት የቻናልህ ስም (ለምሳሌ: "@your_channel_name")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "@your_channel_name")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# የማስታወቂያ አቀባበል ደረጃዎች
class AdState(StatesGroup):
    waiting_for_text = State()

# Render Web Service እንዳይዘጋ የሚያስችል ሰርቨር
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

# አዝራሮች
main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📢 Advertise"), KeyboardButton(text="👥 Referral")],
        [KeyboardButton(text="💰 Balance"), KeyboardButton(text="💳 Deposit")],
        [KeyboardButton(text="🏧 Withdraw"), KeyboardButton(text="📊 My Ads")],
        [KeyboardButton(text="🤖 AI Chat")]
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
        f"ሰላም {message.from_user.first_name}! ወደ **Digital Pro Ads & AI Bot** በደህና መጡ።",
        reply_markup=main_menu,
        parse_mode="Markdown"
    )

@dp.message(F.text == "💰 Balance")
async def balance_handler(message: types.Message):
    balance = await get_user_balance(message.from_user.id)
    await message.answer(f"💰 የአሁን ቀሪ ሂሳብዎ፦ **{balance:.2f} ETB**", parse_mode="Markdown")

@dp.message(F.text == "👥 Referral")
async def referral_handler(message: types.Message):
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={message.from_user.id}"
    await message.answer(f"👥 **የመጋበዣ ሊንክዎ**፦\n`{ref_link}`", parse_mode="Markdown")

# 1. ማስታወቂያ ለመለጠፍ ጥያቄ ሲላክ
@dp.message(F.text == "📢 Advertise")
async def start_ad_submission(message: types.Message, state: FSMContext):
    await state.set_state(AdState.waiting_for_text)
    await message.answer("📝 እባክዎ ሊያስተዋውቁት የሚፈልጉትን ማስታወቂያ ጽሑፍ እዚህ ይላኩ፦")

# 2. ማስታወቂያውን ተቀብሎ ሴቭ ማድረግ
@dp.message(AdState.waiting_for_text)
async def process_ad_text(message: types.Message, state: FSMContext):
    ad_content = message.text
    await save_ad(message.from_user.id, ad_content)
    await state.clear()
    await message.answer(
        "✅ ማስታወቂያዎ በተሳካ ሁኔታ ተመዝግቧል!\nበቀን 3 ጊዜ በራስ-ሰር ወደ ቻናሉ ይለጠፋል።",
        reply_markup=main_menu
    )

# 3. በቀን 3 ጊዜ (በየ 8 ሰዓቱ) ማስታወቂያዎችን ወደ ቻናል የመለጠፊያ ተግባር
async def post_ads_to_channel():
    ads = await get_all_active_ads()
    for ad in ads:
        try:
            await bot.send_message(chat_id=CHANNEL_ID, text=f"📢 **ስፖንሰር የተደረገ ማስታወቂያ**\n\n{ad[0]}")
            await asyncio.sleep(5)  # በቴሌግራም ህግ መሰረት እንዳይታገድ ትንሽ ማረፊያ
        except Exception as e:
            print(f"Error posting ad: {e}")

async def main():
    await init_db()
    await start_web_server()

    # በቀን 3 ጊዜ (በየ 8 ሰዓቱ) እንዲለጥፍ ማስተካከል
    scheduler = AsyncIOScheduler()
    scheduler.add_job(post_ads_to_channel, 'interval', hours=8)
    scheduler.start()

    print("ቦቱ እና የማስታወቂያ መርሃ-ግብሩ ስራ ጀምረዋል...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
