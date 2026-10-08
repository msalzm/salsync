if __package__:
    from .discogs import find_first_release as find_discogs_release
    from .llm_title import extract_track_hint
    from .musicbrainz import find_first_release
    from .track import normalize_youtube_track
else:
    from discogs import find_first_release as find_discogs_release
    from llm_title import extract_track_hint
    from musicbrainz import find_first_release
    from track import normalize_youtube_track


def get_youtube_playlists(youtube):
    playlists = []
    request = youtube.playlists().list(
        part="snippet",
        mine=True,
        maxResults=50
    )

    while request is not None:
        response = request.execute()
        for item in response.get("items", []):
            playlists.append({
                "id": item["id"],
                "name": item["snippet"]["title"],
                "service": "youtube",
            })
        request = youtube.playlists().list_next(request, response)

    return playlists


def get_tracks_from_playlist(youtube, playlist_id):
    tracks = []

    request = youtube.playlistItems().list(
        part="snippet,contentDetails",
        maxResults=50,
        playlistId=playlist_id,
    )

    while request is not None:
        response = request.execute()
        page_tracks = response.get("items", [])

        for track_data in page_tracks:
            snippet = track_data.get("snippet", {})
            video_title = snippet.get("title", "")
            video_id = (
                track_data.get("contentDetails", {}).get("videoId")
                or snippet.get("resourceId", {}).get("videoId")
            )
            if not video_id or not video_title or video_title in {"Private video", "Deleted video"}:
                continue

            hint = extract_track_hint(video_title, snippet.get("videoOwnerChannelTitle", ""))
            title = hint.get("title")
            artist = hint.get("artist")
            if not isinstance(title, str) or not title.strip():
                continue
            if not isinstance(artist, str) or not artist.strip():
                continue

            metadata = find_first_release(title.strip(), artist.strip())
            if metadata is None:
                metadata = find_discogs_release(title.strip(), artist.strip())
            metadata = metadata or {}
            track_data = {
                **track_data,
                "title": metadata.get("title") or title.strip(),
                "artists": metadata.get("artists") or [artist.strip()],
                "album": metadata.get("album"),
            }
            norm_track = normalize_youtube_track(track_data)
            if norm_track is not None:
                tracks.append(norm_track)

        request = youtube.playlistItems().list_next(request, response)

    return tracks
