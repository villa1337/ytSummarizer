import os
import time
import json
from datetime import datetime
from app import get_transcript, query_groq
from telegram_listener import send_telegram_summary
from helper import transcript_to_prompt, extract_video_id
import logging
import fcntl
from contextlib import contextmanager

QUEUE_PATH = os.path.join(os.path.dirname(__file__), os.getenv("QUEUE_PATH", "queue.json"))
REPORTS_DIR = os.path.join(os.path.dirname(__file__), 'reports')

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# File lock helpers
@contextmanager
def locked_file(filename, mode):
    with open(filename, mode) as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield f
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)

os.makedirs(REPORTS_DIR, exist_ok=True)

def load_queue():
    try:
        with locked_file(QUEUE_PATH, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load queue: {e}")
        return []

def save_queue(queue):
    try:
        with locked_file(QUEUE_PATH, 'w') as f:
            json.dump(queue, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save queue: {e}")

def process_url(url):
    logger.info(f"Processing URL: {url}")
    transcript = get_transcript(url)
    if not transcript:
        logger.warning(f"No transcript found for {url}")
        return False
    prompt = transcript_to_prompt(transcript)
    summary = query_groq(prompt)
    video_id = extract_video_id(url)
    if not video_id:
        logger.warning(f"Could not extract video ID from {url}")
        return False
    report = {
        'url': url,
        'summary': summary,
        'timestamp': datetime.now().isoformat(timespec='seconds')
    }
    report_path = os.path.join(REPORTS_DIR, f'{video_id}.json')
    try:
        with open(report_path, 'w') as f:
            json.dump(report, f, indent=2)
        logger.info(f"Report written: {report_path}")
    except Exception as e:
        logger.error(f"Failed to write report for {url}: {e}")
        return False
    try:
        send_telegram_summary(url, summary)
        logger.info(f"Telegram summary sent for {url}")
    except Exception as e:
        logger.error(f"Failed to send Telegram summary for {url}: {e}")
        return False
    return True

def worker_loop():
    while True:
        queue = load_queue()
        if queue:
            new_queue = []
            for url in queue:
                try:
                    success = process_url(url)
                    if not success:
                        new_queue.append(url)  # Keep failed items in queue
                except Exception as e:
                    logger.error(f'Error processing {url}: {e}')
                    new_queue.append(url)  # Keep failed items in queue
            save_queue(new_queue)
        else:
            time.sleep(10)

if __name__ == '__main__':
    worker_loop()
