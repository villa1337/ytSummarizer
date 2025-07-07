# telegram_listener.py
import json
import logging
import re
import os
from pathlib import Path
from telegram.ext import Updater, MessageHandler, Filters
from telegram import Bot

# === CONFIG ===
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
QUEUE_PATH = Path(os.getenv("QUEUE_PATH", "queue.json"))
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

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

def send_telegram_summary(url, summary, chat_id=None):
    """
    Send a summary message to a Telegram chat.
    If chat_id is not provided, uses TELEGRAM_CHAT_ID from config.
    """
    if chat_id is None:
        chat_id = TELEGRAM_CHAT_ID
    if not chat_id:
        logger.error("TELEGRAM_CHAT_ID is not set. Cannot send summary.")
        return
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    text = f"Summary for {url}:\n\n{summary}"
    try:
        bot.send_message(chat_id=chat_id, text=text)
        logger.info(f"✅ Sent summary to chat {chat_id}")
    except Exception as e:
        logger.error(f"❌ Failed to send summary: {e}")

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

__all__ = ["send_telegram_summary", "add_to_queue"]