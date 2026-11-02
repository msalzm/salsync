"""Identify MP3s from tags or filenames, then optionally tag and rename them."""

import argparse
import logging


from folder import get_tracks_from_folder, organize_tracks
from sockseek import add_sockseek_arguments, run_sockseek_from_args


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", help="Folder containing MP3 files")
    parser.add_argument("--recursive", action="store_true", help="Include subfolders")
    parser.add_argument("--organize", action="store_true",
                        help="Write tags and rename files to 'Artist - Title.mp3'")
    add_sockseek_arguments(parser, "folder")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    try:
        tracks = get_tracks_from_folder(
            args.folder, recursive=args.recursive,
        )
    except OSError as error:
        parser.error(str(error))
    failed = 0
    if args.organize:
        tracks, failed = organize_tracks(tracks)

    print(len(tracks))
    for track in tracks[:3]:
        print(f"title: {track['title']} artist: {track['artists']} album: {track['album']}")
    if failed:
        parser.exit(1, f"{failed} file(s) could not be tagged and renamed.\n")

    run_sockseek_from_args(tracks, args, parser)


if __name__ == "__main__":
    main()
