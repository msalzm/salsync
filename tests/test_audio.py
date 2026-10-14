import contextlib
from concurrent.futures import ThreadPoolExecutor
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from mutagen.id3 import APIC, ID3, TALB, TCON, TDRC, TIT2
from mutagen.mp3 import HeaderNotFoundError, MP3

from audio import build_filename, complete_download, finish_download


# Eight MPEG-1 layer III frames, 128 kbps / 44.1 kHz, without an ID3 header.
MP3_AUDIO = (bytes.fromhex("fffb9000") + bytes(413)) * 8
TRACK = {"title": "White Flag", "artists": ["Dido"], "album": "Life for Rent",
         "release_year": 2003}


class AudioTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name).resolve()
        self.source = self.folder / "peer download.mp3"
        self.source.write_bytes(MP3_AUDIO)

    def test_untagged_download_gets_name_and_only_the_requested_tags(self):
        before = MP3(self.source).info
        path = finish_download(self.source, TRACK)
        self.assertEqual(path.name, "Dido - White Flag.mp3")
        self.assertFalse(self.source.exists())
        tags = ID3(path)
        self.assertEqual(tags.version, (2, 4, 0))
        self.assertEqual(set(tags.keys()), {"TIT2", "TPE1", "TALB", "TDRC"})
        self.assertEqual(tags["TIT2"].text, ["White Flag"])
        self.assertEqual(tags["TPE1"].text, ["Dido"])
        self.assertEqual(tags["TALB"].text, ["Life for Rent"])
        self.assertEqual(str(tags["TDRC"].text[0]), "2003")
        self.assertTrue(path.read_bytes().endswith(MP3_AUDIO))
        self.assertEqual(MP3(path).info.length, before.length)
        self.assertEqual(MP3(path).info.bitrate, before.bitrate)

    def test_multiple_artists_unicode_and_punctuation_keep_exact_tag_values(self):
        track = {**TRACK, "artists": ["Björk", "Guest / Artist"],
                 "title": 'Song: "One"? / Two; Three', "album": "Álbum"}
        path = finish_download(self.source, track)
        self.assertTrue(path.name.startswith("Björk & Guest - Artist - "))
        self.assertFalse(any(character in path.name for character in '<>:"/\\|?*;'))
        tags = ID3(path)
        self.assertEqual(tags["TIT2"].text, [track["title"]])
        self.assertEqual(tags["TPE1"].text, track["artists"])
        self.assertEqual(tags["TALB"].text, ["Álbum"])

    def test_missing_album_and_year_preserve_existing_fields_and_artwork(self):
        tags = ID3()
        tags.add(TIT2(encoding=3, text=["Incorrect title"]))
        tags.add(TALB(encoding=3, text=["Existing album"]))
        tags.add(TDRC(encoding=3, text=["2001-05-02"]))
        tags.add(TCON(encoding=3, text=["Existing genre"]))
        tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="cover", data=b"cover image"))
        tags.save(self.source)
        path = finish_download(self.source, {**TRACK, "album": None, "release_year": None})
        tags = ID3(path)
        self.assertEqual(tags["TIT2"].text, ["White Flag"])
        self.assertEqual(tags["TALB"].text, ["Existing album"])
        self.assertEqual(str(tags["TDRC"].text[0]), "2001-05-02")
        self.assertEqual(tags["TCON"].text, ["Existing genre"])
        self.assertEqual(tags.getall("APIC")[0].data, b"cover image")

    def test_collision_preserves_existing_file_and_repeat_run_retains_suffix(self):
        existing = self.folder / "Dido - White Flag.mp3"
        existing.write_bytes(b"unrelated existing file")
        path = finish_download(self.source, TRACK)
        self.assertEqual(path.name, "Dido - White Flag (2).mp3")
        self.assertEqual(existing.read_bytes(), b"unrelated existing file")
        repeated = finish_download(path, {**TRACK, "release_year": 2004})
        self.assertEqual(repeated, path)
        self.assertEqual(str(ID3(path)["TDRC"].text[0]), "2004")
        self.assertEqual(len(list(self.folder.glob("*.mp3"))), 2)

    def test_tagging_failure_preserves_original_and_cleans_temporary_copy(self):
        with patch("audio.tag_downloaded_track", side_effect=OSError("Cannot save tags")):
            with self.assertRaisesRegex(OSError, "Cannot save tags"):
                finish_download(self.source, TRACK)
        self.assertEqual(self.source.read_bytes(), MP3_AUDIO)
        self.assertEqual(list(self.folder.iterdir()), [self.source])

    def test_corrupt_mp3_is_retained_and_does_not_become_a_tag_only_file(self):
        self.source.write_bytes(b"not MPEG audio")
        with self.assertRaises(HeaderNotFoundError):
            finish_download(self.source, TRACK)
        self.assertEqual(self.source.read_bytes(), b"not MPEG audio")
        self.assertEqual(list(self.folder.iterdir()), [self.source])

    def test_failure_to_remove_source_rolls_back_new_destination(self):
        unlink = Path.unlink

        def fail_source(path, *args, **kwargs):
            if path == self.source:
                raise PermissionError("Original cannot be removed")
            return unlink(path, *args, **kwargs)

        with patch("pathlib.Path.unlink", fail_source), self.assertRaises(PermissionError):
            finish_download(self.source, TRACK)
        self.assertEqual(self.source.read_bytes(), MP3_AUDIO)
        self.assertFalse((self.folder / "Dido - White Flag.mp3").exists())

    def test_failed_final_rename_removes_reservation_and_retains_original(self):
        with patch("audio.os.replace", side_effect=OSError("Rename failed")), \
                self.assertRaisesRegex(OSError, "Rename failed"):
            finish_download(self.source, TRACK)
        self.assertEqual(self.source.read_bytes(), MP3_AUDIO)
        self.assertEqual(list(self.folder.iterdir()), [self.source])

    def test_concurrent_completions_reserve_different_filenames(self):
        second = self.folder / "second download.mp3"
        second.write_bytes(MP3_AUDIO)
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda path: finish_download(path, TRACK),
                                        [self.source, second]))
        self.assertEqual({path.name for path in results},
                         {"Dido - White Flag.mp3", "Dido - White Flag (2).mp3"})
        self.assertTrue(all(path.read_bytes().endswith(MP3_AUDIO) for path in results))
        self.assertEqual(len(list(self.folder.iterdir())), 2)

    def test_long_unicode_filename_fits_a_common_filesystem_component(self):
        name = build_filename({**TRACK, "title": "音楽" * 200})
        self.assertLessEqual(len(name.encode("utf-8")), 224)
        path = finish_download(self.source, {**TRACK, "title": "音楽" * 200})
        self.assertEqual(ID3(path)["TIT2"].text, ["音楽" * 200])

    def test_unknown_optional_fields_do_not_create_empty_tags(self):
        path = finish_download(self.source, {"title": "Song", "artists": ["Artist"]})
        self.assertEqual(set(ID3(path).keys()), {"TIT2", "TPE1"})


class CompletionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name).resolve()
        self.output = self.folder / "downloads"
        self.output.mkdir()
        self.source = self.output / "peer.mp3"
        self.source.write_bytes(MP3_AUDIO)
        self.manifest = self.folder / "tracks.json"
        self.manifest.write_text(json.dumps({"tracks": [TRACK], "output_dir": str(self.output)}))

    def call_hook(self, item=1, source=None):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            code = complete_download(self.manifest, item, source or self.source)
        report = json.loads((self.folder / f"result-{item}.json").read_text())
        return code, output.getvalue().strip(), report

    def test_success_reports_final_path_for_sockseek_index(self):
        code, output, report = self.call_hook()
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "tagged")
        self.assertEqual(output, f"success;{report['path']}")
        self.assertTrue(Path(report["path"]).is_file())

    def test_unknown_item_never_tags_a_different_track(self):
        _, output, report = self.call_hook(item=0)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(self.source.read_bytes(), MP3_AUDIO)
        self.assertEqual(output, f"ignored;{self.source}")

    def test_outside_file_and_symlink_to_original_library_are_untouched(self):
        original = self.folder / "original.mp3"
        original.write_bytes(MP3_AUDIO)
        symlink = self.output / "linked.mp3"
        symlink.symlink_to(original)
        for source in (original, symlink):
            with self.subTest(source=source):
                _, _, report = self.call_hook(source=source)
                self.assertEqual(report["status"], "failed")
                self.assertEqual(original.read_bytes(), MP3_AUDIO)

    def test_failed_tagging_retains_original_index_path_and_reports_error(self):
        self.source.write_bytes(b"corrupt download")
        code, output, report = self.call_hook()
        self.assertEqual(code, 0)
        self.assertEqual(output, f"ignored;{self.source}")
        self.assertEqual(report["status"], "failed")
        self.assertTrue(report["error"])
        self.assertEqual(self.source.read_bytes(), b"corrupt download")
