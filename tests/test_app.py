import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from app import AppState, handler_for
import app_worker


TRACK = {"service": "youtube", "service_id": "video", "url": "https://youtube.com/watch?v=video",
         "title": "Subra", "artists": ["Volodymyr Gnatenko"],
         "album": "The Chants of the Holy Oyster", "release_year": 2023}


class AppTests(unittest.TestCase):
    def test_selected_tracks_come_from_server_collection(self):
        state = AppState()
        state.tracks = [TRACK, {**TRACK, "title": "Other"}]
        with patch("app.threading.Thread") as thread:
            state.start({"action": "download", "indices": [1, 1], "tracks": [TRACK]})
        request = thread.call_args.kwargs["args"][0]
        self.assertEqual(request["tracks"], [{**TRACK, "title": "Other"}])
        self.assertEqual(state.job["status"], "running")

    def test_rejects_invalid_selections_before_launch(self):
        for indices in ([], [-1], [True], [0], "all"):
            with self.subTest(indices=indices), patch("app.threading.Thread") as thread:
                with self.assertRaises(ValueError):
                    AppState().start({"action": "download", "indices": indices})
                thread.assert_not_called()

    def test_blocks_overlapping_jobs(self):
        state = AppState()
        with patch("app.threading.Thread"):
            state.start({"action": "playlists", "source": "youtube"})
            with self.assertRaisesRegex(ValueError, "already running"):
                state.start({"action": "playlists", "source": "spotify"})

    def test_worker_result_updates_collection_and_captures_logs(self):
        state = AppState()
        process = Mock()
        process.stdout = io.StringIO("Finding releases…\nFinished.\n")
        process.wait.return_value = 0
        process.__enter__ = Mock(return_value=process)
        process.__exit__ = Mock(return_value=False)
        with tempfile.TemporaryDirectory() as temporary:
            (Path(temporary) / "result.json").write_text(json.dumps({"tracks": [TRACK]}))
            with patch("app.tempfile.TemporaryDirectory") as directory, patch("app.subprocess.Popen", return_value=process):
                directory.return_value.__enter__.return_value = temporary
                state.run({"action": "normalize", "source": "youtube"})
        self.assertEqual(state.tracks, [TRACK])
        self.assertEqual(state.job["status"], "done")
        self.assertIn("Finding releases…", state.job["logs"])

    def test_partial_sockseek_failure_is_not_reported_as_success(self):
        state = AppState()
        process = Mock()
        process.stdout = io.StringIO("2 succeeded, 1 failed\n")
        process.wait.return_value = 1
        process.__enter__ = Mock(return_value=process)
        process.__exit__ = Mock(return_value=False)
        with patch("app.subprocess.Popen", return_value=process):
            state.run({"action": "download", "tracks": [TRACK]})
        self.assertEqual(state.job["status"], "error")
        self.assertIn("2 succeeded, 1 failed", state.job["logs"])

    def test_organize_only_accepts_local_tracks(self):
        state = AppState()
        state.tracks = [TRACK]
        with patch("app.threading.Thread") as thread, self.assertRaisesRegex(ValueError, "local folder"):
            state.start({"action": "organize", "indices": [0]})
        thread.assert_not_called()

    def test_partial_organize_keeps_successful_renames_and_reports_error(self):
        local = {**TRACK, "service": "local", "service_id": "/music/a.mp3", "url": "file:///music/a.mp3"}
        failed = {**local, "service_id": "/music/b.mp3", "url": "file:///music/b.mp3"}
        renamed = {**local, "service_id": "/music/Volodymyr Gnatenko - Subra.mp3"}
        state = AppState()
        state.tracks = [local, failed]
        process = Mock()
        process.stdout = io.StringIO("Error: 1 file(s) could not be tagged and renamed.\n")
        process.wait.return_value = 1
        process.__enter__ = Mock(return_value=process)
        process.__exit__ = Mock(return_value=False)
        with tempfile.TemporaryDirectory() as temporary:
            (Path(temporary) / "result.json").write_text(json.dumps({
                "organized": [[local["service_id"], renamed], [failed["service_id"], failed]], "failed": 1,
            }))
            with patch("app.tempfile.TemporaryDirectory") as directory, patch("app.subprocess.Popen", return_value=process):
                directory.return_value.__enter__.return_value = temporary
                state.run({"action": "organize", "tracks": [local, failed]})
        self.assertEqual(state.tracks, [renamed, failed])
        self.assertEqual(state.job["status"], "error")

    def test_download_reuses_tagging_adapter_with_reviewed_metadata(self):
        with patch("sockseek.run_sockseek") as run:
            app_worker.execute({"action": "download", "tracks": [TRACK], "options": {
                "binary": "/some path/sockseek", "config": "/some path/config", "output_dir": "/music",
            }}, Path("/unused"))
        self.assertEqual(run.call_args.args, ([TRACK],))
        self.assertTrue(run.call_args.kwargs["download"])
        self.assertEqual(run.call_args.kwargs["executable"], "/some path/sockseek")
        self.assertEqual(run.call_args.kwargs["output_dir"], "/music")

    def test_folder_uses_filename_normalizer(self):
        with patch("folder.get_tracks_from_folder", return_value=[TRACK]) as normalize:
            result = app_worker.execute({"action": "normalize", "source": "folder",
                                         "folder": "/music", "recursive": True}, Path("/unused"))
        normalize.assert_called_once_with("/music", recursive=True)
        self.assertEqual(result, {"tracks": [TRACK]})

    def test_post_requires_app_token(self):
        state = AppState()
        handler = object.__new__(handler_for(state))
        handler.path = "/api/tasks"
        handler.headers = {}
        handler.send = Mock()
        handler.do_POST()
        self.assertEqual(handler.send.call_args.args[0], 403)
        self.assertEqual(state.job["status"], "idle")

    def test_spotify_missing_client_id_is_actionable(self):
        with patch.dict("os.environ", {}, clear=True), self.assertRaisesRegex(ValueError, "SPOTIFY_CLIENT_ID"):
            app_worker.spotify_client()

    def test_real_folder_worker_completes_without_modifying_original_files(self):
        state = AppState()
        with tempfile.TemporaryDirectory() as temporary:
            original = Path(temporary) / "notes.txt"
            original.write_text("Keep this file.")
            state.run({"action": "normalize", "source": "folder", "folder": temporary})
            self.assertEqual(original.read_text(), "Keep this file.")
        self.assertEqual(state.job["status"], "done")
        self.assertEqual(state.tracks, [])

    def test_http_page_and_state_are_served_without_network_dependencies(self):
        state = AppState()

        class Connection:
            def __init__(self, path):
                self.input = io.BytesIO(f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n".encode())
                self.output = bytearray()

            def makefile(self, *args):
                return self.input

            def sendall(self, data):
                self.output.extend(data)

        for path in ("/", "/app.js", "/style.css", "/api/state"):
            with self.subTest(path=path):
                connection = Connection(path)
                handler_for(state)(connection, ("127.0.0.1", 12345), Mock())
                self.assertIn(b"200 OK", connection.output)
                self.assertNotIn(b"__APP_TOKEN__", connection.output)
                self.assertNotIn(b"__DEFAULTS__", connection.output)
                if path == "/":
                    self.assertIn(state.token.encode(), connection.output)
                if path == "/api/state":
                    self.assertNotIn(state.token.encode(), connection.output)
