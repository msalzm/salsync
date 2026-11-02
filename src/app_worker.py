"""Run one interface task in an isolated process, using the existing services."""

import json
import logging
import os
from pathlib import Path
import sys


PROJECT_DIR = Path(__file__).resolve().parents[1]


def spotify_client():
    import spotipy
    from spotipy.oauth2 import CacheFileHandler, SpotifyPKCE

    client_id = os.environ.get("SPOTIFY_CLIENT_ID")
    if not client_id:
        raise ValueError("Set SPOTIFY_CLIENT_ID in the terminal before starting the app.")
    return spotipy.Spotify(auth_manager=SpotifyPKCE(
        client_id=client_id,
        redirect_uri="http://127.0.0.1:8888/callback",
        scope="playlist-read-private",
        cache_handler=CacheFileHandler(cache_path=str(PROJECT_DIR / ".cache-spotify")),
    ))


def execute(request, directory):
    action = request["action"]
    source = request.get("source")
    if action in {"search", "download"}:
        from sockseek import run_sockseek

        options = request.get("options", {})
        run_sockseek(
            request["tracks"], download=action == "download",
            csv_path=PROJECT_DIR / ".sockseek" / "app.csv",
            executable=options.get("binary") or None,
            config_path=options.get("config") or None,
            output_dir=options.get("output_dir") or PROJECT_DIR / "downloads",
        )
        return {}

    if action == "organize":
        from folder import organize_tracks

        organized, failed = organize_tracks(request["tracks"])
        return {"organized": [[old["service_id"], new] for old, new in zip(request["tracks"], organized)],
                "failed": failed}

    if source == "folder":
        from folder import get_tracks_from_folder

        return {"tracks": get_tracks_from_folder(
            request["folder"], recursive=request.get("recursive", False),
        )}

    if source == "youtube":
        from check_youtube import get_youtube_client
        from youtube import get_tracks_from_playlist, get_youtube_playlists

        client = get_youtube_client()
        if action == "playlists":
            return {"playlists": get_youtube_playlists(client)}
    else:
        from spotify import get_tracks_from_playlist, get_spotify_playlists

        client = spotify_client()
        if action == "playlists":
            return {"playlists": [
                {"id": item["id"], "name": item["name"]}
                for item in get_spotify_playlists(client)
            ]}
    return {"tracks": get_tracks_from_playlist(client, request["playlist_id"])}


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    directory = Path(sys.argv[1])
    request = json.loads((directory / "request.json").read_text(encoding="utf-8"))
    print(f"Starting {request['action']}…", flush=True)
    try:
        result = execute(request, directory)
    except Exception as error:
        print(f"Error: {error}", flush=True)
        return 1
    (directory / "result.json").write_text(json.dumps(result), encoding="utf-8")
    if result.get("failed"):
        print(f"Error: {result['failed']} file(s) could not be tagged and renamed.", flush=True)
        return 1
    print("Finished.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
