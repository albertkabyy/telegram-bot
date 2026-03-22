import time
import os
import asyncio
import httpx
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters

# ====== SETTINGS ======
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
API_URL = "https://api.groq.com/openai/v1/chat/completions"

SUPPORT_USERNAME = "@123"
ADMIN_ID = 694342459
ADMIN_IDS = [694342459]

SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "")
CREDENTIALS_PATH = "credentials.json"

PRIMARY_MODEL = "llama-3.3-70b-versatile"
FALLBACK_MODEL = "mixtral-8x7b-32768"

# ====== RATE LIMIT ======
AI_RATE_LIMIT = 3       # max requests per window
AI_RATE_WINDOW = 60     # seconds
user_ai_requests = {}   # {user_id: [timestamps]}

def check_ai_rate_limit(user_id):
    now = time.time()
    if user_id not in user_ai_requests:
        user_ai_requests[user_id] = []
    user_ai_requests[user_id] = [t for t in user_ai_requests[user_id] if now - t < AI_RATE_WINDOW]
    if len(user_ai_requests[user_id]) >= AI_RATE_LIMIT:
        return False
    user_ai_requests[user_id].append(now)
    return True

# ====== AI CACHE ======
ai_cache = {}           # {query_hash: (answer, timestamp)}
AI_CACHE_TTL = 3600     # cache lives 1 hour

def get_cached_answer(query):
    key = hash(query.lower().strip())
    if key in ai_cache:
        answer, ts = ai_cache[key]
        if time.time() - ts < AI_CACHE_TTL:
            return answer
    return None

def set_cached_answer(query, answer):
    key = hash(query.lower().strip())
    ai_cache[key] = (answer, time.time())

scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

# ====== LANGUAGE CONTENT ======
LANGUAGES = {
    "🇬🇧 English": "en",
    "🇪🇸 Español": "es",
    "🇵🇹 Português": "pt",
    "🇩🇪 Deutsch": "de",
    "🇷🇺 Русский": "ru"
}

