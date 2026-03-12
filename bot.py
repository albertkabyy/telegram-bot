import time
import os
import httpx
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters

# ====== НАСТРОЙКИ ======
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
API_URL = "https://api.groq.com/openai/v1/chat/completions"

MANAGER_USERNAME = "@nektarinx"
ADMIN_ID = int(os.environ.get("ADMIN_ID", "694342459"))

SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID") # ← ID з URL таблиці
CREDENTIALS_PATH = "credentials.json"

PRIMARY_MODEL = "llama-3.3-70b-versatile"
FALLBACK_MODEL = "mixtral-8x7b-32768"





# ====== РОБОЧИЙ РОЗКЛАД ======
WORK_HOURS = ["09:00", "10:00", "11:00", "12:00", "13:00", "14:00", "15:00", "16:00", "17:00"]
WORK_DAYS = [0, 1, 2, 3, 4, 5]
DAYS_AHEAD = 7

DAY_NAMES = {
    0: "Понеділок", 1: "Вівторок", 2: "Середа",
    3: "Четвер", 4: "П'ятниця", 5: "Субота", 6: "Неділя"
}

scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]


# ====== ПІДКЛЮЧЕННЯ SHEETS ======
def connect_sheets():
    try:
        creds_json = os.environ.get("GOOGLE_CREDENTIALS")
        if creds_json:
            creds_dict = json.loads(creds_json)
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        else:
            creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_PATH, scope)

        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(SPREADSHEET_ID)

        try:
            sheet_leads = spreadsheet.worksheet("Заявки")
        except:
            sheet_leads = spreadsheet.add_worksheet(title="Заявки", rows=1000, cols=10)
            sheet_leads.append_row(["№", "Дата", "Час запису", "Ім'я", "Телефон", "Послуга", "Дата прийому", "Час прийому", "Telegram ID"])

        try:
            sheet_stats = spreadsheet.worksheet("Статистика")
        except:
            sheet_stats = spreadsheet.add_worksheet(title="Статистика", rows=20, cols=3)
            sheet_stats.append_row(["Показник", "Значення", "Оновлено"])

        try:
            sheet_slots = spreadsheet.worksheet("Розклад")
        except:
            sheet_slots = spreadsheet.add_worksheet(title="Розклад", rows=1000, cols=3)
            sheet_slots.append_row(["Дата", "Час", "Статус"])

        return sheet_leads, sheet_stats, sheet_slots

    except Exception as e:
        print(f"⚠️ Помилка підключення до Google Sheets: {e}")
        return None, None, None

sheet, sheet_stats, sheet_slots = connect_sheets()

# ====== СЛОТИ ======
def get_booked_slots():
    try:
        if sheet_slots is None:
            return set()
        rows = sheet_slots.get_all_values()[1:]
        return {(r[0], r[1]) for r in rows if len(r) >= 2}
    except:
        return set()

def book_slot(date_str, time_str):
    try:
        if sheet_slots is None:
            return False
        sheet_slots.append_row([date_str, time_str, "зайнято"])
        return True
    except:
        return False

# ====== ЗБЕРЕЖЕННЯ ЗАЯВКИ ======
def save_to_sheets(name, phone, service, date_str, time_str, user_id):
    try:
        if sheet is None:
            return False
        all_rows = sheet.get_all_values()
        row_num = len(all_rows)
        now = datetime.now()
        sheet.append_row([row_num, now.strftime("%d.%m.%Y"), now.strftime("%H:%M"),
                          name, phone, service, date_str, time_str, str(user_id)])
        return True
    except Exception as e:
        print(f"⚠️ Помилка запису: {e}")
        return False

