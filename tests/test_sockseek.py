import contextlib
import csv
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch

from mutagen.id3 import ID3

from sockseek import download_tracks, search_tracks


TRACK = {"service": "youtube", "service_id": "video-1", "url": "youtube-url",
         "title": "White Flag", "artists": ["Dido", "Guest"],
         "album": "Life for Rent", "release_year": 2003}


# Emulate the documented CSV, source-number, completion and index contracts.
# The actual tagger is executed in a child process with real MPEG/ID3 files.
FAKE_SOCKSEEK = textwrap.dedent('''\
    import csv, json, os, shlex, subprocess, sys
    from pathlib import Path

    args = sys.argv[1:]
    Path(os.environ["SOCKSEEK_TEST_ARGS"]).write_text(json.dumps(args))
    if "--print" in args:
        sys.exit(0)
    output = Path(args[args.index("--output-dir") + 1])
    output.mkdir(parents=True, exist_ok=True)
    index_path = output / "fake-index.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else {}
    hooks = [args[i + 1].removeprefix("+ ")
             for i, arg in enumerate(args) if arg == "--on-complete"]
    with open(args[0], encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for item, row in enumerate(rows, start=1):
        key = json.dumps(row, sort_keys=True)
        previous = index.get(key)
        exists = previous is not None and Path(previous).exists()
        if exists:
            path = Path(previous)
            when = "when=already-exists"
        else:
            path = output / f"peer shared track {item}.mp3"
            audio = (bytes.fromhex("fffb9000") + bytes(413)) * 8
            if os.environ.get("SOCKSEEK_TEST_CORRUPT_ITEM") == str(item):
                audio = b"corrupt MPEG download"
            path.write_bytes(audio)
            when = "when=success"
        hook = next(hook for hook in hooks if hook.startswith(when + " "))
        command = shlex.split(hook.split(" -- ", 1)[1])
        command = [arg.replace("{snum}", str(item)).replace("{path}", str(path))
                   for arg in command]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stderr)
        status, new_path = result.stdout.strip().split(";", 1)
        assert status in ("success", "ignored")
        index[key] = new_path
        index_path.write_text(json.dumps(index))
    sys.exit(0)
''')