CONTENT = {
    "en": {
        "welcome": (
            "🎮 *Welcome to B.SITE!*\n\n"
            "I'm Alex, your 24/7 AI assistant 🤖\n\n"
            "I can help you with:\n"
            "📦 Cases & unboxing\n"
            "🎰 Games & roulette\n"
            "💰 Deposits & withdrawals\n"
            "🎁 Bonuses & promo codes\n"
            "❓ Any platform questions\n\n"
            "Choose an option below 👇"
        ),
        "cases": (
            "📦 *Cases on B.SITE*\n\n"
            "🏢 *Official Cases* — curated by B.SITE team\n"
            "🛠 *Custom Cases* — created by players!\n"
            "   └ Earn *2%* every time someone opens your case\n\n"
            "💡 *How it works:*\n"
            "   1️⃣ Choose a case\n"
            "   2️⃣ Click Open\n"
            "   3️⃣ Get your CS2 skin instantly\n\n"
            "🎯 The more popular your case → the more you earn!\n\n"
            "👉 Visit *b.site* to open cases!"
        ),
        "games": (
            "🎯 *Games on B.SITE*\n\n"
            "🎰 *Roulette* — bet on 🔴 Red / ⚫ Black / 🟡 Gold\n\n"
            "💣 *Hidden Mines* — minesweeper with real money\n"
            "   └ Avoid mines, cash out before you explode!\n\n"
            "⚔️ *Case Battles* — open cases vs other players\n"
            "   └ 2-4 players, highest drop value wins!\n\n"
            "🎡 *Spin Duels* — spin wheel vs opponents\n"
            "   └ Winner takes all!\n\n"
            "✈️ *Cluckin Airways* — crash-style game\n\n"
            "🔐 All games are *Provably Fair*"
        ),
        "deposit": (
            "💰 *Deposit & Withdraw*\n\n"
            "📥 *Deposit methods:*\n"
            "   🔸 Crypto: BTC, ETH, USDT, SOL, LTC, BNB, DOGE, USDC\n"
            "   🔸 Skins: CS2 & Rust via Steam\n"
            "   🔸 Cash: Kinguin Gift Cards\n"
            "   🔸 Minimum: *$1*\n\n"
            "📤 *Withdraw methods:*\n"
            "   🔸 Crypto: USDT, SOL, LTC\n"
            "   🔸 Skins: CS2 & Rust via Steam\n"
            "   🔸 Instant processing\n\n"
            "🔑 *How to redeem Kinguin card:*\n"
            "   1️⃣ Click '+' or Profile → Cashier\n"
            "   2️⃣ Select Kinguin\n"
            "   3️⃣ Enter your code → Redeem!"
        ),
        "bonuses": (
            "🎁 *Bonuses & Rewards*\n\n"
            "🔥 Promo code *WELCOME* → +3% deposit & 3 free cases\n"
            "🆓 *Free Cases* — available daily for all users\n"
            "💧 *Faucet* — claim free coins periodically\n"
            "📈 *Rakeback* — get % back from every bet\n"
            "🏆 *Leaderboard* — top players win big prizes\n"
            "👥 *Affiliates* — earn % from referred users\n"
            "🛠 *Case Creator* — earn 2% from your cases\n\n"
            "💬 Daily promo codes on our *Discord* server!"
        ),
        "faq": (
            "❓ *FAQ*\n\n"
            "• How do I open a case?\n"
            "• How to deposit funds?\n"
            "• How to withdraw winnings?\n"
            "• Is the site provably fair?\n"
            "• How does Case Creator work?\n"
            "• How to join Case Battles?\n"
            "• Where to find promo codes?\n\n"
            "💬 Type your question — I'll answer instantly!"
        ),
        "support": (
            "🆘 *Support*\n\n"
            "Our support team is available 24/7!\n\n"
            f"💬 Contact directly: @123\n"
            "🌐 Live chat on b.site\n"
            "📧 support@b.site\n\n"
            "Or press the button below to call a manager 👇"
        ),
        "thinking": "⏳ Thinking...",
        "lang_select": "🌍 Select your language:",
        "lang_set": "✅ Language set to English!",
        "play_now": "🎮 *Play now:*",
        "rate_limit": "⚠️ Too many requests! Please wait a minute and try again.",
    },
    "es": {
        "welcome": (
            "🎮 *¡Bienvenido a B.SITE!*\n\n"
            "Soy Alex, tu asistente IA 24/7 🤖\n\n"
            "Puedo ayudarte con:\n"
            "📦 Casos y unboxing\n"
            "🎰 Juegos y ruleta\n"
            "💰 Depósitos y retiros\n"
            "🎁 Bonos y códigos promo\n"
            "❓ Cualquier pregunta\n\n"
            "Elige una opción 👇"
        ),
        "cases": (
            "📦 *Casos en B.SITE*\n\n"
            "🏢 *Casos Oficiales* — del equipo B.SITE\n"
            "🛠 *Casos Personalizados* — ¡creados por jugadores!\n"
            "   └ Gana *2%* cada vez que alguien abra tu caso\n\n"
            "💡 *Cómo funciona:*\n"
            "   1️⃣ Elige un caso\n"
            "   2️⃣ Haz clic en Abrir\n"
            "   3️⃣ ¡Recibe tu skin CS2 al instante!\n\n"
            "👉 Visita *b.site*"
        ),
        "games": (
            "🎯 *Juegos en B.SITE*\n\n"
            "🎰 *Ruleta* — apuesta en 🔴 Rojo / ⚫ Negro / 🟡 Oro\n\n"
            "💣 *Minas* — buscaminas con dinero real\n\n"
            "⚔️ *Case Battles* — abre casos vs otros jugadores\n\n"
            "🎡 *Spin Duels* — ruleta vs oponentes\n\n"
            "✈️ *Cluckin Airways* — juego tipo crash\n\n"
            "🔐 Todos los juegos son *Provablemente Justos*"
        ),
        "deposit": (
            "💰 *Depósito y Retiro*\n\n"
            "📥 Crypto, Skins CS2/Rust, Kinguin. Mín: *$1*\n"
            "📤 Crypto (USDT, SOL, LTC), Skins Steam"
        ),
        "bonuses": (
            "🎁 *Bonos y Recompensas*\n\n"
            "🔥 Código *WELCOME* → +3% depósito y 3 casos gratis\n"
            "🆓 Casos Gratis diarios\n"
            "💧 Faucet, 📈 Rakeback, 👥 Afiliados"
        ),
        "faq": "❓ *Preguntas frecuentes*\n\n💬 ¡Escribe tu pregunta!",
        "support": "🆘 *Soporte 24/7*\n\n💬 @nektarinx\n🌐 b.site live chat",
        "thinking": "⏳ Pensando...",
        "lang_select": "🌍 Selecciona tu idioma:",
        "lang_set": "✅ ¡Idioma: Español!",
        "play_now": "🎮 *Jugar ahora:*",
        "rate_limit": "⚠️ ¡Demasiadas solicitudes! Espera un minuto.",
    },
    "pt": {
        "welcome": (
            "🎮 *Bem-vindo ao B.SITE!*\n\n"
            "Sou Alex, seu assistente IA 24/7 🤖\n\n"
            "Posso te ajudar com:\n"
            "📦 Cases e unboxing\n"
            "🎰 Jogos e roleta\n"
            "💰 Depósitos e saques\n"
            "🎁 Bônus e códigos promo\n"
            "❓ Qualquer dúvida\n\n"
            "Escolha uma opção 👇"
        ),
        "cases": (
            "📦 *Cases no B.SITE*\n\n"
            "🏢 *Cases Oficiais* — da equipe B.SITE\n"
            "🛠 *Cases Customizados* — criados por jogadores!\n"
            "   └ Ganhe *2%* toda vez que abrirem seu case\n\n"
            "💡 1️⃣ Escolha → 2️⃣ Abrir → 3️⃣ Skin na hora!\n\n"
            "👉 Acesse *b.site*"
        ),
        "games": (
            "🎯 *Jogos no B.SITE*\n\n"
            "🎰 *Roleta* — 🔴 Vermelho / ⚫ Preto / 🟡 Ouro\n\n"
            "💣 *Minas* — campo minado com dinheiro real\n\n"
            "⚔️ *Case Battles* — cases vs outros jogadores\n\n"
            "🎡 *Spin Duels* — roleta vs oponentes\n\n"
            "✈️ *Cluckin Airways* — crash\n\n"
            "🔐 Todos *Provably Fair*"
        ),
        "deposit": (
            "💰 *Depósito e Saque*\n\n"
            "📥 Crypto, Skins CS2/Rust, Kinguin. Mín: *$1*\n"
            "📤 Crypto (USDT, SOL, LTC), Skins Steam"
        ),
        "bonuses": (
            "🎁 *Bônus e Recompensas*\n\n"
            "🔥 Código *WELCOME* → +3% e 3 cases grátis\n"
            "🆓 Cases Grátis diários\n"
            "💧 Faucet, 📈 Rakeback, 👥 Afiliados"
        ),
        "faq": "❓ *Perguntas Frequentes*\n\n💬 Digite sua pergunta!",
        "support": "🆘 *Suporte 24/7*\n\n💬 @nektarinx\n🌐 b.site live chat",
        "thinking": "⏳ Pensando...",
        "lang_select": "🌍 Selecione seu idioma:",
        "lang_set": "✅ Idioma: Português!",
        "play_now": "🎮 *Jogar agora:*",
        "rate_limit": "⚠️ Muitas solicitações! Aguarde um minuto.",
    },
    "de": {
        "welcome": (
            "🎮 *Willkommen bei B.SITE!*\n\n"
            "Ich bin Alex, dein 24/7 KI-Assistent 🤖\n\n"
            "Ich helfe dir mit:\n"
            "📦 Cases & Unboxing\n"
            "🎰 Spiele & Roulette\n"
            "💰 Einzahlungen & Auszahlungen\n"
            "🎁 Boni & Promo-Codes\n"
            "❓ Alle Fragen\n\n"
            "Wähle eine Option 👇"
        ),
        "cases": (
            "📦 *Cases auf B.SITE*\n\n"
            "🏢 *Offizielle Cases* — vom B.SITE-Team\n"
            "🛠 *Custom Cases* — von Spielern erstellt!\n"
            "   └ Verdiene *2%* bei jedem Öffnen\n\n"
            "💡 1️⃣ Auswählen → 2️⃣ Öffnen → 3️⃣ Skin sofort!\n\n"
            "👉 Besuche *b.site*"
        ),
        "games": (
            "🎯 *Spiele auf B.SITE*\n\n"
            "🎰 *Roulette* — 🔴 Rot / ⚫ Schwarz / 🟡 Gold\n\n"
            "💣 *Hidden Mines* — Minesweeper mit echtem Geld\n\n"
            "⚔️ *Case Battles* — Cases vs andere Spieler\n\n"
            "🎡 *Spin Duels* — Rad vs Gegner\n\n"
            "✈️ *Cluckin Airways* — Crash\n\n"
            "🔐 Alle Spiele *Provably Fair*"
        ),
        "deposit": (
            "💰 *Einzahlung & Auszahlung*\n\n"
            "📥 Krypto, Skins CS2/Rust, Kinguin. Min: *$1*\n"
            "📤 Krypto (USDT, SOL, LTC), Skins Steam"
        ),
        "bonuses": (
            "🎁 *Boni & Belohnungen*\n\n"
            "🔥 Code *WELCOME* → +3% & 3 gratis Cases\n"
            "🆓 Gratis Cases täglich\n"
            "💧 Faucet, 📈 Rakeback, 👥 Affiliates"
        ),
        "faq": "❓ *FAQ*\n\n💬 Schreib deine Frage!",
        "support": "🆘 *Support 24/7*\n\n💬 @nektarinx\n🌐 b.site Live-Chat",
        "thinking": "⏳ Denke nach...",
        "lang_select": "🌍 Sprache auswählen:",
        "lang_set": "✅ Sprache: Deutsch!",
        "play_now": "🎮 *Jetzt spielen:*",
        "rate_limit": "⚠️ Zu viele Anfragen! Bitte warte eine Minute.",
    },
    "ru": {
        "welcome": (
            "🎮 *Добро пожаловать на B.SITE!*\n\n"
            "Я Алекс, твой ИИ-ассистент 24/7 🤖\n\n"
            "Помогу тебе с:\n"
            "📦 Кейсами и анбоксингом\n"
            "🎰 Играми и рулеткой\n"
            "💰 Депозитами и выводом\n"
            "🎁 Бонусами и промокодами\n"
            "❓ Любыми вопросами\n\n"
            "Выбери опцию ниже 👇"
        ),
        "cases": (
            "📦 *Кейсы на B.SITE*\n\n"
            "🏢 *Официальные кейсы* — от команды B.SITE\n"
            "🛠 *Кастомные кейсы* — созданные игроками!\n"
            "   └ Зарабатывай *2%* каждый раз когда открывают твой кейс\n\n"
            "💡 *Как это работает:*\n"
            "   1️⃣ Выбери кейс\n"
            "   2️⃣ Нажми Открыть\n"
            "   3️⃣ Получи CS2 скин мгновенно!\n\n"
            "🎯 Чем популярнее кейс → тем больше заработок!\n\n"
            "👉 Заходи на *b.site*"
        ),
        "games": (
            "🎯 *Игры на B.SITE*\n\n"
            "🎰 *Рулетка* — ставь на 🔴 Красное / ⚫ Чёрное / 🟡 Золото\n\n"
            "💣 *Сапёр* — минное поле на реальные деньги\n"
            "   └ Обходи мины, выводи до взрыва!\n\n"
            "⚔️ *Case Battles* — открывай кейсы vs других игроков\n"
            "   └ 2-4 игрока, у кого дороже дроп — тот победил!\n\n"
            "🎡 *Spin Duels* — крути колесо против оппонентов\n\n"
            "✈️ *Cluckin Airways* — краш-игра\n\n"
            "🔐 Все игры *Provably Fair*"
        ),
        "deposit": (
            "💰 *Депозит и Вывод*\n\n"
            "📥 *Методы пополнения:*\n"
            "   🔸 Крипто: BTC, ETH, USDT, SOL, LTC, BNB, DOGE, USDC\n"
            "   🔸 Скины: CS2 и Rust через Steam\n"
            "   🔸 Наличные: Kinguin Gift Cards\n"
            "   🔸 Минимум: *$1*\n\n"
            "📤 *Методы вывода:*\n"
            "   🔸 Крипто: USDT, SOL, LTC\n"
            "   🔸 Скины CS2 и Rust через Steam\n"
            "   🔸 Мгновенная обработка\n\n"
            "🔑 *Как использовать Kinguin карту:*\n"
            "   1️⃣ Нажми '+' или Профиль → Кассир\n"
            "   2️⃣ Выбери Kinguin\n"
            "   3️⃣ Введи код → Применить!"
        ),
        "bonuses": (
            "🎁 *Бонусы и Награды*\n\n"
            "🔥 Промокод *WELCOME* → +3% к депозиту и 3 бесплатных кейса\n"
            "🆓 *Бесплатные кейсы* — ежедневно для всех\n"
            "💧 *Кран* — получай бесплатные монеты\n"
            "📈 *Рейкбек* — возврат % с каждой ставки\n"
            "🏆 *Таблица лидеров* — топ игроки выигрывают призы\n"
            "👥 *Партнёрская программа* — % от рефералов\n"
            "🛠 *Создатель кейсов* — зарабатывай 2% со своих кейсов\n\n"
            "💬 Ежедневные промокоды в нашем *Discord*!"
        ),
        "faq": (
            "❓ *Часто задаваемые вопросы*\n\n"
            "• Как открыть кейс?\n"
            "• Как пополнить баланс?\n"
            "• Как вывести выигрыш?\n"
            "• Как работает Provably Fair?\n"
            "• Как создать свой кейс?\n"
            "• Где найти промокоды?\n\n"
            "💬 Напиши свой вопрос — отвечу мгновенно!"
        ),
        "support": (
            "🆘 *Поддержка 24/7*\n\n"
            "Наша команда всегда готова помочь!\n\n"
            "💬 Написать напрямую: @123\n"
            "🌐 Live chat на b.site\n"
            "📧 support@b.site\n\n"
            "Или нажми кнопку ниже 👇"
        ),
        "thinking": "⏳ Думаю...",
        "lang_select": "🌍 Выбери язык:",
        "lang_set": "✅ Язык: Русский!",
        "play_now": "🎮 *Играть:*",
        "rate_limit": "⚠️ Слишком много запросов! Подожди минуту.",
    }
}

