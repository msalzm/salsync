import unittest

from src.track import normalize_spotify_track


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