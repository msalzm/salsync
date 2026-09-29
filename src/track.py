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
    