# ====== KEYBOARDS ======
def get_main_keyboard(lang="en"):
    labels = {
        "en": [["📦 Cases", "🎯 Games"], ["💰 Deposit & Withdraw", "🎁 Bonuses"], ["❓ FAQ", "🆘 Support"], ["🌍 Language"]],
        "es": [["📦 Casos", "🎯 Juegos"], ["💰 Depósito y Retiro", "🎁 Bonos"], ["❓ FAQ", "🆘 Soporte"], ["🌍 Idioma"]],
        "pt": [["📦 Cases", "🎯 Jogos"], ["💰 Depósito e Saque", "🎁 Bônus"], ["❓ FAQ", "🆘 Suporte"], ["🌍 Idioma"]],
        "de": [["📦 Cases", "🎯 Spiele"], ["💰 Einzahlung & Auszahlung", "🎁 Boni"], ["❓ FAQ", "🆘 Support"], ["🌍 Sprache"]],
        "ru": [["📦 Кейсы", "🎯 Игры"], ["💰 Депозит и Вывод", "🎁 Бонусы"], ["❓ FAQ", "🆘 Поддержка"], ["🌍 Язык"]],
    }
    return ReplyKeyboardMarkup(labels.get(lang, labels["en"]), resize_keyboard=True, input_field_placeholder="Ask anything...")

