from track import normalize_spotify_track
def get_spotify_playlists(spotify):
    playlists = []
    page = spotify.current_user_playlists(limit=50)

    while page is not None:
        playlists.extend(page["items"])
        if page["next"] is not None:
            page = spotify.next(page)
        else:
            page = None

    return playlists

def get_tracks_from_playlist(spotify, playlist_id):
    tracks = []
    page = spotify.playlist_items(playlist_id, limit=50)

    while page is not None:
        page_tracks = page["items"]
        
        for entry in page_tracks:
            track_data = entry["item"]
            
            if track_data is not None and track_data["type"] == "track":
                norm_track = normalize_spotify_track(track_data)
                tracks.append(norm_track)

        page = spotify.next(page)
        
    return tracks