# ====== СТАТИСТИКА ======
def update_stats_sheet():
    try:
        if sheet_stats is None:
            return
        now = datetime.now().strftime("%d.%m.%Y %H:%M")
        total_leads = len(sheet.get_all_values()) - 1 if sheet else 0
        sheet_stats.clear()
        sheet_stats.append_row(["Показник", "Значення", "Оновлено"])
        sheet_stats.append_row(["👥 Унікальних користувачів", len(stats["total_users"]), now])
        sheet_stats.append_row(["💬 Всього повідомлень", stats["total_messages"], now])
        sheet_stats.append_row(["📋 Всього заявок", total_leads, now])
        sheet_stats.append_row(["🕐 Бот працює з", datetime.fromtimestamp(stats["start_time"]).strftime("%d.%m.%Y %H:%M"), now])
    except Exception as e:
        print(f"⚠️ Помилка статистики: {e}")

# ====== КЛАВІАТУРИ РОЗКЛАДУ ======
def get_days_keyboard():
    booked = get_booked_slots()
    today = datetime.now().date()
    buttons = []
    row = []
    for i in range(DAYS_AHEAD):
        day = today + timedelta(days=i)
        if day.weekday() not in WORK_DAYS:
            continue
        date_str = day.strftime("%d.%m.%Y")
        day_name = DAY_NAMES[day.weekday()]
        short_date = day.strftime("%d.%m")
        free_slots = [h for h in WORK_HOURS if (date_str, h) not in booked]
        if free_slots:
            row.append(InlineKeyboardButton(f"📅 {day_name} {short_date}", callback_data=f"day_{date_str}"))
        else:
            row.append(InlineKeyboardButton(f"❌ {day_name} {short_date}", callback_data="day_full"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("❌ Скасувати", callback_data="cancel_booking")])
    return InlineKeyboardMarkup(buttons)

def get_time_keyboard(date_str):
    booked = get_booked_slots()
    buttons = []
    row = []
    for i, hour in enumerate(WORK_HOURS):
        if (date_str, hour) in booked:
            row.append(InlineKeyboardButton(f"❌ {hour}", callback_data="time_taken"))
        else:
            row.append(InlineKeyboardButton(f"✅ {hour}", callback_data=f"time_{date_str}_{hour}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("✏️ Вказати свій час", callback_data=f"custom_time_{date_str}")])
    buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_to_days")])
    buttons.append([InlineKeyboardButton("❌ Скасувати", callback_data="cancel_booking")])
    return InlineKeyboardMarkup(buttons)

# ====== ОСОБИСТІСТЬ БОТА ======
SYSTEM_PROMPT = """Ти — Софія, AI-асистент стоматологічної клініки «Посмішка» у Києві.

Правила (ОБОВ'ЯЗКОВО):
- Відповідай ТІЛЬКИ українською мовою
- Будь теплою і професійною, використовуй емодзі
- НІКОЛИ не використовуй слова, символи або літери з інших мов — тільки українська!
- На привітання відповідай: "Привіт! 😊 Чим можу допомогти?"
- Якщо клієнт хоче записатись — кажи ТІЛЬКИ це: "Натисніть кнопку 📅 Записатись на прийом нижче 👇"
- НЕ згадуй жодного сайту — сайту не існує
- НЕ вигадуй інформацію якої немає в базі знань
- НЕ збирай імена та телефони сам — це робить окрема форма через кнопку
- Якщо питання про діагноз — рекомендуй прийти на безкоштовну консультацію
- Якщо не знаєш відповіді — скажи: "Уточніть це питання у адміністратора"
- Відповіді роби короткими і чіткими — максимум 3-4 речення
"""

FAQ = """
=== БАЗА ЗНАНЬ КЛІНІКИ «ПОСМІШКА» ===

📍 Адреса: м. Київ, вул. Хрещатик, 12
📞 Телефон: +38 (044) 123-45-67
🕐 Графік: Пн-Пт 9:00-20:00, Сб 10:00-17:00, Нд — вихідний

ПОСЛУГИ ТА ЦІНИ:
- Консультація — БЕЗКОШТОВНО
- Лікування карієсу — від 800 грн
- Пломба світлова — від 900 грн
- Чистка зубів — 1200 грн
- Відбілювання — 3500 грн
- Видалення зуба — від 600 грн
- Імплантація — від 15000 грн
- Брекети металеві — від 18000 грн
- Елайнери — від 30000 грн
- Лікування молочного зуба — від 600 грн

ЧАСТІ ПИТАННЯ:
Q: Чи боляче? A: Ні, використовуємо сучасну анестезію
Q: Чи є знижки? A: 5% з другого візиту, 10% для пенсіонерів і дітей
Q: Діти? A: Так, з 3 років, окремий кабінет з мультиками 🎁
Q: Оплата? A: Картка, готівка, Apple/Google Pay, розстрочка
Q: Парковка? A: Безкоштовна, 10 місць
"""

# ====== КЛАВІАТУРИ ======
MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["🦷 Наші послуги", "💰 Ціни"],
        ["📅 Записатись на прийом", "❓ FAQ"],
        ["📞 Контакти", "👨‍💼 Покликати менеджера"],  # ← змінили рядок
        ["🏠 Головне меню"]
    ],
    resize_keyboard=True,
    input_field_placeholder="Оберіть або напишіть питання..."
)