def get_language_keyboard():
    return ReplyKeyboardMarkup(
        [["🇬🇧 English", "🇪🇸 Español"], ["🇵🇹 Português", "🇩🇪 Deutsch"], ["🇷🇺 Русский"]],
        resize_keyboard=True
    )

def get_games_inline_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📦 Cases", url="https://b.site/cases"),
            InlineKeyboardButton("🎰 Roulette", url="https://b.site/roulette"),
        ],
        [
            InlineKeyboardButton("💣 Mines", url="https://b.site/mines"),
            InlineKeyboardButton("⚔️ Case Battles", url="https://b.site/case-battles"),
        ],
        [
            InlineKeyboardButton("🎡 Spin Duels", url="https://b.site/spin-duels"),
            InlineKeyboardButton("✈️ Cluckin Airways", url="https://b.site/cluckin-airways"),
        ],
        [
            InlineKeyboardButton("🆓 Free Case", url="https://b.site/r/FREE"),
        ]
    ])

def get_support_inline_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Live Chat on b.site", url="https://b.site")],
        [InlineKeyboardButton("📨 Contact Manager", callback_data="call_manager")]
    ])

# ====== SHEETS CONNECTION ======
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
            sheet_stats = spreadsheet.worksheet("Stats")
        except:
            sheet_stats = spreadsheet.add_worksheet(title="Stats", rows=20, cols=3)
            sheet_stats.append_row(["Metric", "Value", "Updated At"])
        try:
            sheet_knowledge = spreadsheet.worksheet("Knowledge")
        except:
            sheet_knowledge = spreadsheet.add_worksheet(title="Knowledge", rows=100, cols=3)
            sheet_knowledge.append_row(["Topic", "Keywords", "Answer"])
            sheet_knowledge.append_row(["Cases", "case,open,drop,skin,unbox,custom,create,2%", "B.SITE has official cases and custom cases created by players. Case creators earn 2% every time their case is opened!"])
            sheet_knowledge.append_row(["Games", "game,roulette,mines,battle,duel,crash,spin,hidden,cluckin", "B.SITE offers: Roulette (Red/Black/Gold), Hidden Mines, Case Battles (2-4 players), Spin Duels, Cluckin Airways. All provably fair."])
            sheet_knowledge.append_row(["Deposit", "deposit,add,fund,money,pay,top up,bitcoin,crypto,steam,skin,kinguin", "Deposit via: Crypto (BTC/ETH/USDT/SOL/LTC/BNB/DOGE/USDC), CS2/Rust skins, or Kinguin Gift Cards. Minimum $1."])
            sheet_knowledge.append_row(["Withdraw", "withdraw,cashout,payout,send,get money", "Withdraw via: Crypto (USDT, SOL, LTC) or Steam skins. Instant processing."])
            sheet_knowledge.append_row(["Promo", "promo,code,bonus,free,discount,welcome,rakeback,faucet,affiliate", "Code WELCOME = +3% deposit + 3 free cases. Daily free cases, faucet, rakeback, leaderboard, affiliates available."])
            sheet_knowledge.append_row(["Discord", "discord,community,server,chat,daily,code", "Join B.SITE Discord for daily promo codes, community and announcements!"])
            sheet_knowledge.append_row(["Fair", "fair,provably,seed,hash,cheat,rigged,trust,verify", "All games use Provably Fair system. Every result verifiable via seed hash."])
            sheet_knowledge.append_row(["Kinguin", "kinguin,gift card,redeem,code,cash", "Redeem Kinguin card: click '+' → Cashier → Kinguin → enter code → Redeem!"])
        return sheet_stats, sheet_knowledge
    except Exception as e:
        print(f"⚠️ Sheets error: {e}")
        return None, None

