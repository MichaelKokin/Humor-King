import logging
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

DATA_DIR = "/data" if os.path.exists("/data") else "."
DATA_FILE = os.path.join(DATA_DIR, "smehachi.json")
HISTORY_FILE = os.path.join(DATA_DIR, "smehachi_history.json")

MODEL = "claude-haiku-4-5-20251001"

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

anthropic_client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

# --- Хранилище ---
def load_json(path):
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

smehachi = load_json(DATA_FILE)       # {"Лиза": 10, "Руслан": 5, ...}
smehachi_history = load_json(HISTORY_FILE)

# --- Утилиты ---
def get_display_name(user) -> str:
    """Имя пользователя для отображения."""
    return user.first_name or user.username or str(user.id)

def add_smehachi(name: str, count: int):
    smehachi[name] = smehachi.get(name, 0) + count
    smehachi_history.setdefault(name, []).append({
        "count": count,
        "time": datetime.utcnow().isoformat()
    })
    save_json(DATA_FILE, smehachi)
    save_json(HISTORY_FILE, smehachi_history)

def get_known_names() -> list[str]:
    """Все участники, у кого есть хоть один смехач в истории."""
    return list(smehachi.keys())

# --- AI оценка шутки ---
async def ai_evaluate(text: str, sender: str) -> dict | None:
    """Haiku оценивает шутку. Возвращает dict или None."""
    if not anthropic_client or len(text.strip()) < 8:
        return None

    prompt = f"""Ты — судья юмора в групповом чате друзей.
Сообщение от {sender}: «{text}»

Это смешное сообщение? (шутка, каламбур, мем, остроумный ответ, забавная история)
Отвечай ТОЛЬКО в формате JSON:

Если смешно:
{{"funny": true, "smehachi": <1-5>, "comment": "<короткий смешной комментарий, 1 предложение>"}}

Если не смешно:
{{"funny": false}}

Критерии: 1 — слабо, 3 — хорошо, 5 — шедевр. Будь строгим — не каждое сообщение смешное."""

    try:
        response = await anthropic_client.messages.create(
            model=MODEL,
            max_tokens=120,
            messages=[{"role": "user", "content": prompt}]
        )
        result = json.loads(response.content[0].text.strip())
        return result if result.get("funny") else None
    except Exception as e:
        logger.error(f"AI eval error: {e}")
    return None

# --- AI парсинг ручных команд ---
async def ai_parse_command(text: str, known_names: list[str]) -> dict | None:
    """Haiku парсит ручное начисление/вычитание из текста."""
    if not anthropic_client:
        return None

    names_str = ", ".join(known_names) if known_names else "неизвестно"
    prompt = f"""В сообщении могут быть команды для начисления/вычитания смехачей.
Известные участники чата: {names_str}

Сообщение: «{text}»

Если это команда начисления или вычитания смехачей — ответь JSON:
{{"action": "add" или "remove", "count": <число>, "target": "<имя из списка участников>"}}

Если это НЕ команда — ответь:
{{"action": null}}

Только JSON, без объяснений."""

    try:
        response = await anthropic_client.messages.create(
            model=MODEL,
            max_tokens=80,
            messages=[{"role": "user", "content": prompt}]
        )
        result = json.loads(response.content[0].text.strip())
        if result.get("action") and result.get("target") and result.get("count"):
            return result
    except Exception as e:
        logger.error(f"AI parse error: {e}")
    return None

# --- Команды ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    ai_status = "✅ Haiku включён — сам оценивает шутки" if anthropic_client else "❌ AI не настроен"
    await update.message.reply_text(
        f"Привет! 😄 Считаю смехачи в этом чате.\n\n"
        f"{ai_status}\n\n"
        f"Пишите в чате — бот сам разберётся кто шутит!\n"
        f"Или вручную: «дай 3 смехача [имя]», «минус 2 [имя]»\n\n"
        f"/rating — рейтинг\n/weekly — за неделю\n/stats — подробно"
    )

async def rating(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not smehachi:
        await update.message.reply_text("Пока никто не набрал смехачей 😶")
        return
    sorted_users = sorted(smehachi.items(), key=lambda x: x[1], reverse=True)
    medals = ['🥇', '🥈', '🥉'] + ['😐'] * 20
    text = "📊 Рейтинг смехачей:\n\n"
    for i, (name, count) in enumerate(sorted_users):
        bar = '█' * min(count // 5, 10) if count > 0 else '░'
        text += f"{medals[i]} {name}: {count} {bar}\n"
    text += f"\nВсего: {sum(smehachi.values())} 😂"
    await update.message.reply_text(text)

async def weekly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    now = datetime.utcnow()
    week_start = now - timedelta(days=now.weekday())
    weekly_scores = {}
    for name, records in smehachi_history.items():
        total = sum(r['count'] for r in records if datetime.fromisoformat(r['time']) >= week_start)
        if total != 0:
            weekly_scores[name] = total
    if not weekly_scores:
        await update.message.reply_text("На этой неделе тихо 😴")
        return
    sorted_users = sorted(weekly_scores.items(), key=lambda x: x[1], reverse=True)
    text = "📆 Эта неделя:\n\n"
    for name, count in sorted_users:
        sign = "+" if count > 0 else ""
        text += f"{name}: {sign}{count}\n"
    await update.message.reply_text(text)

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not smehachi:
        await update.message.reply_text("Пока пусто 🤷")
        return
    text = "📈 Подробная статистика:\n\n"
    for name, total in sorted(smehachi.items(), key=lambda x: x[1], reverse=True):
        records = smehachi_history.get(name, [])
        given = sum(r['count'] for r in records if r['count'] > 0)
        taken = sum(abs(r['count']) for r in records if r['count'] < 0)
        text += f"**{name}**: {total} (получено +{given}, снято -{taken})\n"
    await update.message.reply_text(text)

# --- Основной обработчик ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text
    if text.startswith('/'):
        return

    sender = get_display_name(update.effective_user)
    known_names = get_known_names()

    # 1. Проверяем: может это ручная команда начисления?
    cmd = await ai_parse_command(text, known_names)
    if cmd and cmd.get("action"):
        target = cmd["target"]
        count = int(cmd["count"])
        if cmd["action"] == "add":
            add_smehachi(target, count)
            await update.message.reply_text(f"🎉 {target} получает {count} смехачей!")
        elif cmd["action"] == "remove":
            add_smehachi(target, -count)
            await update.message.reply_text(f"😬 {target} лишается {count} смехачей!")
        return

    # 2. AI оценка шутки от отправителя
    result = await ai_evaluate(text, sender)
    if result:
        count = result.get("smehachi", 1)
        comment = result.get("comment", "")
        add_smehachi(sender, count)
        emoji = {1: '😄', 2: '😄', 3: '😂', 4: '🤣', 5: '💀'}.get(count, '😄')
        ending = 'а' if count in [2, 3, 4] else 'ей'
        await update.message.reply_text(
            f"{emoji} +{count} смехач{ending} {sender}у!\n{comment}"
        )

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