SERVICE_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["🦷 Консультація", "🔧 Лікування карієсу"],
        ["✨ Відбілювання", "🧹 Чистка зубів"],
        ["🔩 Імплантація", "😬 Брекети / Елайнери"],
        ["👶 Дитяча стоматологія", "❓ Не знаю — потрібна консультація"]
    ],
    resize_keyboard=True,
    input_field_placeholder="Оберіть послугу..."
)

# ====== ДАНІ В ПАМ'ЯТІ ======
user_memory = {}
user_state = {}
spam_tracker = {}
stats = {
    "total_users": set(),
    "total_messages": 0,
    "start_time": time.time()
}

# ====== АНТИСПАМ ======
def is_spam(user_id):
    now = time.time()
    if user_id not in spam_tracker:
        spam_tracker[user_id] = []
    spam_tracker[user_id] = [t for t in spam_tracker[user_id] if now - t < 60]
    spam_tracker[user_id].append(now)
    return len(spam_tracker[user_id]) > 10

# ====== МОДЕЛІ ======
PRIMARY_MODEL = "llama-3.3-70b-versatile"
FALLBACK_MODEL = "mixtral-8x7b-32768"  # резервна

async def ask_ai_with_memory(messages):
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    # Пробуємо основну модель, потім резервну
    for model in [PRIMARY_MODEL, FALLBACK_MODEL]:
        payload = {
            "model": model,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT + "\n" + FAQ}] + messages,
            "max_tokens": 512,
            "temperature": 0.7
        }
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(API_URL, headers=headers, json=payload, timeout=30.0)
                data = response.json()

                if response.status_code == 200:
                    return data["choices"][0]["message"]["content"].strip()

                # Якщо помилка — логуємо і пробуємо резервну
                print(f"⚠️ Модель {model} відповіла з помилкою {response.status_code} — пробую резервну...")

            except httpx.TimeoutException:
                print(f"⚠️ Модель {model} — timeout, пробую резервну...")
            except Exception as e:
                print(f"⚠️ Модель {model} — помилка: {e}, пробую резервну...")

    # Якщо обидві моделі не відповіли
    return "⚠️ Сервіс тимчасово недоступний. Зверніться до адміністратора: {MANAGER_USERNAME}"

# ====== КОМАНДА /start ======
async def start(update: Update, context):
    user_id = update.message.from_user.id
    user_memory[user_id] = []
    user_state.pop(user_id, None)
    stats["total_users"].add(user_id)
    await update.message.reply_text(
        "👋 Вітаємо в стоматологічній клініці *«Посмішка»*!\n\n"
        "Я — Софія, ваш AI-асистент 🦷\n\n"
        "Допоможу вам з:\n"
        "• 🦷 Інформацією про послуги та ціни\n"
        "• 📅 Записом на прийом\n"
        "• ❓ Відповідями на питання\n"
        "• 📞 Контактами клініки\n\n"
        "Перший візит та консультація — *БЕЗКОШТОВНО* 🎁\n\n"
        "Оберіть що вас цікавить 👇",
        reply_markup=MAIN_KEYBOARD,
        parse_mode="Markdown"
    )