sheet_stats, sheet_knowledge = connect_sheets()

# ====== STATISTICS ======
def update_stats_sheet():
    try:
        if sheet_stats is None:
            return
        now = datetime.now().strftime("%d.%m.%Y %H:%M")
        sheet_stats.clear()
        sheet_stats.append_row(["Metric", "Value", "Updated At"])
        sheet_stats.append_row(["👥 Unique Users", len(stats["total_users"]), now])
        sheet_stats.append_row(["💬 Total Messages", stats["total_messages"], now])
        sheet_stats.append_row(["🕐 Uptime Since", datetime.fromtimestamp(stats["start_time"]).strftime("%d.%m.%Y %H:%M"), now])
    except:
        pass

# ====== RAG ======
knowledge_cache = []
knowledge_cache_time = 0

def search_knowledge(query):
    global knowledge_cache, knowledge_cache_time
    if time.time() - knowledge_cache_time > 300 or not knowledge_cache:
        try:
            knowledge_cache = sheet_knowledge.get_all_values()[1:]
            knowledge_cache_time = time.time()
        except:
            pass
    query_lower = query.lower()
    relevant = []
    for row in knowledge_cache:
        if len(row) < 3:
            continue
        topic, keywords, answer = row[0], row[1], row[2]
        if any(kw.strip().lower() in query_lower for kw in keywords.split(",")):
            relevant.append(f"{topic}: {answer}")
    return "\n".join(relevant) if relevant else ""

