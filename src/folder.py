"""Normalize local MP3s from their tags, falling back to filenames, then tag and rename them."""

import logging
from pathlib import Path

from musicbrainzngs import MusicBrainzError
from mutagen import MutagenError
from mutagen.id3 import ID3, ID3NoHeaderError
from ollama import ResponseError
from requests import RequestException

from audio import finish_download
from discogs import find_first_release as find_discogs_release
from musicbrainz import find_first_release
from track import normalize_folder_track
from llm_title import extract_filename_hint


logger = logging.getLogger(__name__)

# One file failing must not stop the rest of the folder.
FILE_ERRORS = (OSError, ValueError, KeyError, MutagenError, MusicBrainzError,
               RequestException, ResponseError)


def read_credits(path: Path) -> dict:
    """Return title, artists, album and release_date from existing ID3 tags, without writing.

    Missing or blank tags are None (artists: an empty list). A file without an
    ID3 header, including an empty file, has no tags rather than an error.
    """
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = None

    def values(frame_id):
        if tags is None:
            return []
        return [str(value).strip() for frame in tags.getall(frame_id)
                for value in frame.text if str(value).strip()]

    titles, albums, dates = values("TIT2"), values("TALB"), values("TDRC")
    return {
        "title": titles[0] if titles else None,
        "artists": values("TPE1"),
        "album": albums[0] if albums else None,
        "release_date": dates[0] if dates else None,
    }


def identify_mp3(file_path: str | Path) -> dict | None:
    """Identify an MP3 without changing its contents.

    Return {"title": str, "artists": list[str], "album", "release_date"} when
    identified. Prefer existing tags; use filename extraction for missing fields.
    Return None if title or artist remains unknown.
    """
    path = Path(file_path)
    credits = read_credits(path)
    if credits["title"] and credits["artists"]:
        return credits

    # Only mention tags to the model when there are some to preserve.
    known = {}
    if credits["title"]:
        known["tagged_title"] = credits["title"]
    if credits["artists"]:
        known["tagged_artists"] = credits["artists"]
    hint = extract_filename_hint(path.name, **known)

    title = credits["title"] or (hint.get("title") or "").strip()
    artists = credits["artists"] or [(hint.get("artist") or "").strip()]
    if not title or not artists[0]:
        logger.warning("Skipped %s: could not identify title and artist", path)
        return None
    return {**credits, "title": title, "artists": artists}


def find_mp3_files(folder: Path, recursive: bool = False) -> list[Path]:
    """Return MP3 paths sorted case-insensitively; `.MP3` counts."""
    entries = folder.rglob("*") if recursive else folder.iterdir()
    return sorted(
        (path for path in entries if path.is_file() and path.suffix.casefold() == ".mp3"),
        key=lambda path: str(path).casefold(),
    )


def resolve_mp3_track(path: Path) -> dict | None:
    """Identify one MP3, look up its release if needed and return a normalized track.

    Return None (after identify_mp3 logs a WARNING) when unidentifiable.
    Files tagged with title, artist, album and year skip the lookup.
    Otherwise prefer matched metadata's title, artists and album. Without a
    match, keep the identified credits and any tagged album and year.
    """
    credits = identify_mp3(path)
    if credits is None:
        return None

    metadata = None
    if not (credits["album"] and credits["release_date"]):
        metadata = find_first_release(credits["title"], credits["artists"][0])
        if metadata is None:
            metadata = find_discogs_release(credits["title"], credits["artists"][0])
    if metadata is None:
        metadata = credits

    return normalize_folder_track({
        "path": path,
        "title": metadata.get("title") or credits["title"],
        "artists": metadata.get("artists") or credits["artists"],
        "album": metadata.get("album"),
        "release_date": metadata.get("release_date"),
    })


def get_tracks_from_folder(folder_path, *, recursive=False) -> list[dict]:
    """Return normalized tracks for every identifiable MP3 in the folder.

    Raise NotADirectoryError for a missing folder. Log per-file service
    errors at ERROR and continue with the remaining files. Files are only read.
    """
    folder = Path(folder_path).expanduser().resolve()
    if not folder.is_dir():
        raise NotADirectoryError(f"Not a folder: {folder}")

    tracks = []
    for path in find_mp3_files(folder, recursive):
        try:
            track = resolve_mp3_track(path)
        except FILE_ERRORS as error:
            logger.error("Failed %s: %s", path.name, error)
            continue
        if track is not None:
            tracks.append(track)
    return tracks


def organize_tracks(tracks: list[dict]) -> tuple[list[dict], int]:
    """Write tags to local tracks and rename each file to `Artist - Title.mp3`.

    Return the tracks in the same order, pointing to their new paths, and the
    number of failures. A track that fails is logged at ERROR and returned unchanged.
    """
    organized, failed = [], 0
    for track in tracks:
        try:
            if track.get("service") != "local":
                raise ValueError("Only local folder tracks can be renamed")
            new_path = Path(finish_download(track["service_id"], track))
        except FILE_ERRORS as error:
            logger.error("Failed %s: %s", track.get("service_id"), error)
            organized.append(track)
            failed += 1
            continue
        logger.info("Tagged %s", new_path.name)
        organized.append({**track, "url": new_path.as_uri(), "service_id": str(new_path)})
    return organized, failed
