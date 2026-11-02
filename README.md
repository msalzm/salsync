This is a desktop app that stores each user’s music collection on their own device.
- The user adds a track on a free or subscription based service ( Tidal, Spotify etc.) to a specific "own" playlist.
- The track gets added on the app and shows its original listening link.
- The app will search for this song on plattforms like Discogs, Bandcamp where the track or the Album can be bought. 
- Adding the same song from another listening service should show one song with two listening links.
- Prices and automatic playlist mirroring are future features. Further services might be added in the future.

Start the minimal local app with your existing Python environment:

```sh
salvenv/bin/python src/app.py
```

On macOS, double-click `Salsync.command` in Finder to start the app. A Desktop
alias or symlink to this launcher works too. If the app is already running, the
launcher opens its existing browser interface. Keep its Terminal window open
while using the app; press Ctrl+C there to stop the server.

It opens `http://127.0.0.1:8765` in your browser. Choose YouTube, Spotify or a
local folder, load normalized tracks, then select the rows to search or download.
For folder tracks, **Tag & rename files** writes tags to the selected files and
renames them after confirmation.
Album metadata and release year appear in the track table, and the Activity panel
shows progress, search matches and errors. Tasks run in the background; one task
runs at a time. The collection stays in memory and resets when the app stops.
Downloads and their tags remain on disk.

The app uses the same YouTube credentials, Spotify cache, Discogs token and
Ollama server as the scripts. For Spotify, set `SPOTIFY_CLIENT_ID` before starting
the app. Account sign-in opens in your browser when needed. Download settings
accept the Sockseek executable path, configuration path and destination folder.
`SOCKSEEK_BINARY` and `SOCKSEEK_CONFIG` provide defaults; a Sockseek executable
in `~/Downloads/sockseek` is also detected. Settings last for the current page.
No additional Python packages are needed beyond the existing service dependencies.
Use `--port 8766` to choose another port or `--no-browser` to open the URL yourself.

YouTube title extraction can be enriched with the earliest documented original
album in MusicBrainz, falling back to the first official release:

```python
from src.musicbrainz import find_first_release

metadata = find_first_release("White Flag", "Dido")
if metadata is not None:
    print(metadata["album"], metadata["release_date"], metadata["url"])
```

Install `musicbrainzngs` in your Python environment. Optionally set
`MUSICBRAINZ_CONTACT` to a contact email or application URL for the API user agent.
No MusicBrainz API key is needed.

Like Spotify, `youtube.get_tracks_from_playlist(youtube, playlist_id)` returns
a list of normalized tracks with `service`, `url`, `service_id`, `title`,
`artists`, `album` and `release_year`. Both service modules fetch playlist pages and call their
normalizer with one track at a time, then append the normalized result.
`normalize_youtube_track(track_data)` lives alongside `normalize_spotify_track`
in `src/track.py` and formats an enriched track without making service calls.
YouTube's `get_tracks_from_playlist` extracts the title and artist using Ollama,
calls MusicBrainz's `find_first_release` for album metadata, and checks Discogs
if MusicBrainz returns no match. It then passes the enriched item to the normalizer.
YouTube's `service_id` is the video ID, and `url` is its original listening link.

The Discogs fallback reads `DISCOGS_TOKEN` from the environment, or falls back to
`.discogs-token` in the project root. Put only the token in that file, without
quotes or `DISCOGS_TOKEN=`. Surrounding whitespace is ignored. The environment
variable takes precedence, and `.discogs-token` is ignored by Git. It checks all
search pages for matching titles and artist credits, preferring the earliest
dated original album over singles. Unofficial releases and promos are excluded.
When neither source matches, the extracted title and artist are retained and
`album` is `None`. Private/deleted videos and items without an identifiable title
and artist are skipped. API and Ollama errors propagate. This requires the
`ollama` Python package and a running Ollama server with `ministral-3:8b`.
Like `src/check_spotify.py`, `src/check_youtube.py` prints the track count and
previews the first three normalized tracks.

`check_youtube.py` can pass its normalized tracks to Sockseek:

```sh
export SOCKSEEK_CONFIG="$PWD/.sockseek.conf"
salvenv/bin/python src/check_youtube.py --search --limit 3
salvenv/bin/python src/check_youtube.py --download --limit 3
```

Copy `sockseek.conf.example` to `.sockseek.conf` and enter your Soulseek
credentials. The `sockseek` executable must be on PATH, or selected with
`SOCKSEEK_BINARY` / `--sockseek-binary`. `--search` prints matches without
downloading; `--download` downloads matching individual tracks to `downloads/`.
Use `--download-dir` to choose another destination and `--playlist` to select
a playlist other than `salsync`. `--limit` applies after playlist normalization.
Without either mode flag, the script only normalizes and previews tracks.

