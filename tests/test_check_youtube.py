import contextlib
import csv
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

import check_youtube


TRACK = {
    "service": "youtube", "service_id": "video-1",
    "url": "https://www.youtube.com/watch?v=video-1",
    "title": "White Flag", "artists": ["Dido"], "album": "Life for Rent",
}


class CheckYouTubeTests(unittest.TestCase):
    def setUp(self):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        token = stack.enter_context(patch.object(check_youtube, "TOKEN_FILE"))
        token.exists.return_value = True
        stack.enter_context(patch.object(
            check_youtube.Credentials, "from_authorized_user_file",
            return_value=Mock(valid=True),
        ))
        self.build = stack.enter_context(patch.object(check_youtube, "build"))
        stack.enter_context(patch.object(check_youtube, "get_youtube_playlists", return_value=[
            {"id": "playlist-1", "name": "salsync"},
            {"id": "playlist-2", "name": "Other playlist"},
        ]))
        self.fetch = stack.enter_context(patch.object(
            check_youtube, "get_tracks_from_playlist", return_value=[TRACK, TRACK],
        ))
        stack.enter_context(contextlib.redirect_stdout(io.StringIO()))

    def test_search_and_download_pass_normalized_tracks_to_sockseek(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory).resolve()
            config = folder / "sockseek.conf"
            config.write_text("username = example\npassword = example\n")
            csv_path = folder / "youtube.csv"
            for mode in ("--search", "--download"):
                argv = ["check_youtube.py", mode, "--limit", "1",
                        "--sockseek-config", str(config), "--sockseek-csv", str(csv_path),
                        "--download-dir", str(folder / "downloads")]
                with self.subTest(mode=mode), patch("sys.argv", argv), \
                        patch("sockseek.RUN_DIR", folder / "runs"), \
                        patch("sockseek.shutil.which", return_value="/fake/sockseek"), \
                        patch("sockseek.subprocess.run", return_value=subprocess.CompletedProcess(
                            args=[], returncode=0,
                        )) as run:
                    check_youtube.main()
                command = run.call_args.args[0]
                self.assertEqual(command[0], "/fake/sockseek")
                self.assertEqual(command[1], str(csv_path))
                self.assertEqual(run.call_args.kwargs, {"check": True})
                self.assertEqual("--print" in command, mode == "--search")
                self.assertEqual("--no-write-index" in command, mode == "--search")
                if mode == "--search":
                    self.assertEqual(command[command.index("--print") + 1], "results-full")
                with csv_path.open(encoding="utf-8", newline="") as handle:
                    self.assertEqual(list(csv.DictReader(handle)), [
                        {"artist": "Dido", "title": "White Flag", "album": "Life for Rent"},
                    ])
        self.fetch.assert_called_with(self.build.return_value, "playlist-1")

    def test_default_run_only_normalizes_and_previews(self):
        with patch("sys.argv", ["check_youtube.py"]), \
                patch("sockseek.run_sockseek") as run:
            check_youtube.main()
        run.assert_not_called()
        self.fetch.assert_called_once_with(self.build.return_value, "playlist-1")

    def test_playlist_option_selects_named_playlist(self):
        with patch("sys.argv", ["check_youtube.py", "--playlist", "Other playlist"]):
            check_youtube.main()
        self.fetch.assert_called_once_with(self.build.return_value, "playlist-2")

    def test_invalid_options_are_rejected_before_authentication(self):
        for options in (["--search", "--download"], ["--search", "--limit", "invalid"]):
            with self.subTest(options=options), \
                    patch("sys.argv", ["check_youtube.py", *options]), \
                    contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                check_youtube.main()
        self.build.assert_not_called()
        self.fetch.assert_not_called()

    def test_missing_playlist_reports_error_without_searching(self):
        with patch("sys.argv", ["check_youtube.py", "--playlist", "missing", "--search"]), \
                patch("sockseek.run_sockseek") as run, \
                contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            check_youtube.main()
        run.assert_not_called()
        self.fetch.assert_not_called()
