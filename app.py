import os
import re
import requests
import logging
from flask import Flask, request, render_template
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound, NoTranscriptAvailable
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s")

load_dotenv()
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
def get_transcript(video_id, language):
    logging.debug(f"Fetching transcript for video ID: {video_id} with language: {language}")
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        try:
            transcript = transcript_list.find_transcript([language])
        except NoTranscriptFound:
            logging.warning(f"Transcript not found in language '{language}', falling back to 'es'")
            transcript = transcript_list.find_transcript(['es'])

        segments = transcript.fetch()
        transcript_text = " ".join([seg["text"] for seg in segments])
        logging.debug(f"Fetched transcript: {transcript_text[:100]}...")  # Log first 100 characters
        return transcript_text
    except (TranscriptsDisabled, NoTranscriptAvailable) as e:
        logging.error(f"Error fetching transcript: {str(e)}")
        return ""
    except YouTubeRequestFailed:
        return "Transcript could not be retrieved – YouTube is rate-limiting or blocking access."

# Queries OpenRouter with either a summary or user question about the transcript
def query_openrouter(transcript, user_query):
    logging.debug(f"Querying OpenRouter with user query: '{user_query}'")
    if not user_query.strip():
        prompt = f"Summarize the following YouTube video transcript:\n\n{transcript[:10000]}"
    else:
        prompt = f"Given the following transcript, answer this question: '{user_query}'\n\nTranscript:\n{transcript[:10000]}"

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    body = {
        "model": "openai/gpt-4o",
        "messages": [
        {"role": "user", "content": prompt}
        ],
        "max_tokens": 500
    }

    logging.debug(f"Sending request to OpenRouter with body: {body}")
    try:
        response = requests.post("https://openrouter.ai/api/v1/chat/completions", json=body, headers=headers)
        response.raise_for_status()
        result = response.json()["choices"][0]["message"]["content"]
        logging.debug(f"Received response from OpenRouter: {result[:100]}...")  # Log first 100 characters
        return result
    except Exception as e:
        logging.error(f"Error querying OpenRouter: {str(e)}")
        raise

@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    error = None

    if request.method == "POST":
        url = request.form["url"]
        language = request.form.get("lang", "en")
        user_query = request.form.get("query", "").strip()


        # Force User-Agent spoofing to always act like a desktop browser
        request.headers.environ['HTTP_USER_AGENT'] = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        
        logging.info(f"Received POST request with URL: {url}, language: {language}, query: {user_query}")
        video_id = extract_video_id(url)
        if video_id:
            transcript = get_transcript(video_id, language)
            if transcript:
                try:
                    result = query_openrouter(transcript, user_query)
                except Exception as e:
                    error = f"Error querying OpenRouter: {str(e)}"
                    logging.error(error)
            else:
                error = "Transcript could not be retrieved."
                logging.error(error)
        else:
            error = "Invalid YouTube URL."
            logging.error(error)

    return render_template("index.html", result=result, error=error)

if __name__ == "__main__":
    logging.info("Starting Flask app...")
    app.run(host="0.0.0.0", port=8080, debug=True)