# ====== КОМАНДА /cancel ======
async def cancel(update: Update, context):
    user_id = update.message.from_user.id
    if user_id in user_state:
        del user_state[user_id]
        await update.message.reply_text("❌ Запис скасовано. Повертаємось в меню 👇", reply_markup=MAIN_KEYBOARD)
    else:
        await update.message.reply_text("Немає активного запису.", reply_markup=MAIN_KEYBOARD)

# ====== КОМАНДА /stats ======
async def show_stats(update: Update, context):
    update_stats_sheet()
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ У вас немає доступу.")
        return
    uptime_hours = int((time.time() - stats["start_time"]) / 3600)
    uptime_minutes = int((time.time() - stats["start_time"]) % 3600 / 60)
    try:
        total_leads = len(sheet.get_all_values()) - 1 if sheet else 0
    except:
        total_leads = "недоступно"
    await update.message.reply_text(
        f"📊 *Статистика бота «Посмішка»:*\n\n"
        f"👥 Унікальних користувачів: {len(stats['total_users'])}\n"
        f"💬 Всього повідомлень: {stats['total_messages']}\n"
        f"📋 Заявок в таблиці: {total_leads}\n"
        f"⏱ Працює: {uptime_hours}г {uptime_minutes}хв",
        parse_mode="Markdown"
    )

# ====== ОБРОБКА INLINE КНОПОК ======
async def handle_callback(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    # Зайнятий день
    if data == "day_full":
        await query.answer("❌ Цей день повністю зайнятий!", show_alert=True)
        return

    # Зайнятий час
    if data == "time_taken":
        await query.answer("❌ Цей час вже зайнятий!", show_alert=True)
        return

    # Скасування
    if data == "cancel_booking":
        user_state.pop(user_id, None)
        await query.edit_message_text("❌ Запис скасовано.")
        await context.bot.send_message(chat_id=user_id, text="Повертаємось в меню 👇", reply_markup=MAIN_KEYBOARD)
        return

    # Назад до днів
    if data == "back_to_days":
        await query.edit_message_text("📅 *Оберіть зручний день:*", reply_markup=get_days_keyboard(), parse_mode="Markdown")
        return

    # Свій час
    if data.startswith("custom_time_"):
        date_str = data.replace("custom_time_", "")
        user_state[user_id]["date"] = date_str
        user_state[user_id]["step"] = "custom_time"
        await query.edit_message_text(
            f"✏️ Введіть бажаний час для *{date_str}*\n\n"
            f"Наприклад: _08:30_ або _18:00_\n\n"
            f"_(або /cancel щоб скасувати)_",
            parse_mode="Markdown"
        )
        return

    # Вибір дня
    if data.startswith("day_"):
        date_str = data.replace("day_", "")
        if user_id in user_state:
            user_state[user_id]["date"] = date_str
            user_state[user_id]["step"] = "time"
        day_obj = datetime.strptime(date_str, "%d.%m.%Y")
        day_name = DAY_NAMES[day_obj.weekday()]
        await query.edit_message_text(
            f"📅 *{day_name}, {date_str}*\n\n"
            f"✅ — вільно  ❌ — зайнято\n\n"
            f"Оберіть зручний час:",
            reply_markup=get_time_keyboard(date_str),
            parse_mode="Markdown"
        )
        return

    # Вибір часу
    if data.startswith("time_"):
        parts = data.split("_")
        date_str = parts[1]
        time_str = parts[2]
        if user_id in user_state:
            user_state[user_id]["date"] = date_str
            user_state[user_id]["time"] = time_str
            user_state[user_id]["step"] = "confirm"
        day_obj = datetime.strptime(date_str, "%d.%m.%Y")
        day_name = DAY_NAMES[day_obj.weekday()]
        service = user_state[user_id].get("service", "не вказано")
        name = user_state[user_id].get("name", "")
        phone = user_state[user_id].get("phone", "")
        confirm_keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Підтвердити", callback_data="confirm_yes"),
                InlineKeyboardButton("❌ Скасувати", callback_data="cancel_booking")
            ],
            [InlineKeyboardButton("⬅️ Змінити час", callback_data=f"day_{date_str}")]
        ])
        await query.edit_message_text(
            f"📋 *Підтвердіть запис:*\n\n"
            f"👤 Ім'я: {name}\n"
            f"📞 Телефон: {phone}\n"
            f"🦷 Послуга: {service}\n"
            f"📅 Дата: {day_name}, {date_str}\n"
            f"🕐 Час: {time_str}\n\n"
            f"Все вірно?",
            reply_markup=confirm_keyboard,
            parse_mode="Markdown"
        )
        return

    # Підтвердження
