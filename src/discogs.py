# src/discogs.py
from collections import defaultdict
import os
import re

import requests


BASE_URL = "https://api.discogs.com"


def normalized(text):
    return " ".join(text.casefold().split())


def artist_name(artist):
    return re.sub(r" \(\d+\)$", "", artist.get("anv") or artist.get("name", "")).strip()


def matches_artist(artists, artist_name):
    names = [artist_name(artist) for artist in artists]
    names.extend(re.sub(r" \(\d+\)$", "", artist.get("name", "")) for artist in artists)
    joined = " ".join(
        f"{artist_name(artist)} {artist.get('join', '')}".strip() for artist in artists
    )
    return normalized(artist_name) in {normalized(name) for name in names + [joined]}


def search_results(session, song_title, artist_name):
    page = 1
    while True:
        response = session.get(
            f"{BASE_URL}/database/search",
            params={"track": song_title, "artist": artist_name, "type": "release",
                    "per_page": 25, "page": page},
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
        results = data.get("results", [])
        yield from results
        if not results or page >= int(data.get("pagination", {}).get("pages", 1)):
            return
        page += 1


def search_discogs(song_title, artist_name):
    token = os.environ["DISCOGS_TOKEN"]

    session = requests.Session()
    session.headers.update({
        "User-Agent": "salsync/0.1",
        "Authorization": f"Discogs token={token}",
    })

    groups = defaultdict(list)

    for result in search_results(session, song_title, artist_name):
        release_response = session.get(
            f"{BASE_URL}/releases/{result['id']}",
            timeout=20,
        )
        release_response.raise_for_status()
        release = release_response.json()

        matching_tracks = [
            track
            for track in release.get("tracklist", [])
            if normalized(track.get("title", "")) == normalized(song_title)
            and matches_artist(track.get("artists") or release.get("artists", []), artist_name)
        ]

        if not matching_tracks:
            continue

        master_id = release.get("master_id")
        group_key = (
            ("master", master_id)
            if master_id
            else ("release", release["id"])
        )

        groups[group_key].append({
            "release_id": release["id"],
            "release_title": release["title"],
            "year": release.get("year"),
            "released": release.get("released"),
            "url": release.get("uri"),
            "master_id": master_id,
            "tracks": matching_tracks,
            "artists": matching_tracks[0].get("artists") or release.get("artists", []),
            "format_descriptions": [
                description
                for release_format in release.get("formats", [])
                for description in release_format.get("descriptions", [])
            ],
        })

    ranked = []

    for group_key, editions in groups.items():
        earliest = min(
            editions,
            key=lambda edition: edition["year"] or 9999,
        )

        ranked.append({
            "master_id": group_key[1] if group_key[0] == "master" else None,
            "release_name": earliest["release_title"],
            "matching_editions": len(editions),
            "earliest_matching_edition": earliest,
            "editions": editions,
        })

    return sorted(
        ranked,
        key=lambda group: group["matching_editions"],
        reverse=True,
    )


def find_first_release(song_title, artist_name):
    matches = search_discogs(song_title, artist_name)
    candidates = []
    for group in matches:
        for edition in group["editions"]:
            descriptions = {normalized(value) for value in edition["format_descriptions"]}
            if descriptions.intersection({"unofficial release", "promo"}) or not edition["year"]:
                continue
            original_album = "album" in descriptions and not descriptions.intersection(
                {"compilation", "remix", "live"}
            )
            key = (
                0 if original_album else 1, int(edition["year"]),
                edition.get("released") or str(edition["year"]), edition["release_id"],
            )
            candidates.append((key, edition))
    if not candidates:
        return None

    _, edition = min(candidates, key=lambda candidate: candidate[0])

    first_release = {
        "title": edition["tracks"][0]["title"],
        "artists": [artist_name(artist) for artist in edition["artists"]],
        "album": edition["release_title"],
        "release_date": edition.get("released") or str(edition["year"]),
        "release_id": edition["release_id"],
        "source": "discogs",
        "url": edition["url"],
    }
    
    return first_release
