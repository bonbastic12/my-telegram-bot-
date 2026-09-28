# ============================================================
# 🤖 AI RESPONSE (የተስተካከለ)
# ============================================================

@dp.message(BotStates.waiting_for_ai_prompt)
async def ai_chat_response(
    message: types.Message,
    state: FSMContext
):
    if not GEMINI_API_KEY or not ai_client:
        await message.answer(
            "⚠️ **Gemini AI አልተዘጋጀም።**\n\n"
            "Render → Environment Variables ላይ\n"
            "`GEMINI_API_KEY` መኖሩን ያረጋግጡ።",
            parse_mode="Markdown",
        )
        return

    prompt = (message.text or "").strip()
    if not prompt:
        await message.answer("⚠️ እባክዎ ጥያቄ ያስገቡ።")
        return

    try:
        await bot.send_chat_action(
            chat_id=message.chat.id,
            action="typing"
        )
    except Exception:
        pass

    # የ System መመሪያውን ከጥያቄው ጋር በማጣመር በቀላሉ እና ያለ SDK config error እንዲሰራ ማድረግ
    full_prompt = (
        "System: You are Digital Pro Ads AI Assistant. "
        "Answer naturally, accurately and helpfully in Amharic or English depending on user input. "
        "Keep answers clear, useful and ready-to-use.\n\n"
        f"User: {prompt}"
    )

    models_to_try = [
        GEMINI_MODEL,
        GEMINI_FALLBACK_MODEL,
    ]

    answer = None

    for model_name in models_to_try:
        try:
            print(f"Trying Gemini model: {model_name}")

            # ቀጥተኛ ጥሪ (ያለ dictionary config ስህተት)
            response = await asyncio.to_thread(
                ai_client.models.generate_content,
                model=model_name,
                contents=full_prompt,
            )

            if response and response.text:
                answer = response.text.strip()
                print(f"Gemini success: {model_name}")
                break

            print(f"Gemini returned empty response: {model_name}")

        except Exception as e:
            print("================================")
            print(f"Gemini ERROR - {model_name}")
            print("Error type:", type(e).__name__)
            print("Error:", str(e))
            traceback.print_exc()
            print("================================")
            await asyncio.sleep(1)

    if not answer:
        await message.answer(
            "⚠️ **AI ምላሽ ማግኘት አልተቻለም።**\n\n"
            "Gemini API Key፣ API access ወይም quota ላይ ችግር ሊኖር ይችላል።\n\n"
            "Render Logs ውስጥ የGemini ERROR ይመልከቱ።",
            parse_mode="Markdown",
        )
        return

    for part in split_telegram_text(answer):
        try:
            await message.answer(part)
        except Exception as e:
            print("Telegram AI response send error:", e)