# Підтвердження
    if data == "confirm_yes":
        if user_id not in user_state:
            await query.answer("⚠️ Помилка — почніть запис заново.", show_alert=True)
            return

        state = user_state[user_id]
        name = state.get("name", "")
        phone = state.get("phone", "")
        service = state.get("service", "")
        date_str = state.get("date", "")
        time_str = state.get("time", "")
        del user_state[user_id]

        day_obj = datetime.strptime(date_str, "%d.%m.%Y")
        day_name = DAY_NAMES[day_obj.weekday()]

        # Спочатку показуємо результат клієнту — БЕЗ затримок
        await query.edit_message_text(
            f"✅ *Запис підтверджено!*\n\n"
            f"👤 {name}\n"
            f"🦷 {service}\n"
            f"📅 {day_name}, {date_str}\n"
            f"🕐 {time_str}\n\n"
            f"Чекаємо вас! До зустрічі 😊",
            parse_mode="Markdown"
        )
        await context.bot.send_message(
            chat_id=user_id,
            text="Якщо маєте питання — я тут! 😊",
            reply_markup=MAIN_KEYBOARD
        )

        # Потім вже зберігаємо в таблицю (клієнт вже бачить відповідь)
        book_slot(date_str, time_str)
        saved = save_to_sheets(name, phone, service, date_str, time_str, user_id)
        update_stats_sheet()
        sheets_status = "📊 Збережено в таблицю ✅" if saved else "📊 Таблиця недоступна ⚠️"

        # Сповіщення адміну
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"🔔 *Нова заявка на прийом!*\n\n"
                 f"👤 Ім'я: {name}\n"
                 f"📞 Телефон: {phone}\n"
                 f"🦷 Послуга: {service}\n"
                 f"📅 Дата: {day_name}, {date_str}\n"
                 f"🕐 Час: {time_str}\n"
                 f"🆔 Telegram ID: {user_id}\n\n"
                 f"{sheets_status}",
            parse_mode="Markdown"
        )
        return

# ====== ОБРОБКА ПОВІДОМЛЕНЬ ======
async def handle_message(update: Update, context):
    user_id = update.message.from_user.id
    user_text = update.message.text

    if is_spam(user_id):
        await update.message.reply_text("⚠️ Зачекайте трохи перед наступним повідомленням.")
        return

    stats["total_users"].add(user_id)
    stats["total_messages"] += 1

    if user_id not in user_memory:
        user_memory[user_id] = []

    # ── Ім'я ──
    if user_id in user_state and user_state[user_id].get("step") == "name":
        user_state[user_id]["name"] = user_text
        user_state[user_id]["step"] = "phone"
        await update.message.reply_text("📞 Крок 2 з 4 — Введіть ваш *номер телефону:*", parse_mode="Markdown")
        return

# ── Телефон ──
    if user_id in user_state and user_state[user_id].get("step") == "phone":
        # Перевірка телефону — тільки цифри, довжина 10-13
        phone_clean = user_text.replace("+", "").replace("-", "").replace(" ", "").replace("(", "").replace(")", "")
        if not phone_clean.isdigit() or not (10 <= len(phone_clean) <= 13):
            await update.message.reply_text(
                "❌ Невірний формат номера!\n\n"
                "Введіть номер у форматі:\n"
                "• 0987654321\n"
                "• +380987654321\n\n"
                "Спробуйте ще раз 👇"
            )
            return
        user_state[user_id]["phone"] = user_text
        user_state[user_id]["step"] = "service"
        await update.message.reply_text("🦷 Крок 3 з 4 — Оберіть послугу:", reply_markup=SERVICE_KEYBOARD)
        return

    # ── Послуга ──
    if user_id in user_state and user_state[user_id].get("step") == "service":
        user_state[user_id]["service"] = user_text
        user_state[user_id]["step"] = "date"
        await update.message.reply_text("📅 Крок 4 з 4 — Оберіть зручний день:", reply_markup=ReplyKeyboardRemove())
        await update.message.reply_text("👇 Вільні дні для запису:", reply_markup=get_days_keyboard())
        return

