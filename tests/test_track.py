import unittest

from src.track import find_match, normalize_spotify_track, tracks_to_add


class SpotifyTrackTests(unittest.TestCase):
    def test_normalizes_track_with_two_artists(self):
        raw = {
            "id": "sample-001",
            "name": "Blue Lights",
            "artists": [
                {"name": "Mira Echo"},
                {"name": "Abba"},
            ],
            "album": {"name": "Night Walks"},
            "external_urls": {
                "spotify": "https://open.spotify.com/track/sample-001"
            },
        }

        expected = {
            "service": "spotify",
            "url": "https://open.spotify.com/track/sample-001",
            "service_id": "sample-001",
            "title": "Blue Lights",
            "artists": ["Mira Echo", "Abba"],
            "album": "Night Walks",
        }

        self.assertEqual(normalize_spotify_track(raw), expected)


class TrackMatchingTests(unittest.TestCase):
    def test_matches_despite_capitalization_and_outer_spaces(self):
        track = {
            "title": " Blue Lights ",
            "artists": ["Jorja Smith"],
        }
        candidate = {
            "title": "blue lights",
            "artists": [" JORJA SMITH "],
        }

        self.assertIs(find_match(track, [candidate]), candidate)

    def test_does_not_match_a_different_artist(self):
        track = {
            "title": "Blue Lights",
            "artists": ["Jorja Smith"],
        }
        candidate = {
            "title": "Blue Lights",
            "artists": ["Another Artist"],
        }

        self.assertIsNone(find_match(track, [candidate]))

    def test_does_not_match_a_different_title(self):
        track = {
            "title": "Blue Lights",
            "artists": ["Jorja Smith"],
        }
        candidate = {
            "title": "Green Lights",
            "artists": ["Jorja Smith"],
        }

        self.assertIsNone(find_match(track, [candidate]))

    def test_continues_searching_after_a_wrong_candidate(self):
        track = {
            "title": "Blue Lights",
            "artists": ["Jorja Smith"],
        }
        wrong = {
            "title": "Blue Lights",
            "artists": ["Another Artist"],
        }
        correct = {
            "title": "blue lights",
            "artists": ["JORJA SMITH"],
        }

        self.assertIs(find_match(track, [wrong, correct]), correct)

    def test_returns_none_for_no_candidates(self):
        track = {
            "title": "Blue Lights",
            "artists": ["Jorja Smith"],
        }

        self.assertIsNone(find_match(track, []))


class TracksToAddTests(unittest.TestCase):
    def test_returns_tracks_not_in_destination(self):
        source = [
            {"title": "Blue Lights", "artists": ["Jorja Smith"]},
            {"title": "Green Lights", "artists": ["Another Artist"]},
        ]
        destination = [
            {"title": "blue lights", "artists": ["JORJA SMITH"]},
        ]

        self.assertEqual(
            source[1:],
            tracks_to_add(source, destination),
        )

    def test_returns_empty_list_if_all_tracks_are_in_destination(self):
        source = [
            {"title": "Blue Lights", "artists": ["Jorja Smith"]},
        ]
        destination = [
            {"title": "blue lights", "artists": ["JORJA SMITH"]},
        ]

        self.assertEqual([], tracks_to_add(source, destination))

    def test_returns_empty_list_if_source_is_empty(self):
        self.assertEqual([], tracks_to_add([], []))

    def test_every_source_matches_every_destination(self):
        source = [
            {"title": "Blue Lights", "artists": ["Jorja Smith"]},
            {"title": "Green Lights", "artists": ["Another Artist"]},
        ]
        destination = [
            {"title": "blue lights", "artists": ["JORJA SMITH"]},
            {"title": "green lights", "artists": ["ANOTHER ARTIST"]},
        ]

        self.assertEqual([], tracks_to_add(source, destination))

    