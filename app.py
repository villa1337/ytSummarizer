import os
import re
import requests
import logging
import subprocess
import json
import time
from flask import Flask, request, render_template
from yt_dlp import YoutubeDL

# Configure logging
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s")

app = Flask(__name__)

API_KEY = os.getenv("OPENROUTER_API_KEY")
groq_api_key = os.getenv("GROQ_API_KEY", "")

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
    ydl_opts = {
        'skip_download': True,
        'writesubtitles': True,
        'subtitlesformat': 'json3',
        'subtitleslangs': [language],
        'quiet': True,
        'no_warnings': True,
        'cookiefile': os.path.join(os.path.dirname(__file__), 'cookies.txt'),  # Use relative path
    }
    with YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(video_url, download=False)
        except Exception as e:
            print(f"yt-dlp extraction error: {e}")
            # Fallback to Whisper
            return transcribe_with_whisper(video_url)
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
                # Fallback to Whisper
                return transcribe_with_whisper(video_url)
        formats = subtitles[language]
        json3_url = next((f['url'] for f in formats if f['ext'] == 'json3'), None)
        if not json3_url:
            print("Could not find JSON3 subtitle format")
            # Fallback to Whisper
            return transcribe_with_whisper(video_url)
        response = requests.get(json3_url)
        # Check for redirect to consent or login page
        if "consent.youtube.com" in response.url or "signin" in response.url:
            print("❌ YouTube is requesting login or CAPTCHA.")
            # Fallback to Whisper
            return transcribe_with_whisper(video_url)
        if response.status_code != 200:
            print("Failed to fetch transcript JSON3")
            # Fallback to Whisper
            return transcribe_with_whisper(video_url)
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

# Helper: fallback to Whisper transcription
def transcribe_with_whisper(video_url):
    """
    Downloads audio using yt-dlp, transcribes with whisper, and returns transcript segments.
    """
    import tempfile
    import shutil
    import whisper
    logging.info("Falling back to Whisper transcription...")
    # Make temp dir for audio
    temp_dir = tempfile.mkdtemp()
    audio_path = os.path.join(temp_dir, "audio.mp3")
    try:
        # Download audio using yt-dlp
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': audio_path,
            'quiet': True,
            'no_warnings': True,
            'cookiefile': os.path.join(os.path.dirname(__file__), 'cookies.txt'),
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
        }
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
        # Transcribe with whisper
        model = whisper.load_model("base")
        result = model.transcribe(audio_path)
        segments = []
        for seg in result.get("segments", []):
            segments.append({
                "start": seg["start"],
                "duration": seg["end"] - seg["start"],
                "text": seg["text"].strip()
            })
        if not segments and "text" in result:
            # fallback: whole text as one segment
            segments.append({
                "start": 0.0,
                "duration": 0.0,
                "text": result["text"].strip()
            })
        return segments
    except Exception as e:
        logging.error(f"Whisper transcription failed: {e}")
        return None
    finally:
        try:
            shutil.rmtree(temp_dir)
        except Exception:
            pass

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
                transcript_text = "\n".join([seg["text"] for seg in transcript])
                if not user_query.strip():
                    prompt = f"Summarize the following YouTube video transcript (leave out any advertisements that are made):\n\n{transcript_text[:10000]}"
                else:
                    prompt = f"Given the following transcript, answer this question: '{user_query}'\n\nTranscript:\n{transcript_text[:10000]}"
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

if __name__ == "__main__":
    logging.info("Starting Flask app...")
    app.run(host="0.0.0.0", port=8000, debug=True)