class SockseekTaggingIntegrationTests(unittest.TestCase):
    def setUp(self):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        directory = stack.enter_context(tempfile.TemporaryDirectory())
        self.folder = Path(directory).resolve()
        self.output = self.folder / "downloads with spaces"
        self.csv_path = self.folder / "playlist.csv"
        self.args_path = self.folder / "argv.json"
        self.binary = self.folder / "fake sockseek"
        self.binary.write_text(f"#!{sys.executable}\n" + FAKE_SOCKSEEK, encoding="utf-8")
        self.binary.chmod(0o700)
        self.config = self.folder / "sockseek.conf"
        self.config.write_text("username = example\npassword = private-test-password\n")
        stack.enter_context(patch("sockseek.RUN_DIR", self.folder / "runs"))
        stack.enter_context(patch.dict(os.environ, {
            "SOCKSEEK_TEST_ARGS": str(self.args_path), "SOCKSEEK_TEST_CORRUPT_ITEM": "",
        }))
        stack.enter_context(contextlib.redirect_stdout(io.StringIO()))

    def options(self):
        return {"executable": self.binary, "config_path": self.config,
                "csv_path": self.csv_path, "output_dir": self.output}

    def test_real_callback_tags_full_metadata_and_updates_download_index(self):
        track = {**TRACK, "title": 'White Flag, "Live" $(literal)', "artists": ["Björk", "Guest"]}
        result = download_tracks([track], **self.options())
        self.assertEqual(result.returncode, 0)
        index = json.loads((self.output / "fake-index.json").read_text())
        path = Path(next(iter(index.values())))
        self.assertTrue(path.exists())
        self.assertTrue(path.name.startswith("Björk & Guest - White Flag"))
        self.assertFalse((self.output / "peer shared track 1.mp3").exists())
        tags = ID3(path)
        self.assertEqual(tags["TPE1"].text, ["Björk", "Guest"])
        self.assertEqual(tags["TIT2"].text, [track["title"]])
        self.assertEqual(str(tags["TDRC"].text[0]), "2003")
        self.assertFalse(tags.getall("WXXX"))
        self.assertFalse(tags.getall("TXXX"))
        args = json.loads(self.args_path.read_text())
        self.assertEqual(args[args.index("--format") + 1], "mp3")
        self.assertIn("--write-index", args)
        self.assertNotIn("private-test-password", " ".join(args))

    def test_limit_and_item_number_preserve_track_to_file_mapping(self):
        tracks = [TRACK, {**TRACK, "title": "Second Song", "release_year": 1999},
                  {**TRACK, "title": "Must not be downloaded"}]
        download_tracks(tracks, limit=2, **self.options())
        self.assertEqual(str(ID3(self.output / "Dido & Guest - White Flag.mp3")["TDRC"].text[0]), "2003")
        self.assertEqual(str(ID3(self.output / "Dido & Guest - Second Song.mp3")["TDRC"].text[0]), "1999")
        self.assertEqual(len(list(self.output.glob("*.mp3"))), 2)
        manifest = next((self.folder / "runs").glob("*/tracks.json"))
        self.assertEqual(json.loads(manifest.read_text())["tracks"], tracks[:2])

    def test_already_downloaded_file_is_retagged_without_creating_another_copy(self):
        download_tracks([TRACK], **self.options())
        path = self.output / "Dido & Guest - White Flag.mp3"
        download_tracks([{**TRACK, "release_year": 2004}], **self.options())
        self.assertEqual(str(ID3(path)["TDRC"].text[0]), "2004")
        self.assertEqual(list(self.output.glob("*.mp3")), [path])

    def test_one_tag_error_is_reported_even_when_other_downloads_succeed(self):
        with patch.dict(os.environ, {"SOCKSEEK_TEST_CORRUPT_ITEM": "1"}):
            with self.assertRaisesRegex(RuntimeError, "Could not tag 1 download"):
                download_tracks([TRACK, {**TRACK, "title": "Second Song"}], **self.options())
        original = self.output / "peer shared track 1.mp3"
        self.assertEqual(original.read_bytes(), b"corrupt MPEG download")
        self.assertTrue((self.output / "Dido & Guest - Second Song.mp3").is_file())
        results = [json.loads(path.read_text()) for path in (self.folder / "runs").glob("*/result-*.json")]
        self.assertEqual({result["status"] for result in results}, {"tagged", "failed"})

    def test_search_does_not_create_tagging_manifests_or_touch_audio(self):
        with patch("sockseek.importlib.util.find_spec", return_value=None):
            result = search_tracks([TRACK], **self.options())
        self.assertEqual(result.returncode, 0)
        self.assertFalse((self.folder / "runs").exists())
        self.assertFalse(self.output.exists())
        args = json.loads(self.args_path.read_text())
        self.assertNotIn("--on-complete", args)
        self.assertNotIn("--format", args)
        self.assertIn("--no-write-index", args)

    def test_missing_mutagen_fails_before_launching_downloader(self):
        with patch("sockseek.importlib.util.find_spec", return_value=None), \
                self.assertRaisesRegex(ValueError, "Mutagen"):
            download_tracks([TRACK], **self.options())
        self.assertFalse(self.args_path.exists())

    def test_empty_input_does_not_launch_downloader(self):
        self.assertIsNone(download_tracks([], **self.options()))
        self.assertFalse(self.args_path.exists())
        self.assertFalse(self.csv_path.exists())

    def test_csv_keeps_primary_artist_and_escapes_quoted_multiline_title(self):
        track = {**TRACK, "title": 'One, "Two"\nThree'}
        search_tracks([track], **self.options())
        with self.csv_path.open(encoding="utf-8", newline="") as handle:
            self.assertEqual(list(csv.DictReader(handle)), [
                {"artist": "Dido", "title": track["title"], "album": "Life for Rent"},
            ])
