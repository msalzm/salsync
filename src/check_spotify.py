import os

import spotipy
from track import find_match, normalize_spotify_track, tracks_to_add
from spotify import get_spotify_playlists, get_tracks_from_playlist
from playlist import find_target_playlist
from spotipy.oauth2 import CacheFileHandler, SpotifyPKCE

auth = SpotifyPKCE(
    client_id=os.environ["SPOTIFY_CLIENT_ID"],
    redirect_uri="http://127.0.0.1:8888/callback",
    scope="playlist-read-private",
    cache_handler=CacheFileHandler(cache_path=".cache-spotify"),
)
spotify = spotipy.Spotify(auth_manager=auth)
playlists = get_spotify_playlists(spotify)
target_playlist = find_target_playlist("popop", playlists)

if target_playlist:
    playlist_id = target_playlist["id"]
    tracks = get_tracks_from_playlist(spotify, playlist_id)

    print(len(tracks))
    for t in tracks[:3]:
        print(f"title: {t["title"]} artist: {t["artists"]}")

   