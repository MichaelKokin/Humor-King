import logging
import re
import os
import json
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes
)

# --- Конфигурация ---
TOKEN = os.environ.get("TOKEN", "")
DATA_FILE = "smehachi.json"
HISTORY_FILE = "smehachi_history.json"

# --- Логирование ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

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

# --- Поиск ---
def find_person(text):
    text = text.strip().lower().lstrip('@')
    for name, alias_list in aliases.items():
        if text in [a.strip().lower().lstrip('@') for a in alias_list]:
            return name
    return None

# --- Утилиты ---
def record_history(name, count):
    now = datetime.utcnow().isoformat()
    smehachi_history.setdefault(name, []).append({'count': count, 'time': now})
    save_json(HISTORY_FILE, smehachi_history)

# --- Команды ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text("Привет! Я считаю смехачи. Пиши 'даю 3 смехача Лизе', 'минус 2 Руслану' или 'плюс 5 Насте'.")

async def rating(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sorted_users = sorted(smehachi.items(), key=lambda x: x[1], reverse=True)
    text = "📊 Общий рейтинг смехачей:\n\n"
    for name, count in sorted_users:
        if name in valid_names:
            text += f"{name}: {count} смехачей\n"
    if update.message:
        await update.message.reply_text(text)

async def weekly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.utcnow()
    week_start = now - timedelta(days=now.weekday())
    weekly_scores = {name: 0 for name in valid_names}

    for name, records in smehachi_history.items():
        for r in records:
            time = datetime.fromisoformat(r['time'])
            if time >= week_start:
                weekly_scores[name] += r['count']

    sorted_users = sorted(weekly_scores.items(), key=lambda x: x[1], reverse=True)
    text = "📆 Рейтинг за эту неделю:\n\n"
    for name, count in sorted_users:
        text += f"{name}: {count} смехачей\n"
    if update.message:
        await update.message.reply_text(text)

# --- Обработка начислений и вычитаний ---
async def handle_smehachi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text
    sender = update.effective_user.first_name

    # Начисление
    match_add = re.search(r'(отдаю|даю|дарю|плюс|кидаю|держи|отсылаю)\s+(\d+)\s+смехач(?:а|ей|ейчиков)?\s+(.+)', text, re.IGNORECASE)
    if match_add:
        count = int(match_add.group(2))
        target_raw = match_add.group(3)
        recipient = find_person(target_raw)
        if recipient and recipient != sender and recipient in valid_names:
            smehachi[recipient] = smehachi.get(recipient, 0) + count
            save_json(DATA_FILE, smehachi)
            record_history(recipient, count)
            if update.message:
                await update.message.reply_text(f"{recipient} получил {count} смехачей! 🎉")
        return

    # Вычитание
    match_sub = re.search(r'(минус|забираю|вылетает|забрать)\s+(\d+)\s+смехач(?:а|ей|ейчиков)?(?:\s+у)?\s+(.+)', text, re.IGNORECASE)
    if match_sub:
        count = int(match_sub.group(2))
        target_raw = match_sub.group(3)
        recipient = find_person(target_raw)
        if recipient and recipient in valid_names:
            smehachi[recipient] = smehachi.get(recipient, 0) - count
            save_json(DATA_FILE, smehachi)
            record_history(recipient, -count)
            if update.message:
                await update.message.reply_text(f"{recipient} лишился {count} смехачей! 😬")
        return

# --- Запуск ---
def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("rating", rating))
    app.add_handler(CommandHandler("weekly", weekly))
    app.add_handler(MessageHandler(filters.TEXT, handle_smehachi))

    app.run_polling()

if __name__ == '__main__':
    main()
