import unittest
from unittest.mock import Mock, call, patch

from src.musicbrainz import find_first_release


def recording(recording_id="recording-1", title="White Flag", artist="Dido"):
    return {
        "id": recording_id,
        "title": title,
        "artist-credit": [{"artist": {"name": artist}}],
    }


def release(release_id="release-1", date="2003-09-01", status="Official",
            release_type="Single", secondary_types=()):
    return {
        "id": release_id, "title": "White Flag", "date": date, "status": status,
        "release-group": {
            "primary-type": release_type,
            "secondary-type-list": list(secondary_types),
        },
    }


class FirstReleaseTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.client.search_recordings.return_value = {
            "recording-list": [recording()], "recording-count": 1,
        }
        self.client.browse_releases.return_value = {
            "release-list": [release()], "release-count": 1,
        }
        self.client.get_recording_by_id.return_value = {
            "recording": {
                **recording(), "length": "241000", "isrc-list": ["GBTEST000001"],
            },
        }
        self.client.get_release_by_id.return_value = {
            "release": {
                **release(),
                "country": "GB",
                "release-group": {"id": "group-1", "primary-type": "Single"},
                "label-info-list": [
                    {"label": {"name": "Test Label"}, "catalog-number": "TEST001"},
                ],
                "medium-list": [{"format": "CD"}, {"format": "CD"}],
            },
        }

    def lookup(self, title="White Flag", artist="Dido"):
        return find_first_release(title, artist, client=self.client)

    def test_returns_release_and_recording_metadata(self):
        self.assertEqual(self.lookup(), {
            "title": "White Flag",
            "artists": ["Dido"],
            "album": "White Flag",
            "release_date": "2003-09-01",
            "country": "GB",
            "release_type": "Single",
            "labels": [{"name": "Test Label", "catalog_number": "TEST001"}],
            "formats": ["CD"],
            "duration_ms": 241000,
            "isrcs": ["GBTEST000001"],
            "recording_id": "recording-1",
            "recording_comment": None,
            "release_id": "release-1",
            "release_group_id": "group-1",
            "source": "musicbrainz",
            "url": "https://musicbrainz.org/release/release-1",
        })

    def test_chooses_earliest_across_recordings_and_unsorted_releases(self):
        self.client.search_recordings.return_value = {
            "recording-list": [recording("new"), recording("original")],
            "recording-count": 2,
        }
        self.client.browse_releases.side_effect = [
            {"release-list": [release("reissue", "2020")], "release-count": 1},
            {"release-list": [release("album", "2003-09-29"), release()],
             "release-count": 2},
        ]
        result = self.lookup()
        self.assertEqual(result["release_id"], "release-1")
        self.client.get_recording_by_id.assert_called_once_with(
            "original", includes=["artist-credits", "isrcs"],
        )

    def test_checks_release_pages_after_first_hundred_editions(self):
        self.client.browse_releases.side_effect = [
            {"release-list": [release(f"reissue-{n}", "2020") for n in range(100)],
             "release-count": "101"},
            {"release-list": [release()], "release-count": "101"},
        ]
        self.assertEqual(self.lookup()["release_id"], "release-1")
        self.assertEqual(self.client.browse_releases.call_args_list, [
            call(recording="recording-1", release_status=["official"],
                 includes=["release-groups"], limit=100, offset=0),
            call(recording="recording-1", release_status=["official"],
                 includes=["release-groups"], limit=100, offset=100),
        ])

    def test_prefers_later_album_over_earlier_single_and_ep(self):
        album = release("album", "2003-09-29", release_type="Album")
        self.client.browse_releases.return_value = {
            "release-list": [release(), release("ep", "2003-09-10", release_type="EP"), album],
            "release-count": 3,
        }
        self.client.get_release_by_id.return_value = {
            "release": {**album, "title": "Life for Rent"},
        }
        result = self.lookup()
        self.assertEqual(result["album"], "Life for Rent")
        self.assertEqual(result["release_date"], "2003-09-29")
        self.assertEqual(result["release_type"], "Album")
        self.client.get_release_by_id.assert_called_once_with(
            "album", includes=["artist-credits", "labels", "release-groups", "media"],
        )

    def test_selects_earliest_album_across_recordings(self):
        self.client.search_recordings.return_value = {
            "recording-list": [recording("single-version"), recording("album-version")],
            "recording-count": 2,
        }
        self.client.browse_releases.side_effect = [
            {"release-list": [release(), release("new-album", "2004", release_type="Album")],
             "release-count": 2},
            {"release-list": [release("original-album", "2003-09-29", release_type="Album")],
             "release-count": 1},
        ]
        self.lookup()
        self.assertEqual(self.client.get_recording_by_id.call_args.args[0], "album-version")
        self.assertEqual(self.client.get_release_by_id.call_args.args[0], "original-album")

    def test_compilation_live_and_remix_albums_do_not_override_original_album(self):
        self.client.browse_releases.return_value = {
            "release-list": [
                release(kind, "2000", release_type="Album", secondary_types=[kind])
                for kind in ("Compilation", "Live", "Remix")
            ] + [release("original-album", "2003-09-29", release_type="Album")],
            "release-count": 4,
        }
        self.lookup()
        self.assertEqual(self.client.get_release_by_id.call_args.args[0], "original-album")

    def test_falls_back_to_single_when_album_has_no_date(self):
        self.client.browse_releases.return_value = {
            "release-list": [release(), release("album", None, release_type="Album")],
            "release-count": 2,
        }
        self.assertEqual(self.lookup()["release_id"], "release-1")

    def test_prefers_album_found_on_later_release_page(self):
        self.client.browse_releases.side_effect = [
            {"release-list": [release(f"single-{n}") for n in range(100)],
             "release-count": 101},
            {"release-list": [release("album", "2003-09-29", release_type="Album")],
             "release-count": 101},
        ]
        self.lookup()
        self.assertEqual(self.client.get_release_by_id.call_args.args[0], "album")

    def test_supports_legacy_release_group_type(self):
        album = release("album", "2003-09-29")
        album["release-group"] = {"type": "Album"}
        self.client.browse_releases.return_value = {
            "release-list": [release(), album], "release-count": 2,
        }
        self.lookup()
        self.assertEqual(self.client.get_release_by_id.call_args.args[0], "album")

    def test_checks_later_recording_search_pages(self):
        self.client.search_recordings.side_effect = [
            {"recording-list": [recording(str(n), artist="Other") for n in range(100)],
             "recording-count": 101},
            {"recording-list": [recording()], "recording-count": 101},
        ]
        self.assertIsNotNone(self.lookup())
        self.assertEqual(self.client.search_recordings.call_args.kwargs["offset"], 100)
        self.client.browse_releases.assert_called_once()

    def test_rejects_wrong_artists_and_differently_titled_versions(self):
        self.client.search_recordings.return_value = {
            "recording-list": [recording(artist="Other"),
                               recording(title="White Flag (Live)")],
            "recording-count": 2,
        }
        self.assertIsNone(self.lookup())
        self.client.browse_releases.assert_not_called()

    def test_ignores_capitalization_and_extra_whitespace(self):
        self.assertIsNotNone(self.lookup("  WHITE   flag  ", " DIDO "))

    def test_matches_joined_and_individual_artist_credits(self):
        self.client.search_recordings.return_value["recording-list"][0]["artist-credit"] = [
            {"name": "Dido", "artist": {"name": "Dido"}},
            " feat. ",
            {"name": "Guest", "artist": {"name": "Guest Artist"}},
        ]
        for artist in ("Dido", "Dido feat. Guest", "Guest Artist"):
            with self.subTest(artist=artist):
                self.assertIsNotNone(self.lookup(artist=artist))

    def test_excludes_bootlegs_promotions_unknown_and_invalid_dates(self):
        self.client.browse_releases.return_value = {
            "release-list": [release("bootleg", "1990", "Bootleg"),
                             release("promo", "1991", "Promotion"),
                             release("unknown", None),
                             release("invalid", "2000-02-30"),
                             release("zero", "0000"), release()],
            "release-count": 6,
        }
        self.assertEqual(self.lookup()["release_id"], "release-1")

    def test_preserves_partial_dates_and_sorts_them_chronologically(self):
        self.client.browse_releases.return_value = {
            "release-list": [release("newer", "2004-01-01"), release(date="2003")],
            "release-count": 2,
        }
        self.assertEqual(self.lookup()["release_date"], "2003")
        self.client.browse_releases.return_value["release-list"][1]["date"] = "2003-08"
        self.assertEqual(self.lookup()["release_date"], "2003-08")

    def test_returns_none_when_no_dated_official_releases_exist(self):
        self.client.browse_releases.return_value = {
            "release-list": [release(date=None)], "release-count": 1,
        }
        self.assertIsNone(self.lookup())
        self.client.get_release_by_id.assert_not_called()

    def test_returns_none_for_empty_search(self):
        self.client.search_recordings.return_value = {"recording-list": [], "recording-count": 0}
        self.assertIsNone(self.lookup())

    def test_missing_input_does_not_call_api(self):
        for title, artist in ((None, "Dido"), (" ", "Dido"), ("White Flag", None),
                              ("White Flag", "")):
            with self.subTest(title=title, artist=artist):
                self.assertIsNone(self.lookup(title, artist))
        self.client.set_useragent.assert_not_called()
        self.client.search_recordings.assert_not_called()

    def test_missing_optional_metadata(self):
        self.client.get_recording_by_id.return_value = {"recording": recording()}
        minimal_release = release()
        minimal_release.pop("release-group")
        self.client.get_release_by_id.return_value = {"release": minimal_release}
        result = self.lookup()
        for field in ("country", "release_type", "duration_ms", "release_group_id"):
            self.assertIsNone(result[field])
        for field in ("labels", "formats", "isrcs"):
            self.assertEqual(result[field], [])

    def test_api_failures_propagate(self):
        self.client.search_recordings.side_effect = RuntimeError("API unavailable")
        with self.assertRaisesRegex(RuntimeError, "API unavailable"):
            self.lookup()

    def test_default_client_returns_metadata(self):
        expected = self.lookup()
        with patch("src.musicbrainz.mb", self.client):
            self.assertEqual(find_first_release("White Flag", "Dido"), expected)
