import json
import unittest
from unittest.mock import Mock, patch

from src.llm_title import extract_filename_hint, extract_track_hint


class TitleExtractionTests(unittest.TestCase):
    def setUp(self):
        result = Mock()
        result.message.content = '{"title": "White Flag", "artist": "Dido"}'
        chat_patch = patch("src.llm_title.chat", return_value=result)
        self.chat = chat_patch.start()
        self.addCleanup(chat_patch.stop)

    def test_filename_is_sent_as_filename_with_only_title_artist_schema(self):
        hint = extract_filename_hint("01 - Dido - White Flag.mp3")
        self.assertEqual(hint, {"title": "White Flag", "artist": "Dido"})
        args = self.chat.call_args.kwargs
        self.assertEqual(args["messages"][1]["content"], "Filename: 01 - Dido - White Flag.mp3")
        self.assertEqual(set(args["format"]["properties"]), {"title", "artist"})

    def test_youtube_extraction_keeps_title_and_uploader_context(self):
        extract_track_hint("Dido - White Flag", "Dido Official")
        content = self.chat.call_args.kwargs["messages"][1]["content"]
        self.assertEqual(content, "Video title: Dido - White Flag\nUploader: Dido Official")

    def test_quoted_null_does_not_become_an_artist_or_title(self):
        for field in ("artist", "title"):
            for value in ("null", " NULL ", None, " "):
                with self.subTest(field=field, value=value):
                    data = {"artist": "Volodymyr Gnatenko", "title": "Subra"}
                    data[field] = value
                    self.chat.return_value.message.content = json.dumps(data)
                    hint = extract_track_hint(
                        "Volodymyr Gnatenko - Subra [OYSTER40]", "Electronic Love Collective",
                    )
                    self.assertIsNone(hint[field])

    def test_trims_extracted_fields(self):
        self.chat.return_value.message.content = '{"artist": " Dido ", "title": " White Flag "}'
        self.assertEqual(extract_filename_hint("Dido - White Flag.mp3"), {
            "artist": "Dido", "title": "White Flag",
        })
