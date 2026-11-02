from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, call, patch

import requests

from src.discogs import find_first_release, get_discogs_token, request_discogs


def response(data, status_code=200, headers=None):
    result = Mock()
    result.status_code = status_code
    result.headers = headers or {}
    result.json.return_value = data
    if status_code >= 400:
        result.raise_for_status.side_effect = requests.HTTPError(
            f"Discogs HTTP {status_code}", response=result,
        )
    return result


def release(release_id, year=2003, title="Life for Rent", descriptions=("Album",)):
    return {
        "id": release_id,
        "title": title,
        "year": year,
        "uri": f"https://www.discogs.com/release/{release_id}",
        "artists": [{"name": "Dido"}],
        "formats": [{"name": "CD", "descriptions": list(descriptions)}],
        "tracklist": [{"title": "White Flag"}],
    }


def search_page(ids, pages=1):
    return {"results": [{"id": value} for value in ids], "pagination": {"pages": pages}}


class DiscogsRequestTests(unittest.TestCase):
    def setUp(self):
        self.session = Mock()
        self.url = "https://api.discogs.com/database/search"
        sleep_patch = patch("src.discogs.time.sleep")
        self.sleep = sleep_patch.start()
        self.addCleanup(sleep_patch.stop)
        log_patch = patch("src.discogs.logger.warning")
        self.warning = log_patch.start()
        self.addCleanup(log_patch.stop)

    def test_success_returns_without_waiting(self):
        success = response({})
        self.session.get.return_value = success
        params = {"track": "White Flag", "page": 2}
        self.assertIs(request_discogs(self.session, self.url, params=params), success)
        self.session.get.assert_called_once_with(self.url, params=params, timeout=20)
        self.sleep.assert_not_called()

    def test_rate_limit_honors_retry_after_and_repeats_same_request(self):
        limited = response({}, 429, {"Retry-After": " 7 "})
        success = response({})
        self.session.get.side_effect = [limited, success]
        params = {"track": "White Flag", "page": 2}
        self.assertIs(request_discogs(self.session, self.url, params=params), success)
        self.assertEqual(self.session.get.call_args_list, [
            call(self.url, params=params, timeout=20),
            call(self.url, params=params, timeout=20),
        ])
        self.sleep.assert_called_once_with(7)
        limited.close.assert_called_once()
        self.warning.assert_called_once()

    def test_retry_after_accepts_http_dates_and_past_dates(self):
        for timestamp, expected in ((100, 20), (130, 0)):
            with self.subTest(timestamp=timestamp):
                self.sleep.reset_mock()
                self.session.get.side_effect = [
                    response({}, 429, {"Retry-After": "Thu, 01 Jan 1970 00:02:00 GMT"}),
                    response({}),
                ]
                with patch("src.discogs.time.time", return_value=timestamp):
                    request_discogs(self.session, self.url)
                self.sleep.assert_called_once_with(expected)

    def test_missing_or_invalid_retry_after_uses_backoff(self):
        for headers in ({}, {"Retry-After": ""}, {"Retry-After": "invalid"},
                        {"Retry-After": "-5"}, {"Retry-After": "NaN"}):
            with self.subTest(headers=headers):
                self.sleep.reset_mock()
                self.session.get.side_effect = [response({}, 429, headers), response({})]
                request_discogs(self.session, self.url)
                self.sleep.assert_called_once_with(60)

    def test_repeated_rate_limits_stop_after_three_retries(self):
        limited = response({}, 429)
        self.session.get.return_value = limited
        with self.assertRaises(requests.HTTPError) as caught:
            request_discogs(self.session, self.url)
        self.assertIs(caught.exception.response, limited)
        self.assertEqual(self.session.get.call_count, 4)
        self.assertEqual(self.sleep.call_args_list, [call(60), call(120), call(240)])

    def test_zero_retries_raises_immediately(self):
        self.session.get.return_value = response({}, 429)
        with self.assertRaises(requests.HTTPError):
            request_discogs(self.session, self.url, max_retries=0)
        self.session.get.assert_called_once()
        self.sleep.assert_not_called()

    def test_other_http_errors_are_not_retried(self):
        for status in (400, 401, 403, 404, 500):
            with self.subTest(status=status):
                self.session.get.reset_mock()
                self.session.get.return_value = response({}, status)
                with self.assertRaises(requests.HTTPError):
                    request_discogs(self.session, self.url)
                self.session.get.assert_called_once()
                self.sleep.assert_not_called()

    def test_connection_failures_are_not_retried(self):
        self.session.get.side_effect = requests.Timeout("Discogs timed out")
        with self.assertRaises(requests.Timeout):
            request_discogs(self.session, self.url)
        self.session.get.assert_called_once()
        self.sleep.assert_not_called()

    def test_invalid_retry_counts_are_rejected_before_request(self):
        for count in (-1, True, 1.5, None):
            with self.subTest(count=count), self.assertRaises(ValueError):
                request_discogs(self.session, self.url, max_retries=count)
        self.session.get.assert_not_called()
        self.sleep.assert_not_called()


class DiscogsTokenTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.token_file = Path(temp.name) / ".discogs-token"
        token_patch = patch("src.discogs.TOKEN_FILE", self.token_file)
        env_patch = patch.dict("os.environ", {}, clear=True)
        token_patch.start()
        env_patch.start()
        self.addCleanup(token_patch.stop)
        self.addCleanup(env_patch.stop)

    def test_reads_local_token_file_and_strips_whitespace(self):
        self.token_file.write_text("  local-test-token\n", encoding="utf-8")
        self.assertEqual(get_discogs_token(), "local-test-token")

    def test_environment_takes_precedence_without_reading_file(self):
        with patch.dict("os.environ", {"DISCOGS_TOKEN": " env-test-token "}), \
                patch("pathlib.Path.read_text", side_effect=AssertionError("Do not read file")):
            self.assertEqual(get_discogs_token(), "env-test-token")

    def test_blank_environment_falls_back_to_file_for_authentication(self):
        self.token_file.write_text("local-test-token\n", encoding="utf-8")
        with patch.dict("os.environ", {"DISCOGS_TOKEN": " "}), \
                patch("src.discogs.requests.Session") as session:
            session.return_value.get.return_value.json.return_value = search_page([])
            self.assertIsNone(find_first_release("White Flag", "Dido"))
        self.assertEqual(session.return_value.headers.update.call_args.args[0]["Authorization"],
                         "Discogs token=local-test-token")

    def test_missing_or_empty_token_reports_configuration_needed(self):
        for content in (None, " \n"):
            with self.subTest(content=content):
                if content is not None:
                    self.token_file.write_text(content, encoding="utf-8")
                with self.assertRaisesRegex(KeyError, "Set DISCOGS_TOKEN"):
                    get_discogs_token()


