import os
import re
import requests
import logging
import subprocess
import json
from flask import Flask, request, render_template

# Configure logging
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s")

app = Flask(__name__)

API_KEY = os.getenv("OPENROUTER_API_KEY")

# Extracts video ID from a YouTube URL
def extract_video_id(url):
    logging.debug(f"Extracting video ID from URL: {url}")
    # Updated regex to handle more YouTube URL formats
    match = re.search(r"(?:v=|\/|youtu\.be\/|embed\/)([a-zA-Z0-9_-]{11})", url)
    video_id = match.group(1) if match else None
    logging.debug(f"Extracted video ID: {video_id}")
    return video_id

# Attempts to fetch transcript in the selected language, defaults to 'es' if 'en' not found
def get_transcript(video_url, language='en'):
    result = subprocess.run(
        [
            'yt-dlp',
            '--skip-download',
            '--sub-lang', language,
            '--sub-format', 'json3',
            '--print-json',
            video_url
        ],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        print("Error running yt-dlp:\n", result.stderr)
        return None

    try:
        video_info = json.loads(result.stdout)
    except json.JSONDecodeError:
        print("Failed to parse yt-dlp output.")
        return None

    # Try both 'subtitles' and 'automatic_captions'
    subtitles = video_info.get('subtitles') or video_info.get('automatic_captions', {})
    available_langs = list(subtitles.keys())

    if language not in subtitles:
        print(f"WARNING: No subtitles found for language '{language}'")
        if available_langs:
            fallback_lang = available_langs[0]
            print(f"⚠️  Falling back to: {fallback_lang}")
            language = fallback_lang
        else:
            print("❌ No subtitles available at all.")
            return None

    formats = subtitles[language]
    json3_url = next((f['url'] for f in formats if f['ext'] == 'json3'), None)
    if not json3_url:
        print("Could not find JSON3 subtitle format")
        return None

    response = requests.get(json3_url)
    if response.status_code != 200:
        print("Failed to fetch transcript JSON3")
        return None

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

# Queries OpenRouter with either a summary or user question about the transcript
def query_openrouter(transcript, user_query):
    logging.debug(f"Querying OpenRouter with user query: '{user_query}'")
    if not user_query.strip():
        prompt = f"Summarize the following YouTube video transcript (leave out any advertisements that are made):\n\n{transcript[:10000]}"
    else:
        prompt = f"Given the following transcript, answer this question: '{user_query}'\n\nTranscript:\n{transcript[:10000]}"

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    body = {
        "model": "mistralai/mistral-7b-instruct:free",
        "messages": [
        {"role": "user", "content": prompt}
        ],
        "max_tokens": 666
    }

    logging.debug(f"Sending request to OpenRouter with body: {body}")
    try:
        response = requests.post("https://openrouter.ai/api/v1/chat/completions", json=body, headers=headers)
        response.raise_for_status()
        logging.debug(f"Full response from OpenRouter: {response.json()}")
        result = response.json()["choices"][0]["message"]["content"]
        logging.debug(f"Received response from OpenRouter: {result[:100]}...")  # Log first 100 characters
        return result
    except Exception as e:
        logging.error(f"Error querying OpenRouter: {str(e)}")
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
                result = query_openrouter(transcript, user_query)
            except Exception as e:
                error = f"Error querying OpenRouter: {str(e)}"
                logging.error(error)
        else:
            error = "Transcript could not be retrieved."
            logging.error(error)

        if is_json_request():
            return {"result": result, "error": error}

    if is_json_request():
        return {"result": None, "error": "Only POST method allowed for JSON requests."}

    return render_template("index.html", result=result, error=error)

if __name__ == "__main__":
    logging.info("Starting Flask app...")
    app.run(host="0.0.0.0", port=8080, debug=True)
