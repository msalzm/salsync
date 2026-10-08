from pathlib import Path

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from youtube import get_youtube_playlists, get_tracks_from_playlist
from playlist import find_target_playlist


SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]

PROJECT_DIR = Path(__file__).resolve().parents[1]
TOKEN_FILE = PROJECT_DIR / ".youtube-token.json"
CLIENT_SECRETS_FILE = PROJECT_DIR / (
    "client_secret_926166421256-0evqgkolp2mg1jtf3ar9ri4onck2u1mh"
    ".apps.googleusercontent.com.json"
)


def get_youtube_client():
    """Authenticate and return the YouTube API client."""
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
    youtube = get_youtube_client()
    playlists = get_youtube_playlists(youtube)
    target_playlist = find_target_playlist("salsync", playlists)

    if target_playlist:
        playlist_id = target_playlist["id"]
        tracks = get_tracks_from_playlist(youtube, playlist_id)

        print(len(tracks))
        for track in tracks[:3]:
            print(f"title: {track['title']} artist: {track['artists']} album: {track['album']}")


if __name__ == "__main__":
    main()
