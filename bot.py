import httpx
import os
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters

# ====== НАСТРОЙКИ ======
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
API_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "llama-3.1-8b-instant"
MANAGER_USERNAME = "@nektarinx"  # ← замінити на свій

# ====== ОСОБИСТІСТЬ БОТА ======
SYSTEM_PROMPT = """Ти — Аліна, AI-асистент компанії [Стоматологія «Посмішка»].

Твоя роль: допомагати пацієнтам з питаннями про послуги, ціни та запис на прийом.

Правила:
- Відповідай ТІЛЬКИ українською мовою
- Будь теплою, турботливою і професійною
- Використовуй емодзі щоб відповіді виглядали привітно
- Якщо питання про конкретний діагноз або лікування — рекомендуй звернутись до лікаря на консультації
- Якщо не знаєш відповіді — передай питання адміністратору
- Відповіді роби короткими, чіткими і зрозумілими
- Завжди пропонуй записатись на безкоштовну консультацію
"""

# ====== БАЗА ЗНАНЬ ======
FAQ = """
=== БАЗА ЗНАНЬ КЛІНІКИ «ПОСМІШКА» ===

📍 Адреса: м. Київ, вул. Хрещатик, 12
📞 Телефон: +38 (044) 123-45-67
🕐 Графік роботи: Пн-Пт 9:00-20:00, Сб 10:00-17:00, Нд — вихідний


👨‍⚕️ ЛІКАРІ:
- Др. Олександр Коваль — стоматолог-терапевт, 15 років досвіду
- Др. Марина Бондаренко — ортодонт, брекети та елайнери
- Др. Василь Іванченко — хірург-імплантолог


💊 ПОСЛУГИ ТА ЦІНИ:

Терапія:
- Консультація лікаря — БЕЗКОШТОВНО
- Лікування карієсу (1 зуб) — від 800 грн
- Пломба світлова — від 900 грн
- Лікування пульпіту — від 1500 грн

Гігієна:
- Професійна чистка зубів — 1200 грн
- Відбілювання зубів (система Beyond) — 3500 грн
- Фторування — 400 грн

Хірургія:
- Видалення зуба (просте) — від 600 грн
- Видалення зуба мудрості — від 1200 грн
- Імплантація (під ключ) — від 15000 грн

Ортодонтія:
- Консультація ортодонта — БЕЗКОШТОВНО
- Брекети металеві — від 18000 грн (щелепа)
- Брекети сапфірові — від 25000 грн (щелепа)
- Елайнери — від 30000 грн (курс)

Дитяча стоматологія:
- Консультація дитячого лікаря — БЕЗКОШТОВНО
- Лікування молочного зуба — від 600 грн
- Герметизація фісур — 500 грн за зуб

❓ ЧАСТІ ПИТАННЯ:

Q: Чи боляче лікувати зуби?
A: Ні! Ми використовуємо сучасну анестезію — пацієнт не відчуває болю. Також є заспокійлива терапія для тривожних пацієнтів.

Q: Як записатись на прийом?
A: Можна записатись через бота (натисни "📅 Записатись"), зателефонувати або написати адміністратору.

Q: Чи є знижки?
A: Так! Діє програма лояльності — 5% знижка з другого візиту. Для пенсіонерів та дітей — 10% знижка.

Q: Чи приймаєте дітей?
A: Так, з 3 років. У нас є окремий дитячий кабінет з мультиками та подарунками після прийому 🎁

Q: Які методи оплати?
A: Готівка, картка (Visa/Mastercard), Apple Pay, Google Pay. Є розстрочка на лікування від 3000 грн.

Q: Чи є парковка?
A: Так, безкоштовна парковка на 10 місць біля клініки.

Q: Як швидко можна записатись?
A: Найближчий вільний час зазвичай є вже наступного дня. При гострому болі — приймаємо в день звернення!
"""

# ====== КЛАВІАТУРА ======
MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["🦷 Наші послуги", "💰 Ціни"],
        ["📅 Записатись на прийом", "❓ FAQ"],
        ["📞 Контакти", "🏠 Головне меню"]
    ],
    resize_keyboard=True
)

user_memory = {}

