import os
import time
import json
from datetime import datetime
from app import get_transcript, query_groq
from telegram_listener import send_telegram_summary
from helper import transcript_to_prompt, extract_video_id

QUEUE_PATH = os.path.join(os.path.dirname(__file__), os.getenv("QUEUE_PATH", "queue.json"))
REPORTS_DIR = os.path.join(os.path.dirname(__file__), 'reports')

os.makedirs(REPORTS_DIR, exist_ok=True)

def load_queue():
    with open(QUEUE_PATH, 'r') as f:
        return json.load(f)

def save_queue(queue):
    with open(QUEUE_PATH, 'w') as f:
        json.dump(queue, f, indent=2)

def process_url(url):
    transcript = get_transcript(url)
    if not transcript:
        print(f"No transcript found for {url}")
        return
    prompt = transcript_to_prompt(transcript)
    summary = query_groq(prompt)
    # Use extract_video_id to get a safe filename
    video_id = extract_video_id(url)
    if not video_id:
        print(f"Could not extract video ID from {url}")
        return
    report = {
        'url': url,
        'summary': summary,
        'timestamp': datetime.now().isoformat(timespec='seconds')
    }
    report_path = os.path.join(REPORTS_DIR, f'{video_id}.json')
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2)
    send_telegram_summary(url, summary)

def worker_loop():
    while True:
        queue = load_queue()
        if queue:
            url = queue.pop(0)
            try:
                process_url(url)
            except Exception as e:
                print(f'Error processing {url}: {e}')
            save_queue(queue)
        time.sleep(10)

if __name__ == '__main__':
    worker_loop()
