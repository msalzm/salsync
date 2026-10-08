import json

from ollama import chat


def extract_track_hint(video_title, uploader):
    response = chat(
        model="ministral-3:8b",
        messages=[
            {
                "role": "system",
                "content": (
                    "Extract the song title and artist from a YouTube video. "
                    "The uploader may not be the artist. "
                    "Get the name of the ep or album of the where the song is first released. "
                    "Use null when the text does not provide enough evidence. "
                    "Return JSON."
                ),
            },
            {
                "role": "user",
                "content": f"Video title: {video_title}\nUploader: {uploader}",
            },
        ],
        format={
            "type": "object",
            "properties": {
                "artist": {"type": ["string", "null"]},
                "title": {"type": ["string", "null"]},
                "ep_or_album": {"type": ["string", "null"]},
            },
            "required": ["artist", "title", "ep_or_album"],
            "additionalProperties": False,
        },
        options={"temperature": 0},
    )

    return json.loads(response.message.content)