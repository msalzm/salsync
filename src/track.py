def normalize_spotify_track(track_data):
    """
    Normalize track data
    """

    norm = {}

    norm["service"] = "spotify"
    norm["url"] = track_data["external_urls"]["spotify"]
    norm["service_id"] = track_data["id"]
    norm["title"] = track_data["name"]
    norm["artists"] = [artist["name"] for artist in track_data["artists"]]
    norm["album"] = track_data["album"]["name"]

    return norm

def normalize_youtube_track(track_data):
    """Format an enriched YouTube item using the common track fields."""
    snippet = track_data.get("snippet", {})
    video_id = (
        track_data.get("contentDetails", {}).get("videoId")
        or snippet.get("resourceId", {}).get("videoId")
    )
    title = track_data.get("title")
    artists = track_data.get("artists")
    if not video_id or not isinstance(title, str) or not title.strip() or not artists:
        return None

    norm = {}

    norm["service"] = "youtube"
    norm["url"] = f"https://www.youtube.com/watch?v={video_id}"
    norm["service_id"] = video_id
    norm["title"] = title.strip()
    norm["artists"] = artists
    norm["album"] = track_data.get("album")

    return norm

def find_match(track, candidates):
    track_title = track["title"].strip().casefold()
    track_names = {name.strip().casefold() for name in track["artists"]}

    for candidate in candidates:
        candidate_title = candidate["title"].strip().casefold()
        candidate_names = {name.strip().casefold() for name in candidate["artists"]}
        artists_overlap = bool(track_names & candidate_names)

        if candidate_title == track_title and artists_overlap:
            return candidate

    return None

def tracks_to_add(source_tracks, destination_tracks):
    missing_tracks = []
    for track in source_tracks:
        if not find_match(track, destination_tracks):
            missing_tracks.append(track)

    return missing_tracks
