import unittest
from unittest.mock import Mock, patch

from src.track import find_match, normalize_youtube_track
from youtube import get_tracks_from_playlist


def playlist_item(video_id="video-1", title="Dido - White Flag (Official Video)"):
    return {
        "id": "playlist-item-id",
        "contentDetails": {"videoId": video_id},
        "snippet": {"title": title, "videoOwnerChannelTitle": "Dido Official"},
    }


HINT = {"title": "White Flag", "artist": "Dido", "ep_or_album": None}
METADATA = {"title": "White Flag", "artists": ["Dido"], "album": "Life for Rent",
            "release_date": "2003-09-29"}


class YouTubeTrackTests(unittest.TestCase):
    def test_normalized_track_can_match_spotify_track(self):
        track = normalize_youtube_track({**playlist_item(), **METADATA})
        self.assertEqual(track, {
            "service": "youtube",
            "url": "https://www.youtube.com/watch?v=video-1",
            "service_id": "video-1",
            "title": "White Flag",
            "artists": ["Dido"],
            "album": "Life for Rent",
            "release_year": 2003,
        })
        spotify_track = {
            "service": "spotify", "service_id": "spotify-1", "url": "spotify-url",
            "title": "White Flag", "artists": ["Dido"], "album": "Life for Rent",
        }
        self.assertIs(find_match(track, [spotify_track]), spotify_track)

    def test_metadata_supplies_canonical_title_and_multiple_artists(self):
        track = normalize_youtube_track({
            **playlist_item(),
            "title": "Canonical Title", "artists": ["Dido", "Guest"], "album": "Album",
        })
        self.assertEqual(track["title"], "Canonical Title")
        self.assertEqual(track["artists"], ["Dido", "Guest"])

    def test_retains_hint_when_metadata_is_missing_without_guessing_album(self):
        track = normalize_youtube_track({
            **playlist_item(), "title": " White Flag ", "artists": ["Dido"],
            "ep_or_album": "Guessed Album",
        })
        self.assertEqual(track["title"], "White Flag")
        self.assertEqual(track["artists"], ["Dido"])
        self.assertIsNone(track["album"])
        self.assertIsNone(track["release_year"])

    def test_uses_video_id_from_resource_when_content_details_are_missing(self):
        item = {"id": "playlist-item-id", "snippet": {
            "title": "Dido - White Flag", "resourceId": {"videoId": "video-2"},
        }}
        track = normalize_youtube_track({**item, **METADATA})
        self.assertEqual(track["service_id"], "video-2")

    def test_unidentified_items_are_not_normalized(self):
        for fields in ({"title": None, "artists": ["Dido"]},
                       {"title": "White Flag", "artists": []}):
            with self.subTest(fields=fields):
                self.assertIsNone(normalize_youtube_track({**playlist_item(), **fields}))
        self.assertIsNone(normalize_youtube_track({}))


