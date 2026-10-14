"""Name and tag completed MP3 downloads using normalized track metadata."""

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import unicodedata


def validate_track(track):
    title = track.get("title")
    artists = track.get("artists")
    if not isinstance(title, str) or not title.strip() or "\0" in title:
        raise ValueError("Track needs a nonempty title without null characters")
    if (not isinstance(artists, list) or not artists
            or any(not isinstance(artist, str) or not artist.strip() or "\0" in artist
                   for artist in artists)):
        raise ValueError("Track needs a nonempty artists list")
    album = track.get("album")
    if album is not None and (not isinstance(album, str) or "\0" in album):
        raise ValueError("Album must be a string without null characters, or None")
    year = track.get("release_year")
    if year is not None and (isinstance(year, bool) or not isinstance(year, int)
                             or not 1 <= year <= 9999):
        raise ValueError("Release year must be an integer from 1 to 9999, or None")


def build_filename(track):
    validate_track(track)
    name = " & ".join(artist.strip() for artist in track["artists"])
    name += " - " + track["title"].strip()
    name = unicodedata.normalize("NFC", name)
    # Semicolons/newlines also delimit Sockseek's completion response.
    name = re.sub(r'[<>:"/\\|?*;\x00-\x1f\x7f]', "-", name)
    name = " ".join(name.split()).strip(" .")
    # Leave room for a collision suffix and extension on common filesystems.
    name = name.encode("utf-8")[:220].decode("utf-8", errors="ignore").rstrip(" .")
    return name + ".mp3"


def tag_downloaded_track(file_path, track):
    """Write only the supplied title, artist, album and year fields as ID3v2.4."""
    from mutagen.id3 import TALB, TDRC, TIT2, TPE1
    from mutagen.mp3 import MP3

    validate_track(track)
    path = Path(file_path)
    if path.suffix.casefold() != ".mp3":
        raise ValueError(f"Expected an MP3 download: {path}")
    audio = MP3(path)  # Validate the audio stream as well as the filename.
    if audio.tags is None:
        audio.add_tags()
    audio.tags.setall("TIT2", [TIT2(encoding=3, text=[track["title"].strip()])])
    audio.tags.setall("TPE1", [TPE1(encoding=3, text=[a.strip() for a in track["artists"]])])
    if track.get("album") and track["album"].strip():
        audio.tags.setall("TALB", [TALB(encoding=3, text=[track["album"].strip()])])
    if track.get("release_year") is not None:
        audio.tags.setall("TDRC", [TDRC(encoding=3, text=[f"{track['release_year']:04d}"])])
    audio.save(v2_version=4)


def finish_download(file_path, track):
    """Tag a temporary copy and publish its final name without overwriting peers."""
    source = Path(file_path).resolve(strict=True)
    if not source.is_file() or source.suffix.casefold() != ".mp3":
        raise ValueError(f"Expected an MP3 download: {source}")
    filename = build_filename(track)
    stem = Path(filename).stem
    already_named = source.name == filename or re.fullmatch(
        re.escape(stem) + r" \([1-9][0-9]*\)\.mp3", source.name,
    )
    fd, name = tempfile.mkstemp(prefix=".salsync-", suffix=".mp3", dir=source.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        shutil.copy2(source, temporary)
        tag_downloaded_track(temporary, track)
        if already_named:
            os.replace(temporary, source)
            return source
        number = 1
        while True:
            suffix = "" if number == 1 else f" ({number})"
            destination = source.with_name(f"{stem}{suffix}.mp3")
            try:
                # Reserve a free name exclusively, including on drives without hard links.
                fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(fd)
                break
            except FileExistsError:
                number += 1
        try:
            os.replace(temporary, destination)
            source.unlink()
        except OSError:
            destination.unlink()
            raise
        return destination
    finally:
        temporary.unlink(missing_ok=True)


def complete_download(manifest_path, item_number, file_path):
    manifest_path = Path(manifest_path)
    source = Path(file_path)
    result = {"item_number": item_number, "original_path": str(source)}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        tracks = manifest["tracks"]
        if item_number < 1 or item_number > len(tracks):
            raise ValueError(f"Unknown Sockseek source item: {item_number}")
        root = Path(manifest["output_dir"]).resolve()
        source = source.resolve(strict=True)
        if not source.is_relative_to(root):
            raise ValueError("Completed file is outside the download directory")
        destination = finish_download(source, tracks[item_number - 1])
        result.update({"status": "tagged", "path": str(destination)})
    except Exception as error:
        # The parent reads these reports even when Sockseek exits successfully.
        result.update({"status": "failed", "error": str(error)})
        print(f"Could not tag download {item_number}: {error}", file=sys.stderr)

    report = manifest_path.parent / f"result-{item_number}.json"
    report.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    if result["status"] == "tagged":
        print(f"success;{result['path']}")
        return 0
    if not any(character in str(source) for character in ";\r\n"):
        print(f"ignored;{source}")
        return 0
    return 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--item", type=int, required=True)
    parser.add_argument("--path", required=True)
    args = parser.parse_args()
    return complete_download(args.manifest, args.item, args.path)


if __name__ == "__main__":
    sys.exit(main())
