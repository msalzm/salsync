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

    def test_filename_prompt_includes_available_tags(self) -> None:
        """Keep the filename and include complete or partial tag context."""
        filename = "01 - Dido - White Flag.mp3"
        cases = (
            ("White Flag", ["Dido", "Guest"],
             {"title": "White Flag", "artist": "Dido & Guest"}),
            ("White Flag", None, {"title": "White Flag", "artist": ""}),
            (None, ["Dido", "Guest"], {"title": "", "artist": "Dido & Guest"}),
            (None, None, None),
            ("", [], None),
        )
        for tagged_title, tagged_artists, expected_tags in cases:
            with self.subTest(title=tagged_title, artists=tagged_artists):
                self.chat.reset_mock()
                hint = extract_filename_hint(
                    filename, tagged_title=tagged_title,
                    tagged_artists=tagged_artists,
                )
                self.chat.assert_called_once()
                content = self.chat.call_args.kwargs["messages"][1]["content"]
                if expected_tags is None:
                    self.assertEqual(content, f"Filename: {filename}")
                else:
                    filename_context, tag_context = content.split("\nTags: ", 1)
                    self.assertEqual(filename_context, f"Filename: {filename}")
                    self.assertEqual(json.loads(tag_context), expected_tags)
                self.assertEqual(hint, {"title": "White Flag", "artist": "Dido"})

    def test_youtube_extraction_keeps_title_and_uploader_context(self):
        extract_track_hint("Dido - White Flag", "Dido Official")
        content = self.chat.call_args.kwargs["messages"][1]["content"]
        self.assertEqual(content, "Video title: Dido - White Flag\nChannel name: Dido Official\nVideo description: ")

    def test_youtube_extraction_includes_multiline_description(self):
        description = "Artist: Dido\nTrack: White Flag\nLabel: Example Records"
        hint = extract_track_hint("White Flag", "Music Archive", description=description)
        self.chat.assert_called_once()
        args = self.chat.call_args.kwargs
        self.assertEqual(args["messages"][1]["content"], (
            "Video title: White Flag\nChannel name: Music Archive\n"
            f"Video description: {description}"
        ))
        self.assertEqual(set(args["format"]["properties"]), {"title", "artist"})
        self.assertEqual(hint, {"title": "White Flag", "artist": "Dido"})

    def test_missing_youtube_context_is_sent_as_empty_text(self):
        for missing in (None, ""):
            with self.subTest(missing=missing):
                extract_track_hint("White Flag", missing, description=missing)
                content = self.chat.call_args.kwargs["messages"][1]["content"]
                self.assertEqual(content, (
                    "Video title: White Flag\nChannel name: \nVideo description: "
                ))

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