class DiscogsReleaseTests(unittest.TestCase):
    def setUp(self):
        self.session = Mock()
        session_patch = patch("src.discogs.requests.Session", return_value=self.session)
        token_patch = patch.dict("os.environ", {"DISCOGS_TOKEN": "mock-test-token"})
        session_patch.start()
        token_patch.start()
        self.addCleanup(session_patch.stop)
        self.addCleanup(token_patch.stop)

    def lookup(self, releases):
        self.session.get.side_effect = [
            response(search_page([item["id"] for item in releases])),
            *[response(item) for item in releases],
        ]
        return find_first_release("White Flag", "Dido")

    def test_prefers_album_to_earlier_single_and_returns_compatible_metadata(self):
        result = self.lookup([
            release(1, 2002, "White Flag", ("Single",)),
            release(2),
        ])
        self.assertEqual(result, {
            "title": "White Flag", "artists": ["Dido"], "album": "Life for Rent",
            "release_date": "2003", "release_id": 2, "source": "discogs",
            "url": "https://www.discogs.com/release/2",
        })

    def test_selects_earliest_album_across_editions_in_same_master(self):
        later, earlier = release(1, 2020), release(2, 2003)
        later["master_id"] = earlier["master_id"] = 100
        self.assertEqual(self.lookup([later, earlier])["release_id"], 2)

    def test_selects_earliest_album_across_different_masters(self):
        later, earlier = release(1, 2020), release(2, 2003)
        later["master_id"], earlier["master_id"] = 100, 200
        self.assertEqual(self.lookup([later, earlier])["release_id"], 2)

    def test_rejects_wrong_artist_and_wrong_track_title(self):
        wrong_artist, wrong_title = release(1), release(2)
        wrong_artist["artists"] = [{"name": "Other Artist"}]
        wrong_title["tracklist"] = [{"title": "White Flag (Live)"}]
        self.assertIsNone(self.lookup([wrong_artist, wrong_title]))

    def test_accepts_track_artist_on_compilation_and_cleans_discogs_artist_suffix(self):
        compilation = release(1, descriptions=("Album", "Compilation"))
        compilation["artists"] = [{"name": "Various"}]
        compilation["tracklist"][0]["artists"] = [{"name": "Dido (2)"}]
        result = self.lookup([compilation])
        self.assertEqual(result["artists"], ["Dido"])

    def test_excludes_promos_unofficial_releases_and_undated_editions(self):
        self.assertIsNone(self.lookup([
            release(1, descriptions=("Album", "Promo")),
            release(2, descriptions=("Album", "Unofficial Release")),
            release(3, year=0),
        ]))

    def test_compilation_does_not_override_original_album(self):
        result = self.lookup([
            release(1, 2001, descriptions=("Album", "Compilation")), release(2, 2003),
        ])
        self.assertEqual(result["release_id"], 2)

    def test_falls_back_to_first_single_when_no_album_exists(self):
        result = self.lookup([
            release(1, 2004, "Single", ("Single",)),
            release(2, 2003, "Original Single", ("Single",)),
        ])
        self.assertEqual(result["album"], "Original Single")

    def test_checks_all_search_pages(self):
        self.session.get.side_effect = [
            response(search_page([1], pages=2)), response(release(1, descriptions=("Single",))),
            response(search_page([2], pages=2)), response(release(2)),
        ]
        result = find_first_release("White Flag", "Dido")
        self.assertEqual(result["release_id"], 2)
        calls = self.session.get.call_args_list
        self.assertEqual(calls[2].kwargs["params"]["page"], 2)
        self.assertTrue(all(item.kwargs["timeout"] == 20 for item in calls))

    def test_returns_none_for_empty_search(self):
        self.assertIsNone(self.lookup([]))

    def test_search_and_release_requests_both_recover_from_rate_limits(self):
        self.session.get.side_effect = [
            response({}, 429, {"Retry-After": "2"}),
            response(search_page([1])),
            response({}, 429, {"Retry-After": "3"}),
            response(release(1)),
        ]
        with patch("src.discogs.time.sleep") as sleep, \
                self.assertLogs("src.discogs", level="WARNING"):
            result = find_first_release("White Flag", "Dido")
        self.assertEqual(result["release_id"], 1)
        self.assertEqual(sleep.call_args_list, [call(2), call(3)])
        calls = self.session.get.call_args_list
        self.assertEqual(calls[0], calls[1])
        self.assertEqual(calls[2], calls[3])
        self.assertEqual(calls[2].args[0], "https://api.discogs.com/releases/1")

    def test_http_errors_propagate(self):
        failed = response({})
        failed.raise_for_status.side_effect = requests.HTTPError("Discogs failed")
        self.session.get.return_value = failed
        with self.assertRaises(requests.HTTPError):
            find_first_release("White Flag", "Dido")