# ── Свій час ──
    if user_id in user_state and user_state[user_id].get("step") == "custom_time":
        import re
        time_pattern = re.compile(r'^([0-1]?[0-9]|2[0-3]):([0-5][0-9])$')
        if not time_pattern.match(user_text.strip()):
            await update.message.reply_text(
                "❌ Невірний формат часу!\n\n"
                "Введіть час у форматі:\n"
                "• 09:00\n"
                "• 14:30\n"
                "• 18:00\n\n"
                "Спробуйте ще раз 👇"
            )
            return
        user_state[user_id]["time"] = user_text.strip()
        user_state[user_id]["step"] = "confirm"
        state = user_state[user_id]
        day_obj = datetime.strptime(state["date"], "%d.%m.%Y")
        day_name = DAY_NAMES[day_obj.weekday()]
        confirm_keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Підтвердити", callback_data="confirm_yes"),
                InlineKeyboardButton("❌ Скасувати", callback_data="cancel_booking")
            ]
        ])
        await update.message.reply_text(
            f"📋 *Підтвердіть запис:*\n\n"
            f"👤 Ім'я: {state['name']}\n"
            f"📞 Телефон: {state['phone']}\n"
            f"🦷 Послуга: {state['service']}\n"
            f"📅 Дата: {day_name}, {state['date']}\n"
            f"🕐 Час: {user_text.strip()}\n\n"
            f"Все вірно?",
            reply_markup=confirm_keyboard,
            parse_mode="Markdown"
        )
        return

    # ── Кнопка: Покликати менеджера ──
    if user_text == "👨‍💼 Покликати менеджера":
        # Повідомлення клієнту
        await update.message.reply_text(
            "👨‍💼 *Підключаю менеджера!*\n\n"
            f"Наш менеджер {MANAGER_USERNAME} зв'яжеться з вами найближчим часом.\n\n"
            "Або напишіть йому напряму 👆",
            reply_markup=MAIN_KEYBOARD,
            parse_mode="Markdown"
        )
        # Сповіщення адміну
        user_name = update.message.from_user.first_name or "Невідомий"
        username = f"@{update.message.from_user.username}" if update.message.from_user.username else "без username"
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"🆘 *Клієнт викликає менеджера!*\n\n"
                 f"👤 Ім'я: {user_name}\n"
                 f"💬 Username: {username}\n"
                 f"🆔 Telegram ID: {update.message.from_user.id}\n\n"
                 f"Клієнт потребує допомоги!",
            parse_mode="Markdown"
        )
        return


    # ── Головне меню ──
    if user_text == "🏠 Головне меню":
        user_memory[user_id] = []
        await update.message.reply_text("🏠 *Головне меню*\n\nОберіть що вас цікавить 👇", reply_markup=MAIN_KEYBOARD, parse_mode="Markdown")
        return

    # ── Контакти ──
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

    # ── Записатись ──
    if user_text == "📅 Записатись на прийом":
        user_state[user_id] = {"step": "name"}
        user_memory[user_id] = []
        await update.message.reply_text(
            "📝 *Запис на прийом*\n\n"
            "Крок 1 з 4 — Введіть ваше *ім'я:*\n\n"
            "_(або /cancel щоб скасувати)_",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode="Markdown"
        )
        return

    # ── FAQ ──
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
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CommandHandler("stats", show_stats))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("✅ Бот «Посмішка» з розкладом запущено!")
    app.run_polling()