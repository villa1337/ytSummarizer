# telegram_listener.py
import json
import logging
import re
from pathlib import Path
from telegram.ext import Updater, MessageHandler, Filters

# === CONFIG ===
TELEGRAM_BOT_TOKEN = "7691691528:AAHqM3apFFOxVnoiqslIg1wH31GStFf5HDQ"
QUEUE_PATH = Path("queue.json")

# === Setup logging ===
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === Helpers ===
def add_to_queue(url):
    queue = []
    if QUEUE_PATH.exists():
        with open(QUEUE_PATH) as f:
            queue = json.load(f)

    if url not in queue:
        queue.append(url)
        with open(QUEUE_PATH, "w") as f:
            json.dump(queue, f, indent=2)
        logger.info(f"✅ Queued: {url}")
        return True
    else:
        logger.info("ℹ️ URL already in queue.")
        return False

# === Telegram Handler ===
def handle_message(update, context):
    text = update.message.text
    urls = re.findall(r'(https?://[^\s]+)', text)
    logger.info(f"📨 New message: {text}")
    if urls:
        for url in urls:
            logger.info(f"🔗 URL received: {url}")
            if add_to_queue(url):
                update.message.reply_text("✅ Queued for summarization.")
            else:
                update.message.reply_text("ℹ️ Already in queue.")
    else:
        update.message.reply_text("⚠️ No URL detected.")

# === Main ===
def main():
    updater = Updater(token=TELEGRAM_BOT_TOKEN, use_context=True)
    dispatcher = updater.dispatcher

    handler = MessageHandler(Filters.text & ~Filters.command, handle_message)
    dispatcher.add_handler(handler)

    logger.info("🤖 Telegram bot is listening...")
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()