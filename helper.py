import re


def transcript_to_prompt(transcript, user_query=None):
    """
    Convert a transcript (list of dicts with 'text') into a prompt string for the LLM.
    If user_query is provided, ask that question; otherwise, request a summary.
    """
    if not transcript:
        return None
    transcript_text = "\n".join([seg["text"] for seg in transcript])
    if user_query and user_query.strip():
        prompt = f"Given the following transcript, answer this question: '{user_query.strip()}'\n\nTranscript:\n{transcript_text[:10000]}"
    else:
        prompt = f"Summarize the following YouTube video transcript (leave out any advertisements that are made):\n\n{transcript_text[:10000]}"
    return prompt


def extract_video_id(url):
    """
    Extracts the YouTube video ID from a URL.
    """
    match = re.search(r"(?:v=|\/|youtu\.be\/|embed\/)([a-zA-Z0-9_-]{11})", url)
    video_id = match.group(1) if match else None
    return video_id
