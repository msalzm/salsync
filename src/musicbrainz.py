"""Look up a track's original album, falling back to its first release."""

from datetime import date
import os
import re
import unicodedata

import musicbrainzngs as mb


def normalized(text):
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def artist_names(recording):
    return [
        credit.get("name") or credit.get("artist", {}).get("name", "")
        for credit in recording.get("artist-credit", [])
        if isinstance(credit, dict)
    ]


def matches(recording, title, artist):
    credits = recording.get("artist-credit", [])
    names = artist_names(recording)
    # Accept both an individual artist and the complete joined credit.
    full_credit = "".join(
        credit if isinstance(credit, str) else (
            (credit.get("name") or credit.get("artist", {}).get("name", ""))
            + credit.get("joinphrase", "")
        )
        for credit in credits
    )
    canonical_names = [
        credit.get("artist", {}).get("name", "")
        for credit in credits if isinstance(credit, dict)
    ]
    return (
        normalized(recording.get("title", "")) == normalized(title)
        and normalized(artist) in {
            normalized(name) for name in names + canonical_names + [full_credit]
        }
    )


def pages(fetch, entity, **kwargs):
    offset = 0
    while True:
        page = fetch(limit=100, offset=offset, **kwargs)
        items = page.get(f"{entity}-list", [])
        yield from items
        offset += len(items)
        count = page.get(f"{entity}-count")
        if not items or (
            offset >= int(count) if count is not None else len(items) < 100
        ):
            return


def date_key(value):
    """Preserve partial dates, using their earliest possible day for sorting."""
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}(-\d{2}){0,2}", value):
        return None
    parts = [int(part) for part in value.split("-")]
    try:
        return date(*(parts + [1] * (3 - len(parts))))
    except ValueError:
        return None


def is_original_album(release):
    group = release.get("release-group", {})
    primary_type = group.get("primary-type") or group.get("type", "")
    secondary_types = {
        value.casefold() for value in group.get("secondary-type-list", [])
    }
    return primary_type.casefold() == "album" and not secondary_types.intersection(
        {"compilation", "live", "remix"}
    )


def find_first_release(song_title, artist_name, *, client=None):
    if not isinstance(song_title, str) or not song_title.strip():
        return None
    if not isinstance(artist_name, str) or not artist_name.strip():
        return None

    client = mb if client is None else client
    client.set_useragent("salsync", "0.1", os.environ.get("MUSICBRAINZ_CONTACT"))
    earliest = None
    seen = set()
    for recording in pages(
        client.search_recordings, "recording",
        recording=song_title.strip(), artist=artist_name.strip(), strict=True,
    ):
        if not matches(recording, song_title, artist_name):
            continue
        if recording["id"] in seen:
            continue
        seen.add(recording["id"])
        for release in pages(
            client.browse_releases, "release", recording=recording["id"],
            release_status=["official"], includes=["release-groups"],
        ):
            if release.get("status", "").casefold() != "official":
                continue
            release_date = date_key(release.get("date"))
            if release_date is None:
                continue
            key = (
                0 if is_original_album(release) else 1,
                release_date, release["id"], recording["id"],
            )
            if earliest is None or key < earliest[0]:
                earliest = (key, recording, release)

    if earliest is None:
        return None

    _, recording, release = earliest
    recording = client.get_recording_by_id(
        recording["id"], includes=["artist-credits", "isrcs"],
    )["recording"]
    details = client.get_release_by_id(
        release["id"], includes=["artist-credits", "labels", "release-groups", "media"],
    )["release"]
    group = details.get("release-group", {})
    length = recording.get("length")

    first_release = {
        "title": recording["title"],
        "artists": artist_names(recording),
        "album": details["title"],
        "release_date": release["date"],
        "country": details.get("country"),
        "release_type": group.get("primary-type") or group.get("type"),
        "labels": [
            {
                "name": info.get("label", {}).get("name"),
                "catalog_number": info.get("catalog-number"),
            }
            for info in details.get("label-info-list", [])
        ],
        "formats": list(dict.fromkeys(
            medium["format"] for medium in details.get("medium-list", [])
            if medium.get("format")
        )),
        "duration_ms": int(length) if length is not None else None,
        "isrcs": recording.get("isrc-list", []),
        "recording_id": recording["id"],
        "recording_comment": recording.get("disambiguation"),
        "release_id": release["id"],
        "release_group_id": group.get("id"),
        "source": "musicbrainz",
        "url": f"https://musicbrainz.org/release/{release['id']}",
    }

    return first_release

