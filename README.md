# music-scrobble

A Windows terminal music player that submits Last.fm scrobbles, plus a small Python CLI and Go MCP server.

## Requirements

- Windows 10 or 11 with PowerShell
- Python 3.12
- FFmpeg, including `ffplay` and `ffprobe` on `PATH` (for example, install with [Scoop](https://scoop.sh/): `scoop install ffmpeg`)
- A Last.fm account and API application for scrobbling

## Install

From PowerShell, clone the repository and install the Python dependencies:

```powershell
git clone https://github.com/bonsai/music-scrobble.git
cd music-scrobble
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

The player reads your music folder from `MUSIC_ROOT`. Set it in the same PowerShell session before launching the app:

```powershell
$env:MUSIC_ROOT = "D:\Music"
```

Choose the folder that contains your music files. The player scans supported files such as MP3, FLAC, M4A, OGG, and WAV, and caches library metadata locally.

## Connect Last.fm

1. Create an application at [Last.fm API account creation](https://www.last.fm/api/account/create). Keep its API key and shared secret private; Last.fm shows the shared secret on the application page.
2. In PowerShell, run the authorization step:

   ```powershell
   python lastfm_auth.py token
   ```

   If `LASTFM_API_KEY` and `LASTFM_API_SECRET` are not set, the script prompts for the key and asks for the shared secret without echoing it. The command prints an authorization URL and tries to open it in your browser.
3. Open the URL if needed, sign in to Last.fm, and click **Yes, allow access**.
4. Back in PowerShell, exchange the authorized token for a session:

   ```powershell
   python lastfm_auth.py finish
   ```

   This saves `.lastfm_session` and `.lastfm_creds` beside the scripts, then removes the temporary `.lastfm_token`. The credentials file contains the API key and shared secret in plain text, so keep it private.

These local credential and state files are listed in `.gitignore`; do not commit them. The player and CLI can also read `LASTFM_SESSION_KEY`, `LASTFM_API_KEY`, and `LASTFM_API_SECRET` from the environment. `LASTFM_USER` changes the username displayed in the player; the `lastfm` CLI command currently checks the `kanalsound` account directly.

## Play and scrobble

Start the player from the repository directory:

```powershell
python tui_player.py
```

Wait for the library scan, focus the track list, highlight a track, and press Enter or Space to play it from the beginning. A scrobble is submitted after 15 seconds of playback. The `MUSIC_ROOT` folder and Last.fm session must be available. The player also uses `plays.db` for local play history.

Keyboard shortcuts:

| Key | Action |
| --- | --- |
| `q` | Quit |
| `Enter` / `Space` with track list focused | Play or restart the highlighted track |
| App `Space` shortcut | Stop playback or restart the loaded track from the beginning |
| `n` / `p` | Next / previous track |
| `s` | Stop playback |
| `/` | Focus track search |
| `r` | Toggle shuffle |
| `b` | Toggle blackout mode |

The Play control and app's Space shortcut start the highlighted track only when no track is loaded; otherwise they control the loaded track. The app shortcut applies when the focused widget does not handle Space. Playback restarts from the beginning after stopping.

The controls shown in the player include previous (`<<`), play (`>`), stop (`||`), next (`>>`), shuffle (`RND`), palette (`PAL`), blackout (`BLK`), visualizer (`VIS`), debug (`DBG`), and exit (`EXIT`).

## Scrobbler CLI

Run these commands from the repository directory:

```powershell
python scrobbler.py stats
python scrobbler.py lastfm
python scrobbler.py scrobble "D:\Music\Artist - Track.mp3"
python scrobbler.py resend
```

- `stats` shows records in the local `plays.db` database.
- `lastfm` lists recent tracks for the `kanalsound` account.
- `scrobble PATH` submits one file, deriving artist and track from an `Artist - Track` filename (or using the full filename as the track when there is no separator).
- `resend` retries database rows marked as not scrobbled after credentials are configured.

`python scrobbler.py play FOLDER` submits MP3 files from a folder.

## Go MCP prototype

The Go server is an unfinished stdio MCP prototype. Its current source has a [build blocker (#1)](https://github.com/bonsai/music-scrobble/issues/1), and [MCP client integration (#7)](https://github.com/bonsai/music-scrobble/issues/7) is still pending. It advertises `scrobble`, `play_folder`, and `stats` tools, but its scrobble function makes no Last.fm request and its statistics are a stub ([#2](https://github.com/bonsai/music-scrobble/issues/2)). Use the Python player or CLI above for Last.fm scrobbling.

## UI diagnostics

`ui_ontology.py` describes and checks the terminal UI:

```powershell
python ui_ontology.py --md     # print the generated UI ontology Markdown
python ui_ontology.py --json   # print check findings as JSON
python ui_ontology.py          # print a readable check report
```

## Local data and Last.fm corrections

The app stores local history in `plays.db`, a library cache in `.library_cache.json`, and API errors in `.lastfm_errors.log`. These files are ignored by Git along with `.lastfm_token`, `.lastfm_session`, and `.lastfm_creds`.

Last.fm does not provide an API to undo a submitted scrobble. If you need to remove one, use the Last.fm website's library page.
