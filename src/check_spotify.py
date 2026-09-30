import os

import spotipy
from spotify import get_spotify_playlists
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

target_playlist = find_target_playlist("amanecer", playlists)

print(f"Target playlist: {target_playlist['name']} (ID: {target_playlist['id']})")