# ====== ЗАПИТ ДО AI ======
async def ask_ai_with_memory(messages):
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    system_messages = [
        {"role": "system", "content": SYSTEM_PROMPT + "\n" + FAQ}
    ]
    payload = {
        "model": MODEL,
        "messages": system_messages + messages,
        "max_tokens": 512,
        "temperature": 0.7
    }
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(API_URL, headers=headers, json=payload, timeout=90.0)
            if not response.text:
                return "⚠️ Сервер не відповідає. Спробуй за 30 сек."
            try:
                data = response.json()
            except ValueError:
                return f"⚠️ Помилка відповіді: {response.text[:200]}"
            if response.status_code != 200:
                error = data.get('error', str(data))
                return f"⚠️ Помилка API {response.status_code}: {error}"
            return data["choices"][0]["message"]["content"].strip()
        except httpx.TimeoutException:
            return "⏱ Timeout — спробуй ще раз через хвилину."
        except KeyError:
            return f"⚠️ Несподіваний формат відповіді: {str(data)[:200]}"
        except Exception as e:
            return f"⚠️ Помилка з'єднання: {str(e)}"

# ====== КОМАНДА /start ======
async def start(update: Update, context):
    user_id = update.message.from_user.id
    user_memory[user_id] = []

    await update.message.reply_text(
        "👋 Вітаємо в стоматологічній клініці *«Посмішка»*!\n\n"
        "Я — Софія, ваш AI-асистент 🦷\n\n"
        "Допоможу вам з:\n"
        "• 🦷 Інформацією про послуги та ціни\n"
        "• 📅 Записом на прийом\n"
        "• ❓ Відповідями на ваші питання\n"
        "• 📞 Контактами клініки\n\n"
        "Перший візит та консультація — *БЕЗКОШТОВНО* 🎁\n\n"
        "Оберіть що вас цікавить 👇",
        reply_markup=MAIN_KEYBOARD,
        parse_mode="Markdown"
    )

# ====== ОБРОБКА КНОПОК І ПОВІДОМЛЕНЬ ======
async def handle_message(update: Update, context):
    user_id = update.message.from_user.id
    user_text = update.message.text

    if user_id not in user_memory:
        user_memory[user_id] = []

    # ── Кнопка: Головне меню ──
    if user_text == "🏠 Головне меню":
        user_memory[user_id] = []
        await update.message.reply_text(
            "🏠 *Головне меню*\n\nОберіть що вас цікавить 👇",
            reply_markup=MAIN_KEYBOARD,
            parse_mode="Markdown"
        )
        return

    # ── Кнопка: Контакти ──
    if user_text == "📞 Контакти":
        await update.message.reply_text(
            "📞 *Контакти клініки «Посмішка»*\n\n"
            "📍 Адреса: м. Київ, вул. Хрещатик, 12\n"
            "📞 Телефон: +38 (044) 123-45-67\n"
            f"💬 Адміністратор: {MANAGER_USERNAME}\n\n"
            "🕐 *Графік роботи:*\n"
            "Пн-Пт: 9:00 - 20:00\n"
            "Сб: 10:00 - 17:00\n"
            "Нд: вихідний\n\n"
            "🚗 Безкоштовна парковка біля клініки",
            reply_markup=MAIN_KEYBOARD,
            parse_mode="Markdown"
        )
        return

    # ── Кнопка: Записатись ──
    if user_text == "📅 Записатись на прийом":
        await update.message.reply_text(
            "📅 *Запис на прийом*\n\n"
            "Щоб записатись, напишіть:\n"
            "1️⃣ Ваше ім'я\n"
            "2️⃣ Номер телефону\n"
            "3️⃣ Яка послуга вас цікавить\n"
            "4️⃣ Зручний час для візиту\n\n"
            "Або зателефонуйте нам: *+38 (044) 123-45-67*\n\n"
            "⚡ При гострому болі — приймаємо в день звернення!",
            reply_markup=MAIN_KEYBOARD,
            parse_mode="Markdown"
        )
        return

    # ── Кнопка: FAQ ──
    if user_text == "❓ FAQ":
        await update.message.reply_text(
            "❓ *Часті питання:*\n\n"
            "• Чи боляче лікувати зуби?\n"
            "• Як записатись на прийом?\n"
            "• Чи є знижки?\n"
            "• Чи приймаєте дітей?\n"
            "• Які методи оплати?\n"
            "• Чи є парковка?\n\n"
            "💬 Просто напишіть своє питання і я відповім!",
            reply_markup=MAIN_KEYBOARD,
            parse_mode="Markdown"
        )
        return

    # ── AI відповідь ──
    status_msg = await update.message.reply_text("⏳ Думаю...")

    if len(user_memory[user_id]) > 10:
        user_memory[user_id] = user_memory[user_id][-10:]

    user_memory[user_id].append({"role": "user", "content": user_text})
    answer = await ask_ai_with_memory(user_memory[user_id])
    user_memory[user_id].append({"role": "assistant", "content": answer})

    await status_msg.edit_text(answer)

# ====== ЗАПУСК ======
if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("✅ Бот «Посмішка» запущено!")
    app.run_polling()