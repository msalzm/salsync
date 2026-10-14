import json

from ollama import chat


def extract_hint(content):
    response = chat(
        model="ministral-3:8b",
        messages=[
            {
                "role": "system",
                "content": (
                    "Extract the song title and artist from the supplied video text or filename. "
                    "For text in the form 'Artist - Song Title', use the credited artist "
                    "before the separator and the song title after it. "
                    "The uploader may be a label or curator: a different uploader does not "
                    "invalidate an artist explicitly named in the video title. "
                    "Ignore track numbers, file extensions, video quality labels and "
                    "bracketed catalog codes such as [LABEL123]. Preserve remix/version names. "
                    "Return a JSON object with exactly the keys 'artist' and 'title'. "
                    "Extract each field independently. Use JSON null only when the supplied "
                    "text lacks evidence for that field; never return the string 'null'. "
                    'For example, Example Artist - Example Song [LABEL123] becomes '
                    '{"artist": "Example Artist", "title": "Example Song"}.'
                ),
            },
            {
                "role": "user",
                "content": content,
            },
        ],
        format={
            "type": "object",
            "properties": {
                "artist": {"type": ["string", "null"]},
                "title": {"type": ["string", "null"]},
            },
            "required": ["artist", "title"],
            "additionalProperties": False,
        },
        options={"temperature": 0},
    )

    hint = json.loads(response.message.content)
    return {field: normalize_hint_field(hint.get(field)) for field in ("artist", "title")}


def normalize_hint_field(value):
    """Treat a model's quoted null as missing evidence, not a search term."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if value and value.casefold() != "null" else None


def extract_track_hint(video_title, uploader):
    return extract_hint(f"Video title: {video_title}\nUploader: {uploader}")


def extract_filename_hint(filename):
    return extract_hint(f"Filename: {filename}")
