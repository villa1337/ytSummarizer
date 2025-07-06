import os
import re
import requests
import logging
import subprocess
import json
import time
import glob
from flask import Flask, request, render_template, send_from_directory, redirect, url_for, flash
from yt_dlp import YoutubeDL
from helper import transcript_to_prompt

# Configure logging
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s")

app = Flask(__name__)

groq_api_key = os.getenv("GROQ_API_KEY", "")
REPORTS_DIR = os.path.join(os.path.dirname(__file__), 'reports')
os.makedirs(REPORTS_DIR, exist_ok=True)

# Attempts to fetch transcript in the selected language, defaults to 'es' if 'en' not found
def get_transcript(video_url, language='en'):
    ydl_opts = {
        'skip_download': True,
        'writesubtitles': True,
        'subtitlesformat': 'json3',
        'subtitleslangs': [language],
        'quiet': True,
        'no_warnings': True,
    }
    with YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(video_url, download=False)
        except Exception as e:
            print(f"yt-dlp extraction error: {e}")
            return None  # No fallback to Whisper
        subtitles = info.get('subtitles') or info.get('automatic_captions', {})
        available_langs = list(subtitles.keys())
        if language not in subtitles:
            print(f"WARNING: No subtitles found for language '{language}'")
            if available_langs:
                fallback_lang = available_langs[0]
                print(f"⚠️  Falling back to: {fallback_lang}")
                language = fallback_lang
            else:
                print("❌ No subtitles available at all.")
                return None  # No fallback to Whisper
        formats = subtitles[language]
        json3_url = next((f['url'] for f in formats if f['ext'] == 'json3'), None)
        if not json3_url:
            print("Could not find JSON3 subtitle format")
            return None  # No fallback to Whisper
        response = requests.get(json3_url)
        # Check for redirect to consent or login page
        if "consent.youtube.com" in response.url or "signin" in response.url:
            print("❌ YouTube is requesting login or CAPTCHA.")
            return None  # No fallback to Whisper
        if response.status_code != 200:
            print("Failed to fetch transcript JSON3")
            return None  # No fallback to Whisper
        data = response.json()
        transcript = []
        for event in data.get('events', []):
            if 'segs' in event:
                start = event.get('tStartMs', 0) / 1000.0
                duration = event.get('dDurationMs', 0) / 1000.0
                text = ''.join(seg.get('utf8', '') for seg in event['segs']).strip()
                if text:
                    transcript.append({
                        'start': start,
                        'duration': duration,
                        'text': text
                    })
        return transcript

# GROQ integration
def query_groq(prompt: str, model="llama3-70b-8192") -> str:
    print(f"Querying Groq with key: {groq_api_key} and model: {model}")
    headers = {
        "Authorization": f"Bearer {groq_api_key}",
        "Content-Type": "application/json",
        "User-Agent": "fractal-knowledge-explorer/1.0"
    }
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 2500
    }
    time.sleep(1)  # Delay to reduce risk of rate limiting
    try:
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            json=body,
            headers=headers
        )
        response.raise_for_status()
        print(f"✅ GROQ raw response: {response.text}")
        try:
            return response.json()["choices"][0]["message"]["content"]
        except json.JSONDecodeError as json_err:
            print(f"❌ JSONDecodeError: {json_err}")
            print(f"⚠️ Raw response text: {response.text}")
            raise
    except requests.exceptions.HTTPError as http_err:
        print(f"❌ GROQ HTTP error occurred: {http_err}")
        if response.status_code == 429 and model != "llama3-70b-8192":
            print("🔁 Retrying with fallback model...")
            return query_groq(prompt, model="llama3-13b-4096")
        raise
    except requests.exceptions.RequestException as req_err:
        print(f"❌ RequestException occurred: {req_err}")
        raise
    except Exception as e:
        print(f"❌ An unexpected error occurred: {e}")
        raise

def is_json_request():
    return request.headers.get("Accept") == "application/json" or request.is_json

@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    error = None

    if request.method == "POST":
        url = request.form.get("url") or (request.json and request.json.get("url"))
        language = request.form.get("lang", "en") if request.form else request.json.get("lang", "en")
        user_query = request.form.get("query", "").strip() if request.form else request.json.get("query", "").strip()

        request.headers.user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

        logging.info(f"Received POST request with URL: {url}, language: {language}, query: {user_query}")
        # Use the new approach: pass the full URL to get_transcript
        transcript = get_transcript(url, language)
        if transcript:
            try:
                prompt = transcript_to_prompt(transcript, user_query)
                result = query_groq(prompt)
            except Exception as e:
                error = f"Error querying Groq: {str(e)}"
                logging.error(error)
        else:
            error = "Transcript could not be retrieved."
            logging.error(error)

        if is_json_request():
            return {"result": result, "error": error}

    if is_json_request():
        return {"result": None, "error": "Only POST method allowed for JSON requests."}

    return render_template("index.html", result=result, error=error)

@app.route("/reports", methods=["GET", "POST"])
def reports():
    error = None
    deleted = None
    if request.method == "POST":
        # Delete selected reports
        to_delete = request.form.getlist("delete")
        for fname in to_delete:
            fpath = os.path.join(REPORTS_DIR, fname)
            if os.path.exists(fpath):
                os.remove(fpath)
        deleted = to_delete
    # List all reports
    report_files = sorted(glob.glob(os.path.join(REPORTS_DIR, '*.json')))
    reports = []
    for f in report_files:
        try:
            with open(f) as jf:
                data = json.load(jf)
            video_id = os.path.splitext(os.path.basename(f))[0]
            # Try to get title and thumbnail
            title = video_id
            thumbnail = f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"
            url = data.get('url', '')
            summary = data.get('summary', '')
            timestamp = data.get('timestamp', '')
            reports.append({
                'filename': os.path.basename(f),
                'video_id': video_id,
                'title': title,
                'thumbnail': thumbnail,
                'url': url,
                'summary': summary,
                'timestamp': timestamp
            })
        except Exception as e:
            continue
    return render_template("reports.html", reports=reports, deleted=deleted, error=error)

if __name__ == "__main__":
    logging.info("Starting Flask app...")
    app.run(host="0.0.0.0", port=8000, debug=True)