`find_first_release` returns detailed metadata including the track title,
artists, release title (`album`, also used
for singles and EPs), date, country, type, labels/catalog numbers, formats,
duration, ISRCs, and MusicBrainz IDs and source link. Missing optional fields are
`None` or empty lists. The function returns `None` for missing input, no exact
title/artist match, or no dated official release; API errors propagate.

All recording search and release pages are checked. The earliest original album
is preferred over singles and EPs, even if they were released earlier.
Compilation, live and remix albums do not receive this preference. If no dated
original album is found, the earliest official release is returned instead.
`release_date` is the date of the selected album or fallback release.
Unknown dates are excluded. Partial dates such as
`1998` retain their precision and sort by their earliest possible day, so order
within that year may be uncertain. MusicBrainz may have incomplete release
history. Title and artist alone cannot
distinguish versions with identical names; `recording_comment` exposes any
MusicBrainz disambiguation text.

Run the tests from the project root with
`PYTHONPATH=src salvenv/bin/python -m unittest discover -s tests`. The source
directory is included on the import path to match running the check scripts.

Normalize local MP3s with `check_folder.py`:

```sh
export DISCOGS_TOKEN='your_discogs_personal_access_token'
salvenv/bin/python src/check_folder.py "/path/to/music"
```

Add `--recursive` to include subfolders. Title and artist come from existing
ID3 tags first. When either is missing, the same Ollama model used for YouTube
extracts it from the filename (for example, `01 - Dido - White Flag.mp3`), and
any existing tag is kept. Untagged and empty MP3s are supported. Files already
tagged with title, artist, album and year skip the lookup; otherwise MusicBrainz
is checked first, then Discogs if there is no match, with the same preference
for the original album used by YouTube.

`get_tracks_from_folder(folder_path, recursive=False)` returns the same fields
as Spotify and YouTube: `service`, `url`, `service_id`, `title`, `artists`,
`album` and `release_year`. Local tracks use `service="local"`, a file URL and the absolute path as
`service_id`. Matched metadata supplies the title, artist credits and album;
without a match, identified title/artist and any tagged album/year are retained
(`album` is otherwise `None`). Files whose tags and filename cannot identify
both title and artist are skipped, and per-file errors are reported while the
remaining files are processed. Scanning only reads files.

Add `--organize` to tag and rename the scanned files in place:

```sh
salvenv/bin/python src/check_folder.py "/path/to/music" --organize
```

`organize_tracks(tracks)` uses the same naming and tagging as downloads (see
below): files become `Artist - Title.mp3` in their current folder, and existing
names are never overwritten. It returns the tracks with their new paths and the
number of failures; a failed file is left unchanged and makes the command exit 1.

MP3 downloads are automatically named and tagged:

```sh
salvenv/bin/python -m pip install 'mutagen>=1.47,<2'
salvenv/bin/python src/check_youtube.py --download --limit 3
```

Download mode requests MP3 files explicitly. Each completed file receives the
name `Artist - Track title.mp3`, with multiple artists joined using ` & `.
Characters unsuitable for filenames are replaced, and long filenames are
shortened; the tags retain the original text. The file stays in its download
directory. Existing filenames are preserved by adding `(2)`, `(3)`, etc. to a
new file's name when necessary.

The tagger uses Mutagen to write ID3v2.4 `TIT2` (title), `TPE1` (all artist
credits), `TALB` (album) and `TDRC` (year). No source URLs or custom identifier
frames are added. Existing unrelated tags, including artwork and genre, are
preserved. Missing album/year information leaves those existing fields alone.
MusicBrainz/Discogs's selected album or fallback release supplies the year for
YouTube and folder tracks; Spotify uses the album's release date. The normalized
`release_year` field is an integer, or `None` when unknown.

The MP3 is validated and tagged as a temporary copy before the final filename
is published. Audio is not re-encoded. If tagging fails, the downloaded original
is retained and the failure is reported while other completed tracks continue.

The adapter uses Sockseek's documented completion hooks and source item numbers
to connect downloaded paths to normalized tracks. It reports renamed paths back
through `update-index`, so later runs can reuse Sockseek's download index. Files
reported as already downloaded are tagged too; rerunning retains any filename
suffix previously added for a collision. Use Sockseek v3.0.5 or newer with the
[documented completion-hook options](https://github.com/fiso64/sockseek#on-complete-actions).
Per-run metadata and processing reports are kept in the Git-ignored
`.sockseek/runs/` directory. A tagging failure makes the check command fail even
if Sockseek itself exits successfully. A successful process exit does not mean
every requested song was found on Soulseek.

The shared `sockseek.download_tracks(tracks, ...)` function uses the same flow
for normalized tracks from any source. Folder scans leave local MP3s untouched
unless you organize them. Mutagen is needed for folder scans, downloads and
organizing; YouTube and Spotify normalization and search work without it. Discogs genre enrichment is tracked in [TODO.md](TODO.md).
