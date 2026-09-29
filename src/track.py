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

