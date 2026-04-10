import logging
import re
import os
import json
from datetime import datetime, timedelta
from anthropic import AsyncAnthropic
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes
)

# --- Конфигурация ---
TOKEN = os.environ.get("TOKEN", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# Файлы хранятся в /data если есть volume, иначе рядом
DATA_DIR = "/data" if os.path.exists("/data") else "."
DATA_FILE = os.path.join(DATA_DIR, "smehachi.json")
HISTORY_FILE = os.path.join(DATA_DIR, "smehachi_history.json")

MODEL = "claude-haiku-4-5-20251001"

# --- Логирование ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Участники ---
valid_names = ['Лиза', 'Руслан', 'Миша', 'Настя']

aliases = {
    'Лиза': ['лиза', 'лизе', 'лизу', 'лизы', 'лизой', 'лисочка', 'лизочка', 'для лизы', '@karandashiki'],
    'Руслан': ['руслан', 'руслану', 'руслана', 'русла́н', 'русланом', 'для руслана', '@ruslanzaydullin'],
    'Миша': ['миша', 'мише', 'мишу', 'миши', 'михаил', 'михаилу', 'михаила', 'михаилом',
             'мииша', 'мишаил', 'для миши', 'мужу', 'michael', '@michaelkokin'],
    'Настя': ['настя', 'насте', 'настю', 'настии', 'насти', 'настей', 'анастасия', 'анастасии',
              'анастасией', 'настёна', 'настеночка', 'настюша', 'для насти', 'nastya', '@mymichelleobama']
}

# Telegram username → имя
telegram_to_name = {
    'karandashiki': 'Лиза',
    'ruslanzaydullin': 'Руслан',
    'michaelkokin': 'Миша',
    'mymichelleobama': 'Настя',
}

# --- Клиент Anthropic ---
anthropic_client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

# --- Загрузка / сохранение ---
def load_json(path):
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

smehachi = load_json(DATA_FILE)
smehachi_history = load_json(HISTORY_FILE)

# --- Поиск имени ---
def find_person(text):
    text = text.strip().lower().lstrip('@')
    for name, alias_list in aliases.items():
        if text in [a.strip().lower().lstrip('@') for a in alias_list]:
            return name
    return None

def sender_name_from_update(update: Update) -> str:
    user = update.effective_user
    if not user:
        return "Неизвестный"
    username = (user.username or "").lower()
    if username in telegram_to_name:
        return telegram_to_name[username]
    return user.first_name or "Неизвестный"

# --- История ---
def record_history(name, count):
    now = datetime.utcnow().isoformat()
    smehachi_history.setdefault(name, []).append({'count': count, 'time': now})
    save_json(HISTORY_FILE, smehachi_history)

def add_smehachi(name: str, count: int):
    smehachi[name] = smehachi.get(name, 0) + count
    save_json(DATA_FILE, smehachi)
    record_history(name, count)

# --- AI оценка шутки ---
async def ai_evaluate(text: str, sender: str) -> dict | None:
    """Haiku оценивает шутку. Возвращает dict или None если не смешно."""
    if not anthropic_client:
        return None
    if len(text.strip()) < 8:
        return None

    prompt = f"""Ты — судья юмора в групповом чате друзей. Участники: Лиза, Руслан, Миша, Настя.
Сообщение от {sender}: «{text}»

Оцени: это смешное сообщение (шутка, каламбур, мем, забавная история, остроумный ответ)?
Отвечай ТОЛЬКО в формате JSON, без объяснений:

Если смешно:
{{"funny": true, "smehachi": <число от 1 до 5>, "comment": "<короткий смешной комментарий на русском, 1 предложение>"}}

Если не смешно:
{{"funny": false}}

Критерии: 1 смехач — слабо, 3 — хорошо, 5 — шедевр. Будь строгим, не каждое сообщение смешное."""

    try:
        response = await anthropic_client.messages.create(
            model=MODEL,
            max_tokens=120,
            messages=[{"role": "user", "content": prompt}]
        )
        result = json.loads(response.content[0].text.strip())
        if result.get("funny"):
            return result
    except Exception as e:
        logger.error(f"AI eval error: {e}")
    return None

# --- Команды ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        ai_status = "✅ Haiku включён — сам оценивает шутки!" if anthropic_client else "❌ AI не настроен (нет ANTHROPIC_API_KEY)"
        await update.message.reply_text(
            f"Привет! 😄 Я считаю смехачи.\n\n"
            f"{ai_status}\n\n"
            f"Можно вручную:\n"
            f"• «даю 3 смехача Лизе»\n"
            f"• «минус 2 Руслану»\n\n"
            f"Команды: /rating /weekly /stats"
        )

async def rating(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    total = sum(smehachi.get(n, 0) for n in valid_names)
    sorted_users = sorted(
        [(n, smehachi.get(n, 0)) for n in valid_names],
        key=lambda x: x[1], reverse=True
    )
    medals = ['🥇', '🥈', '🥉', '😐']
    text = "📊 Рейтинг смехачей:\n\n"
    for i, (name, count) in enumerate(sorted_users):
        bar = '█' * min(count // 5, 10) if count > 0 else '░'
        text += f"{medals[i]} {name}: {count} смехачей {bar}\n"
    text += f"\nВсего раздано: {total} 😂"
    await update.message.reply_text(text)

async def weekly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    now = datetime.utcnow()
    week_start = now - timedelta(days=now.weekday())
    weekly_scores = {name: 0 for name in valid_names}
    for name, records in smehachi_history.items():
        for r in records:
            t = datetime.fromisoformat(r['time'])
            if t >= week_start:
                weekly_scores[name] = weekly_scores.get(name, 0) + r['count']
    sorted_users = sorted(weekly_scores.items(), key=lambda x: x[1], reverse=True)
    text = "📆 Эта неделя:\n\n"
    for name, count in sorted_users:
        text += f"{name}: {count} смехачей\n"
    await update.message.reply_text(text)

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Статистика по каждому участнику."""
    if not update.message:
        return
    text = "📈 Подробная статистика:\n\n"
    for name in valid_names:
        records = smehachi_history.get(name, [])
        total = smehachi.get(name, 0)
        given = sum(r['count'] for r in records if r['count'] > 0)
        taken = sum(abs(r['count']) for r in records if r['count'] < 0)
        text += f"**{name}**: {total} смехачей (получено: +{given}, снято: -{taken})\n"
    await update.message.reply_text(text)

# --- Обработка сообщений ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text
    sender = sender_name_from_update(update)

    # 1. Проверяем ручное начисление
    match_add = re.search(
        r'(отдаю|даю|дарю|плюс|кидаю|держи|отсылаю)\s+(\d+)\s+смехач(?:а|ей|ейчиков)?\s+(.+)',
        text, re.IGNORECASE
    )
    if match_add:
        count = int(match_add.group(2))
        recipient = find_person(match_add.group(3))
        if recipient and recipient in valid_names:
            add_smehachi(recipient, count)
            await update.message.reply_text(f"🎉 {recipient} получает {count} смехачей!")
        return

    # 2. Проверяем ручное вычитание
    match_sub = re.search(
        r'(минус|забираю|вылетает|забрать)\s+(\d+)\s+смехач(?:а|ей|ейчиков)?(?:\s+у)?\s+(.+)',
        text, re.IGNORECASE
    )
    if match_sub:
        count = int(match_sub.group(2))
        recipient = find_person(match_sub.group(3))
        if recipient and recipient in valid_names:
            add_smehachi(recipient, -count)
            await update.message.reply_text(f"😬 {recipient} лишается {count} смехачей!")
        return

    # 3. AI оценка — только если отправитель участник и не команда
    if text.startswith('/'):
        return
    if sender not in valid_names:
        return

    result = await ai_evaluate(text, sender)
    if result:
        count = result.get("smehachi", 1)
        comment = result.get("comment", "")
        add_smehachi(sender, count)

        emoji = {1: '😄', 2: '😄', 3: '😂', 4: '🤣', 5: '💀'}.get(count, '😄')
        reply = f"{emoji} +{count} смехач{'а' if count in [2,3,4] else 'ей'} {sender}у!\n{comment}"
        await update.message.reply_text(reply)

# --- Запуск ---
def main():
    if not TOKEN:
        raise ValueError("TOKEN env var is required")

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("rating", rating))
    app.add_handler(CommandHandler("weekly", weekly))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()

if __name__ == '__main__':
    main()