# ====== SYSTEM PROMPTS ======
SYSTEM_PROMPTS = {
    "en": "You are Alex, AI support for B.SITE — CS2 case opening platform. Answer in English. Max 2-3 sentences. Never make up info. Never guarantee winnings. If unsure: 'Please check b.site or contact support.'",
    "es": "Eres Alex, soporte IA de B.SITE. Responde en español. Máximo 2-3 oraciones. Nunca inventes información.",
    "pt": "Você é Alex, suporte IA do B.SITE. Responda em português. Máximo 2-3 frases. Nunca invente informações.",
    "de": "Du bist Alex, KI-Support von B.SITE. Antworte auf Deutsch. Max 2-3 Sätze. Erfinde keine Informationen.",
    "ru": "Ты Алекс, ИИ-поддержка B.SITE. Отвечай на русском. Максимум 2-3 предложения. Никогда не придумывай информацию.",
}

FAQ_BASE = """
B.SITE — CS2 case opening platform. Website: b.site. Support: support@b.site
Games: Case Opening, Roulette (Red/Black/Gold), Hidden Mines, Case Battles, Spin Duels, Cluckin Airways
Deposit: BTC/ETH/USDT/SOL/LTC/BNB/DOGE/USDC, CS2 & Rust skins, Kinguin cards. Min $1.
Withdraw: USDT/SOL/LTC, CS2/Rust skins. Instant.
Promo: WELCOME = +3% + 3 free cases. Faucet, rakeback, leaderboard, affiliates.
Case Creator: earn 2% per open. Provably Fair. Discord: daily codes.
"""

# ====== DATA IN MEMORY ======
user_memory = {}
user_language = {}
spam_tracker = {}
active_chats = {}
pending_chats = set()
chat_history = {}
stats = {
    "total_users": set(),
    "total_messages": 0,
    "start_time": time.time()
}

# ====== ANTISPAM ======
def is_spam(user_id):
    now = time.time()
    if user_id not in spam_tracker:
        spam_tracker[user_id] = []
    spam_tracker[user_id] = [t for t in spam_tracker[user_id] if now - t < 60]
    spam_tracker[user_id].append(now)
    return len(spam_tracker[user_id]) > 10

# ====== AI WITH RAG + RATE LIMIT + CACHE ======
async def ask_ai(user_id, messages):
    lang = user_language.get(user_id, "en")
    system = SYSTEM_PROMPTS.get(lang, SYSTEM_PROMPTS["en"])
    last_query = messages[-1]["content"] if messages else ""

    # Check cache first
    cached = get_cached_answer(last_query)
    if cached:
        return cached

    relevant = search_knowledge(last_query)
    context = system + "\n\n" + (f"RELEVANT INFO:\n{relevant}" if relevant else FAQ_BASE)

    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    for model in [PRIMARY_MODEL, FALLBACK_MODEL]:
        payload = {
            "model": model,
            "messages": [{"role": "system", "content": context}] + messages,
            "max_tokens": 400,
            "temperature": 0.6
        }
        async with httpx.AsyncClient() as client:
            try:
                r = await client.post(API_URL, headers=headers, json=payload, timeout=30.0)
                data = r.json()
                if r.status_code == 200:
                    answer = data["choices"][0]["message"]["content"].strip()
                    set_cached_answer(last_query, answer)
                    return answer
                print(f"⚠️ {model} error {r.status_code}")
            except httpx.TimeoutException:
                print(f"⚠️ {model} timeout")
            except Exception as e:
                print(f"⚠️ {model} error: {e}")
    return f"⚠️ Service unavailable. Contact: {SUPPORT_USERNAME}"

