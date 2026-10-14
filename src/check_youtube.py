import argparse
from pathlib import Path

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


from youtube import get_youtube_playlists, get_tracks_from_playlist
from playlist import find_target_playlist
from sockseek import add_sockseek_arguments, run_sockseek_from_args



SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]

PROJECT_DIR = Path(__file__).resolve().parents[1]
TOKEN_FILE = PROJECT_DIR / ".youtube-token.json"
CLIENT_SECRETS_FILE = PROJECT_DIR / (
    "client_secret_926166421256-0evqgkolp2mg1jtf3ar9ri4onck2u1mh"
    ".apps.googleusercontent.com.json"
)


def get_youtube_client():
    """Reuse the saved credentials, opening sign-in only when necessary."""
    credentials = None

    if TOKEN_FILE.exists():
        credentials = Credentials.from_authorized_user_file(
            str(TOKEN_FILE), SCOPES
        )

    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            try:
                credentials.refresh(Request())
            except RefreshError:
                credentials = None

        if not credentials or not credentials.valid:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CLIENT_SECRETS_FILE), SCOPES
            )
            credentials = flow.run_local_server(port=0)

        TOKEN_FILE.write_text(credentials.to_json(), encoding="utf-8")

    return build("youtube", "v3", credentials=credentials)


def main():
    parser = argparse.ArgumentParser(
        description="Normalize a YouTube playlist, then search or download with Sockseek."
    )
    parser.add_argument("--playlist", default="salsync", help="Playlist name; default: salsync")
    add_sockseek_arguments(parser, "youtube")
    args = parser.parse_args()
    youtube = get_youtube_client()


    playlists = get_youtube_playlists(youtube)
    target_playlist = find_target_playlist(args.playlist, playlists)

    if target_playlist:
        playlist_id = target_playlist["id"]
        tracks = get_tracks_from_playlist(youtube, playlist_id)


        print(len(tracks))
        for t in tracks[:3]:
            print(f"title: {t['title']} artist: {t['artists']} album: {t['album']}")

        run_sockseek_from_args(tracks, args, parser)
    else:
        parser.error(f"Playlist not found: {args.playlist}")


import cProfile
import pstats

if __name__ == "__main__":
    profiler = cProfile.Profile()
    profiler.runcall(main)

    with open("profile.txt", "w") as report:
        pstats.Stats(profiler, stream=report).sort_stats("cumtime").print_stats()
