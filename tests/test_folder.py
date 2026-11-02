import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from mutagen.id3 import ID3, TALB, TDRC, TIT2, TPE1
from requests import RequestException

import check_folder
from src.folder import get_tracks_from_folder, organize_tracks
from src.track import find_match


METADATA = {
    "title": "White Flag", "artists": ["Dido"], "album": "Life for Rent",
    "source": "musicbrainz", "url": "https://musicbrainz.org/release/release-1",
    "release_date": "2003",
}
PAYLOAD = b"Existing MP3 data and tags must remain unchanged"
# Eight MPEG-1 layer III frames, 128 kbps / 44.1 kHz, without an ID3 header.
MP3_AUDIO = (bytes.fromhex("fffb9000") + bytes(413)) * 8


class FolderNormalizationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name).resolve()
        mb_patch = patch("src.folder.find_first_release", return_value=METADATA)
        discogs_patch = patch("src.folder.find_discogs_release", return_value=None)
        filename_patch = patch("src.folder.extract_filename_hint", return_value={
            "title": "White Flag", "artist": "Dido",
        })
        self.musicbrainz = mb_patch.start()
        self.discogs = discogs_patch.start()
        self.extract = filename_patch.start()
        self.addCleanup(mb_patch.stop)
        self.addCleanup(discogs_patch.stop)
        self.addCleanup(filename_patch.stop)

    def make_file(self, name="01 - Dido - White Flag.mp3"):
        path = self.folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(PAYLOAD)
        return path

    def make_tagged_file(self, name="track.mp3", **frames):
        path = self.make_file(name)
        tags = ID3()
        for frame in frames.values():
            tags.add(frame)
        tags.save(path)
        return path

    def test_untagged_file_is_normalized_without_writing_mp3(self):
        path = self.make_file()
        before = path.read_bytes()
        with patch("pathlib.Path.open", side_effect=AssertionError("Do not open MP3 files")):
            tracks = get_tracks_from_folder(self.folder)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(tracks, [{
            "service": "local", "url": path.as_uri(), "service_id": str(path),
            "title": "White Flag", "artists": ["Dido"], "album": "Life for Rent",
            "release_year": 2003,
        }])
        self.extract.assert_called_once_with("01 - Dido - White Flag.mp3")
        self.musicbrainz.assert_called_once_with("White Flag", "Dido")
        self.discogs.assert_not_called()
        spotify_track = {"title": "White Flag", "artists": ["Dido"]}
        self.assertIs(find_match(tracks[0], [spotify_track]), spotify_track)

    def test_uses_canonical_metadata_title_and_artists(self):
        self.make_file()
        self.musicbrainz.return_value = {
            **METADATA, "title": "Canonical Title", "artists": ["Dido", "Guest"],
        }
        track = get_tracks_from_folder(self.folder)[0]
        self.assertEqual(track["title"], "Canonical Title")
        self.assertEqual(track["artists"], ["Dido", "Guest"])

    def test_discogs_fallback_supplies_album(self):
        path = self.make_file()
        self.musicbrainz.return_value = None
        self.discogs.return_value = METADATA
        tracks = get_tracks_from_folder(self.folder)
        self.discogs.assert_called_once_with("White Flag", "Dido")
        self.assertEqual(tracks[0]["album"], "Life for Rent")
        self.assertEqual(path.read_bytes(), PAYLOAD)

    def test_no_match_retains_extracted_credits_and_unknown_album(self):
        path = self.make_file()
        self.musicbrainz.return_value = self.discogs.return_value = None
        self.extract.return_value = {"title": " White Flag ", "artist": " Dido "}
        tracks = get_tracks_from_folder(self.folder)
        self.assertEqual(tracks[0]["title"], "White Flag")
        self.assertEqual(tracks[0]["artists"], ["Dido"])
        self.assertIsNone(tracks[0]["album"])
        self.assertEqual(path.read_bytes(), PAYLOAD)

    def test_fully_tagged_file_skips_llm_and_lookup(self):
        path = self.make_tagged_file(
            title=TIT2(encoding=3, text=["Tagged Title"]), artist=TPE1(encoding=3, text=["Tagged Artist"]),
            album=TALB(encoding=3, text=["Tagged Album"]), year=TDRC(encoding=3, text=["1999"]),
        )
        before = path.read_bytes()
        tracks = get_tracks_from_folder(self.folder)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual((tracks[0]["title"], tracks[0]["artists"], tracks[0]["album"], tracks[0]["release_year"]),
                         ("Tagged Title", ["Tagged Artist"], "Tagged Album", 1999))
        self.extract.assert_not_called()
        self.musicbrainz.assert_not_called()

    def test_tagged_credits_without_album_are_looked_up_without_llm(self):
        self.make_tagged_file(title=TIT2(encoding=3, text=["White Flag"]), artist=TPE1(encoding=3, text=["Dido"]))
        tracks = get_tracks_from_folder(self.folder)
        self.extract.assert_not_called()
        self.musicbrainz.assert_called_once_with("White Flag", "Dido")
        self.assertEqual(tracks[0]["album"], "Life for Rent")

    def test_partial_tags_are_completed_from_filename(self):
        self.make_tagged_file("Dido - White Flag.mp3", title=TIT2(encoding=3, text=["White Flag"]))
        self.musicbrainz.return_value = self.discogs.return_value = None
        self.extract.return_value = {"title": "Something Else", "artist": "Dido"}
        tracks = get_tracks_from_folder(self.folder)
        self.extract.assert_called_once_with("Dido - White Flag.mp3", tagged_title="White Flag")
        self.assertEqual(tracks[0]["title"], "White Flag")
        self.assertEqual(tracks[0]["artists"], ["Dido"])

    def test_organize_tags_and_renames_files(self):
        path = self.make_file("01 untitled.mp3")
        path.write_bytes(MP3_AUDIO)
        track = get_tracks_from_folder(self.folder)[0]
        [organized], failed = organize_tracks([track])
        self.assertEqual(failed, 0)
        new_path = self.folder / "Dido - White Flag.mp3"
        self.assertFalse(path.exists())
        self.assertEqual(organized["service_id"], str(new_path))
        self.assertEqual(organized["url"], new_path.as_uri())
        tags = ID3(new_path)
        self.assertEqual(tags["TIT2"].text, ["White Flag"])
        self.assertEqual(tags["TALB"].text, ["Life for Rent"])
        self.assertEqual(str(tags["TDRC"].text[0]), "2003")

    def test_organize_failure_is_reported_and_other_tracks_continue(self):
        broken = self.make_file("a.mp3")  # Not valid audio.
        self.make_file("b.mp3").write_bytes(MP3_AUDIO)
        tracks = get_tracks_from_folder(self.folder)
        tracks[1] = {**tracks[1], "title": "Other"}
        with self.assertLogs("src.folder", level="ERROR"):
            organized, failed = organize_tracks(tracks + [{"service": "youtube", "service_id": "video"}])
        self.assertEqual(failed, 2)
        self.assertEqual(organized[0], tracks[0])
        self.assertEqual(broken.read_bytes(), PAYLOAD)
        self.assertEqual(Path(organized[1]["service_id"]).name, "Dido - Other.mp3")
        self.assertEqual(organized[2]["service_id"], "video")

    def test_ambiguous_filename_is_skipped_without_lookup(self):
        path = self.make_file()
        for hint in ({"title": None, "artist": "Dido"},
                     {"title": "White Flag", "artist": " "}):
            with self.subTest(hint=hint):
                self.extract.return_value = hint
                with self.assertLogs("src.folder", level="WARNING"):
                    self.assertEqual(get_tracks_from_folder(self.folder), [])
        self.assertEqual(path.read_bytes(), PAYLOAD)
        self.musicbrainz.assert_not_called()
        self.discogs.assert_not_called()

    def test_untagged_file_is_normalized_from_filename(self):
        path = self.make_file()
        path.write_bytes(b"")
        tracks = get_tracks_from_folder(self.folder)
        self.assertEqual(tracks[0]["title"], "White Flag")
        self.assertEqual(path.read_bytes(), b"")

    def test_filters_extensions_and_supports_recursive_scanning(self):
        top = self.make_file("track.MP3")
        nested = self.make_file("nested/track.mp3")
        self.make_file("ignore.txt")
        tracks = get_tracks_from_folder(self.folder)
        self.assertEqual([track["service_id"] for track in tracks], [str(top)])
        tracks = get_tracks_from_folder(self.folder, recursive=True)
        self.assertEqual({track["service_id"] for track in tracks}, {str(top), str(nested)})

    def test_returns_tracks_in_sorted_filename_order(self):
        self.make_file("b.mp3")
        self.make_file("a.mp3")
        get_tracks_from_folder(self.folder)
        self.assertEqual([item.args[0] for item in self.extract.call_args_list], ["a.mp3", "b.mp3"])

    def test_lookup_failure_is_reported_and_other_files_continue(self):
        failed, successful = self.make_file("a.mp3"), self.make_file("b.mp3")
        self.musicbrainz.side_effect = [RequestException("Lookup failed"), METADATA]
        with self.assertLogs("src.folder", level="ERROR"):
            tracks = get_tracks_from_folder(self.folder)
        self.assertEqual(failed.read_bytes(), PAYLOAD)
        self.assertEqual([track["service_id"] for track in tracks], [str(successful)])
        self.discogs.assert_not_called()

    def test_llm_failure_is_reported_and_other_files_continue(self):
        self.make_file("a.mp3")
        successful = self.make_file("b.mp3")
        self.extract.side_effect = [ConnectionError("Ollama unavailable"),
                                    {"title": "White Flag", "artist": "Dido"}]
        with self.assertLogs("src.folder", level="ERROR"):
            tracks = get_tracks_from_folder(self.folder)
        self.assertEqual([track["service_id"] for track in tracks], [str(successful)])

    def test_empty_folder_returns_empty_list(self):
        self.assertEqual(get_tracks_from_folder(self.folder), [])
        self.extract.assert_not_called()

    def test_invalid_folder_is_rejected(self):
        with self.assertRaises(NotADirectoryError):
            get_tracks_from_folder(self.folder / "missing")

    def test_cli_passes_folder_and_previews_normalized_tracks(self):
        track = {"title": "White Flag", "artists": ["Dido"], "album": "Life for Rent"}
        with patch("sys.argv", ["check_folder.py", str(self.folder), "--recursive"]), \
             patch("check_folder.logging.basicConfig"), \
             patch("check_folder.get_tracks_from_folder", return_value=[track]) as fetch:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                check_folder.main()
        fetch.assert_called_once_with(str(self.folder), recursive=True)
        self.assertIn("Life for Rent", output.getvalue())