# ====== ADMIN CALL ======
async def call_admins(context, user_id, user_name, last_message):
    if user_id in pending_chats or user_id in active_chats:
        return
    pending_chats.add(user_id)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✋ Take Chat", callback_data=f"take_chat_{user_id}")]])
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=f"🆘 *User needs support!*\n\n👤 {user_name}\n🆔 {user_id}\n💬 {last_message}",
                reply_markup=kb, parse_mode="Markdown"
            )
        except:
            pass

# ====== /start ======
async def start(update: Update, context):
    user_id = update.message.from_user.id
    user_memory[user_id] = []
    stats["total_users"].add(user_id)
    lang = user_language.get(user_id, "en")
    c = CONTENT[lang]
    await update.message.reply_text(c["welcome"], reply_markup=get_main_keyboard(lang), parse_mode="Markdown")

# ====== /stats ======
async def show_stats(update: Update, context):
    if update.message.from_user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Access denied.")
        return
    update_stats_sheet()
    uh = int((time.time() - stats["start_time"]) / 3600)
    um = int((time.time() - stats["start_time"]) % 3600 / 60)
    await update.message.reply_text(
        f"📊 *B.site Bot Stats:*\n\n"
        f"👥 Users: {len(stats['total_users'])}\n"
        f"💬 Messages: {stats['total_messages']}\n"
        f"💬 Active chats: {len(active_chats)}\n"
        f"🧠 AI Cache size: {len(ai_cache)}\n"
        f"⏱ Uptime: {uh}h {um}m",
        parse_mode="Markdown"
    )

# ====== /end ======
async def end_chat_command(update: Update, context):
    admin_id = update.message.from_user.id
    if admin_id not in ADMIN_IDS:
        return
    client_id = next((uid for uid, aid in active_chats.items() if aid == admin_id), None)
    if not client_id:
        await update.message.reply_text("No active chat.")
        return
    del active_chats[client_id]
    chat_history.pop(client_id, None)
    client_lang = user_language.get(client_id, "en")
    await context.bot.send_message(chat_id=client_id, text="✅ Support session ended. Good luck! 🎮", reply_markup=get_main_keyboard(client_lang))
    await update.message.reply_text("✅ Chat closed.", reply_markup=ReplyKeyboardRemove())

