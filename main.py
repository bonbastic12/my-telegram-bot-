import asyncio
import os
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, CommandObject
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from database import init_db, add_user, get_user_balance

BOT_TOKEN = os.environ.get("BOT_TOKEN")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Render Web Service ነፃውን ፕላን እንዲቀበለው የሚያስችል ሰርቨር
async def handle_ping(request):
    return web.Response(text="Bot is online and running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

# ዋናው የቴሌግራም አዝራሮች ገጽታ
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

    welcome_text = (
        f"ሰላም {message.from_user.first_name}! ወደ **Digital Pro Ads & AI Bot** በደህና መጡ።\n\n"
        "ከታች ያሉትን አዝራሮች በመጠቀም አገልግሎቶችን ማግኘት ይችላሉ።"
    )
    await message.answer(welcome_text, reply_markup=main_menu, parse_mode="Markdown")

@dp.message(F.text == "💰 Balance")
async def balance_handler(message: types.Message):
    balance = await get_user_balance(message.from_user.id)
    await message.answer(f"💰 የአሁን ቀሪ ሂሳብዎ (Balance)፦ **{balance:.2f} ETB**", parse_mode="Markdown")

@dp.message(F.text == "👥 Referral")
async def referral_handler(message: types.Message):
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={message.from_user.id}"
    text = (
        "👥 **የሪፈራል ፕሮግራም**\n\n"
        "የእርስዎን ሊንክ ለጓደኞችዎ ያጋሩ፤ በአንድ ሰው **0.50 ETB** ያግኙ!\n\n"
        f"የመጋበዣ ሊንክዎ፦\n`{ref_link}`"
    )
    await message.answer(text, parse_mode="Markdown")

@dp.message(F.text == "📢 Advertise")
async def advertise_handler(message: types.Message):
    await message.answer("📢 ማስታወቂያ ለመለጠፍ በቅርብ ቀን ይጠብቁን።")

@dp.message(F.text == "💳 Deposit")
async def deposit_handler(message: types.Message):
    await message.answer("💳 ሂሳብ ለመሙላት በቅርብ ቀን ይጠብቁን።")

@dp.message(F.text == "🏧 Withdraw")
async def withdraw_handler(message: types.Message):
    await message.answer("🏧 ገንዘብ ለማውጣት ዝቅተኛው መጠን 20 ETB ነው።")

@dp.message(F.text == "📊 My Ads")
async def my_ads_handler(message: types.Message):
    await message.answer("📊 እስካሁን ያስተዋወቁት ማስታወቂያ የለም።")

@dp.message(F.text == "🤖 AI Chat")
async def ai_chat_handler(message: types.Message):
    await message.answer("🤖 የ AI ረዳት አገልግሎት በቅርብ ቀን ዝግጁ ይሆናል።")

async def main():
    await init_db()
    await start_web_server()
    print("ቦቱ በተሳካ ሁኔታ ስራ ጀምሯል...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
