import argparse
import csv
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from audio import validate_track


PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CSV = PROJECT_DIR / ".sockseek" / "tracks.csv"
DEFAULT_DOWNLOAD_DIR = PROJECT_DIR / "downloads"
RUN_DIR = PROJECT_DIR / ".sockseek" / "runs"
AUDIO_SCRIPT = Path(__file__).with_name("audio.py")


def prepare_tagging(tracks, output_dir):
    if importlib.util.find_spec("mutagen") is None:
        raise ValueError("MP3 tagging requires Mutagen. Install it with: python -m pip install mutagen")
    if any(character in str(output_dir) for character in ";\r\n"):
        raise ValueError("Download directory cannot contain semicolons or line breaks")
    for track in tracks:
        validate_track(track)
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    run_dir = Path(tempfile.mkdtemp(prefix="download-", dir=RUN_DIR))
    manifest = run_dir / "tracks.json"
    manifest.write_text(json.dumps({"tracks": tracks, "output_dir": str(output_dir)},
                                   ensure_ascii=False, allow_nan=False), encoding="utf-8")
    return manifest


def tagging_action(manifest, when):
    command = subprocess.list2cmdline([
        sys.executable, str(AUDIO_SCRIPT), "--manifest", str(manifest),
        "--item", "{snum}",
    ])
    return f'{when} scope=track lock update-index -- {command} --path "{{path}}"'


def report_tagging_results(manifest):
    results = [json.loads(path.read_text(encoding="utf-8"))
               for path in manifest.parent.glob("result-*.json")]
    failed = [result for result in results if result["status"] == "failed"]
    tagged = sum(result["status"] == "tagged" for result in results)
    print(f"Tagged {tagged} MP3 file(s).", flush=True)
    if failed:
        details = "; ".join(f"item {result['item_number']}: {result['error']}" for result in failed)
        raise RuntimeError(f"Could not tag {len(failed)} download(s): {details}. Reports: {manifest.parent}")


def export_tracks_csv(tracks, csv_path=DEFAULT_CSV):
    path = Path(csv_path).expanduser().resolve()
    if path.suffix.casefold() != ".csv":
        raise ValueError("Sockseek input must be a .csv file")

    rows = []
    for index, track in enumerate(tracks, start=1):
        title = track.get("title")
        artists = track.get("artists")
        album = track.get("album")
        if not isinstance(title, str) or not title.strip():
            raise ValueError(f"Track {index} needs a title")
        if (not isinstance(artists, list) or not artists
                or not isinstance(artists[0], str) or not artists[0].strip()):
            raise ValueError(f"Track {index} needs an artists list with a primary artist")
        if album is not None and not isinstance(album, str):
            raise ValueError(f"Track {index} album must be a string or None")
        rows.append({"artist": artists[0].strip(), "title": title.strip(),
                     "album": album or ""})

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["artist", "title", "album"])
        writer.writeheader()
        writer.writerows(rows)
    return path


def run_sockseek(tracks, *, download=False, csv_path=DEFAULT_CSV,
                output_dir=DEFAULT_DOWNLOAD_DIR, config_path=None,
                executable=None, limit=None):
    if limit is not None and (isinstance(limit, bool)
                              or not isinstance(limit, int) or limit < 1):
        raise ValueError("limit must be a positive integer")
    selected = list(tracks)
    if limit is not None:
        selected = selected[:limit]
    if not selected:
        return None

    binary = os.fspath(executable or os.environ.get("SOCKSEEK_BINARY") or "sockseek")
    binary_path = shutil.which(os.path.expanduser(binary))
    if binary_path is None:
        raise FileNotFoundError(
            "Sockseek executable not found. Install it from "
            "https://github.com/fiso64/sockseek/releases and put it on PATH, "
            "or set SOCKSEEK_BINARY to its executable path."
        )

    config = config_path or os.environ.get("SOCKSEEK_CONFIG")
    if config:
        config = Path(config).expanduser().resolve()
        if not config.is_file():
            raise FileNotFoundError(f"Sockseek config not found: {config}")

    csv_file = export_tracks_csv(selected, csv_path)
    destination = Path(output_dir).expanduser().resolve()
    manifest = prepare_tagging(selected, destination) if download else None
    command = [binary_path, str(csv_file), "--input-type", "csv",
                "--no-progress",
               "--output-dir", str(destination)]
    if config:
        command.extend(["--config", str(config)])
    if not download:
        command.extend(["--print", "results-full", "--no-write-index"])
    else:
        command.extend([
            "--format", "mp3", "--write-index", "--upgrade-to-album", "false",
            "--aggregate", "false", "--yt-parse", "false",
            "--on-complete", tagging_action(manifest, "when=success"),
            "--on-complete", "+ " + tagging_action(manifest, "when=already-exists"),
        ])

    result = subprocess.run(command, check=True)
    if manifest is not None:
        report_tagging_results(manifest)
    return result


def search_tracks(tracks, **options):
    """Search Soulseek for normalized tracks without downloading."""
    return run_sockseek(tracks, download=False, **options)


def download_tracks(tracks, **options):
    """Download matching MP3s, then tag and name them from normalized metadata."""
    return run_sockseek(tracks, download=True, **options)


def add_sockseek_arguments(parser, source):
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--search", action="store_true",
                      help="Search normalized tracks on Soulseek without downloading")
    mode.add_argument("--download", action="store_true",
                      help="Download matching MP3s, tag them and set their filenames")
    parser.add_argument("--limit", type= int,
                        help="Search/download only the first N normalized tracks")
    parser.add_argument("--sockseek-binary", help="Sockseek executable (or SOCKSEEK_BINARY)")
    parser.add_argument("--sockseek-config", help="Config file (or SOCKSEEK_CONFIG)")
    parser.add_argument("--sockseek-csv", default=PROJECT_DIR / ".sockseek" / f"{source}.csv",
                        help="CSV export path; default: .sockseek/<source>.csv")
    parser.add_argument("--download-dir", default=DEFAULT_DOWNLOAD_DIR,
                        help="Download destination; default: project downloads folder")


def run_sockseek_from_args(tracks, args, parser):
    if not args.search and not args.download:
        return None
    try:
        return run_sockseek(
            tracks, download=args.download, csv_path=args.sockseek_csv,
            output_dir=args.download_dir, config_path=args.sockseek_config,
            executable=args.sockseek_binary, limit=args.limit,
        )
    except (OSError, ValueError, TaggingError) as error:
        parser.error(str(error))
    except subprocess.CalledProcessError as error:
        parser.exit(1, f"Sockseek exited with code {error.returncode}; see its output above.\n")