# ====== CALLBACKS ======
async def handle_callback(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    # Call manager button
    if data == "call_manager":
        user_name = query.from_user.first_name or "User"
        await query.edit_message_text(
            "⏳ Connecting you with a manager...\n\n"
            f"You can also reach us directly: {SUPPORT_USERNAME}"
        )
        await call_admins(context, user_id, user_name, "User requested live support via button")
        return

    # Admin takes chat
    if data.startswith("take_chat_"):
        client_id = int(data.replace("take_chat_", ""))
        admin_id = query.from_user.id
        if client_id in active_chats:
            await query.answer("❌ Already taken!", show_alert=True)
            return
        active_chats[client_id] = admin_id
        pending_chats.discard(client_id)
        for aid in ADMIN_IDS:
            try:
                await context.bot.send_message(chat_id=aid, text=f"✅ Chat {client_id} taken by @{query.from_user.username or admin_id}")
            except:
                pass
        history = chat_history.get(client_id, [])
        if history:
            await context.bot.send_message(
                chat_id=admin_id,
                text="📜 *Recent messages:*\n\n" + "\n".join(history[-10:]) + "\n\n─────────────",
                parse_mode="Markdown"
            )
        await context.bot.send_message(chat_id=client_id, text="✅ Support agent connected! How can I help? 😊")
        await query.edit_message_text(f"✅ You took chat with user {client_id}\n\nType /end to close.")
        return

# ====== MESSAGES ======
async def handle_message(update: Update, context):
    user_id = update.message.from_user.id
    user_text = update.message.text

    if is_spam(user_id):
        await update.message.reply_text("⚠️ Please slow down!")
        return

    stats["total_users"].add(user_id)
    stats["total_messages"] += 1

    if user_id not in user_memory:
        user_memory[user_id] = []

    lang = user_language.get(user_id, "en")
    c = CONTENT[lang]

    # ── Admin replies ──
    if user_id in ADMIN_IDS:
        client_id = next((uid for uid, aid in active_chats.items() if aid == user_id), None)
        if client_id:
            if user_text == "🔴 End Chat":
                del active_chats[client_id]
                chat_history.pop(client_id, None)
                client_lang = user_language.get(client_id, "en")
                await context.bot.send_message(chat_id=client_id, text="✅ Support session ended. Good luck! 🎮", reply_markup=get_main_keyboard(client_lang))
                await update.message.reply_text("✅ Chat closed.", reply_markup=ReplyKeyboardRemove())
                return
            await context.bot.send_message(chat_id=client_id, text=user_text)
            end_kb = ReplyKeyboardMarkup([["🔴 End Chat"]], resize_keyboard=True)
            await update.message.reply_text("✅", reply_markup=end_kb)
            return

    # ── User in active chat ──
    if user_id in active_chats:
        admin_id = active_chats[user_id]
        user_name = update.message.from_user.first_name or "User"
        username = f" @{update.message.from_user.username}" if update.message.from_user.username else ""
        await context.bot.send_message(chat_id=admin_id, text=f"👤 *{user_name}*{username}:\n{user_text}", parse_mode="Markdown")
        return

    # Save history
    if user_id not in chat_history:
        chat_history[user_id] = []
    chat_history[user_id].append(f"👤 {update.message.from_user.first_name or 'User'}: {user_text}")
    chat_history[user_id] = chat_history[user_id][-10:]

    # ── Language selection ──
    if user_text in LANGUAGES:
        new_lang = LANGUAGES[user_text]
        user_language[user_id] = new_lang
        user_memory[user_id] = []
        nc = CONTENT[new_lang]
        await update.message.reply_text(nc["lang_set"], reply_markup=get_main_keyboard(new_lang))
        return

    # ── Language button ──
    if user_text in ["🌍 Language", "🌍 Idioma", "🌍 Sprache", "🌍 Язык"]:
        await update.message.reply_text(c["lang_select"], reply_markup=get_language_keyboard())
        return

    # ── Cases ──
    cases_btns = {"en": "📦 Cases", "es": "📦 Casos", "pt": "📦 Cases", "de": "📦 Cases", "ru": "📦 Кейсы"}
    if user_text == cases_btns.get(lang):
        await update.message.reply_text(c["cases"], reply_markup=get_main_keyboard(lang), parse_mode="Markdown")
        return

    # ── Games — з deep link кнопками ──
    games_btns = {"en": "🎯 Games", "es": "🎯 Juegos", "pt": "🎯 Jogos", "de": "🎯 Spiele", "ru": "🎯 Игры"}
    if user_text == games_btns.get(lang):
        await update.message.reply_text(c["games"], reply_markup=get_main_keyboard(lang), parse_mode="Markdown")
        await update.message.reply_text(c["play_now"], reply_markup=get_games_inline_keyboard(), parse_mode="Markdown")
        return

    # ── Deposit ──
    deposit_btns = {"en": "💰 Deposit & Withdraw", "es": "💰 Depósito y Retiro", "pt": "💰 Depósito e Saque", "de": "💰 Einzahlung & Auszahlung", "ru": "💰 Депозит и Вывод"}
    if user_text == deposit_btns.get(lang):
        await update.message.reply_text(c["deposit"], reply_markup=get_main_keyboard(lang), parse_mode="Markdown")
        return

    # ── Bonuses ──
    bonus_btns = {"en": "🎁 Bonuses", "es": "🎁 Bonos", "pt": "🎁 Bônus", "de": "🎁 Boni", "ru": "🎁 Бонусы"}
    if user_text == bonus_btns.get(lang):
        await update.message.reply_text(c["bonuses"], reply_markup=get_main_keyboard(lang), parse_mode="Markdown")
        return

    # ── Support ──
    support_btns = {"en": "🆘 Support", "es": "🆘 Soporte", "pt": "🆘 Suporte", "de": "🆘 Support", "ru": "🆘 Поддержка"}
    if user_text == support_btns.get(lang):
        await update.message.reply_text(c["support"], reply_markup=get_main_keyboard(lang), parse_mode="Markdown")
        await update.message.reply_text("👇", reply_markup=get_support_inline_keyboard())
        return

    # ── FAQ ──
    if user_text == "❓ FAQ":
        await update.message.reply_text(c["faq"], reply_markup=get_main_keyboard(lang), parse_mode="Markdown")
        return

    # ── AI response з rate limit ──
    if not check_ai_rate_limit(user_id):
        await update.message.reply_text(c["rate_limit"])
        return

    status_msg = await update.message.reply_text(c["thinking"])
    if len(user_memory[user_id]) > 10:
        user_memory[user_id] = user_memory[user_id][-10:]
    user_memory[user_id].append({"role": "user", "content": user_text})
    answer = await ask_ai(user_id, user_memory[user_id])
    user_memory[user_id].append({"role": "assistant", "content": answer})
    await status_msg.edit_text(answer)

# ====== LAUNCH ======
if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", show_stats))
    app.add_handler(CommandHandler("end", end_chat_command))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("✅ B.site Bot launched!")
    app.run_polling()