class YouTubePlaylistTests(unittest.TestCase):
    def setUp(self):
        self.youtube = Mock()
        self.items = self.youtube.playlistItems.return_value
        self.first_request = self.items.list.return_value
        self.first_request.execute.return_value = {"items": [playlist_item()]}
        self.items.list_next.return_value = None
        extraction_patch = patch("youtube.extract_track_hint", return_value=HINT)
        metadata_patch = patch("youtube.find_first_release", return_value=METADATA)
        discogs_patch = patch("youtube.find_discogs_release", return_value=None)
        self.extract = extraction_patch.start()
        self.lookup = metadata_patch.start()
        self.discogs_lookup = discogs_patch.start()
        self.addCleanup(extraction_patch.stop)
        self.addCleanup(metadata_patch.stop)
        self.addCleanup(discogs_patch.stop)

    def test_returns_normalized_tracks_from_every_page_in_playlist_order(self):
        second_request = Mock()
        second_request.execute.return_value = {"items": [playlist_item("video-2")]}
        self.items.list_next.side_effect = [second_request, None]
        tracks = get_tracks_from_playlist(self.youtube, "playlist-1")
        self.assertEqual([track["service_id"] for track in tracks], ["video-1", "video-2"])
        self.assertTrue(all(track["album"] == "Life for Rent" for track in tracks))
        self.assertTrue(all(track["release_year"] == 2003 for track in tracks))
        self.assertTrue(all(set(track) == {
            "service", "url", "service_id", "title", "artists", "album", "release_year",
        } for track in tracks))
        self.items.list.assert_called_once_with(
            part="snippet,contentDetails", maxResults=50, playlistId="playlist-1",
        )
        self.extract.assert_called_with("Dido - White Flag (Official Video)", "Dido Official")
        self.lookup.assert_called_with("White Flag", "Dido")
        self.assertEqual(self.extract.call_count, 2)
        self.discogs_lookup.assert_not_called()

    def test_missing_metadata_preserves_track(self):
        self.lookup.return_value = None
        tracks = get_tracks_from_playlist(self.youtube, "playlist-1")
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0]["title"], "White Flag")
        self.assertIsNone(tracks[0]["album"])
        self.discogs_lookup.assert_called_once_with("White Flag", "Dido")

    def test_uses_discogs_metadata_when_musicbrainz_has_no_match(self):
        self.lookup.return_value = None
        self.discogs_lookup.return_value = METADATA
        tracks = get_tracks_from_playlist(self.youtube, "playlist-1")
        self.discogs_lookup.assert_called_once_with("White Flag", "Dido")
        self.assertEqual(tracks[0]["album"], "Life for Rent")
        self.assertEqual(tracks[0]["release_year"], 2003)

    def test_discogs_errors_propagate(self):
        self.lookup.return_value = None
        self.discogs_lookup.side_effect = RuntimeError("Discogs unavailable")
        with self.assertRaisesRegex(RuntimeError, "Discogs unavailable"):
            get_tracks_from_playlist(self.youtube, "playlist-1")

    def test_skips_unavailable_videos_before_extraction(self):
        self.first_request.execute.return_value = {"items": [
            playlist_item(title="Private video"), playlist_item(title="Deleted video"),
            playlist_item(video_id=None), {}, playlist_item(),
        ]}
        tracks = get_tracks_from_playlist(self.youtube, "playlist-1")
        self.assertEqual(len(tracks), 1)
        self.extract.assert_called_once()
        self.lookup.assert_called_once()

    def test_skips_unidentified_tracks_without_metadata_request(self):
        for hint in ({"title": None, "artist": None},
                     {"title": "White Flag", "artist": " "}):
            with self.subTest(hint=hint):
                self.extract.return_value = hint
                self.assertEqual(get_tracks_from_playlist(self.youtube, "playlist-1"), [])
        self.lookup.assert_not_called()
        self.discogs_lookup.assert_not_called()

    def test_empty_playlist_returns_empty_list(self):
        self.first_request.execute.return_value = {}
        self.assertEqual(get_tracks_from_playlist(self.youtube, "playlist-1"), [])
        self.extract.assert_not_called()

    def test_real_extractor_quoted_null_skips_lookup_and_download_input(self):
        from llm_title import extract_track_hint

        self.extract.side_effect = extract_track_hint
        self.first_request.execute.return_value = {"items": [{
            **playlist_item(),
            "snippet": {
                "title": "Volodymyr Gnatenko - Subra [OYSTER40]",
                "videoOwnerChannelTitle": "Electronic Love Collective",
            },
        }]}
        response = Mock()
        response.message.content = '{"artist": "null", "title": "Subra"}'
        with patch("llm_title.chat", return_value=response), self.assertLogs("youtube", level="WARNING") as logs:
            self.assertEqual(get_tracks_from_playlist(self.youtube, "playlist-1"), [])
        self.assertIn("could not extract artist", logs.output[0])
        self.lookup.assert_not_called()
        self.discogs_lookup.assert_not_called()

    def test_service_errors_propagate(self):
        self.lookup.side_effect = RuntimeError("Metadata service unavailable")
        with self.assertRaisesRegex(RuntimeError, "Metadata service unavailable"):
            get_tracks_from_playlist(self.youtube, "playlist-1")
        self.discogs_lookup.assert_not_called()
