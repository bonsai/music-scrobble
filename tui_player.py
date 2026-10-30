#!/usr/bin/env python3
"""
TUI Music Player with ASCII visualizer
Uses textual for UI, ffplay for audio, updates plays.db on scrobble
"""

import os
import hashlib
import json
import random
import re
import time
import threading
import subprocess
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Deque, List, Optional, Tuple
from collections import deque
from dataclasses import dataclass

try:
    from mutagen import File as MutagenFile
except Exception:  # pragma: no cover
    MutagenFile = None

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import (
    Header, Footer, Static, ListView, ListItem, Label, Button, Input, ProgressBar
)
from textual.reactive import reactive
from textual.screen import Screen
from textual.message import Message
from textual.binding import Binding
from textual.timer import Timer

# ─── Config ──────────────────────────────────────────────────────
MUSIC_ROOT = Path(os.environ.get("MUSIC_ROOT", r"C:\Users\dance\Music\mp3"))
DB_PATH = Path("plays.db")
LASTFM_API_KEY = os.environ.get("LASTFM_API_KEY", "0db7ea47efd451c06b4d7c02a64f5458")
FFPLAY = "ffplay"
SESSION_FILE = Path(__file__).with_name(".lastfm_session")
CREDS_FILE = Path(__file__).with_name(".lastfm_creds")
LIB_CACHE = Path(__file__).with_name(".library_cache.json")

# ─── Data ────────────────────────────────────────────────────────
@dataclass
class Track:
    path: Path
    artist: str
    title: str
    duration: float = 0.0

    @property
    def display(self) -> str:
        return f"{self.artist} - {self.title}"

    @property
    def key(self) -> str:
        return str(self.path)

# ─── DB ──────────────────────────────────────────────────────────
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS plays (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT UNIQUE,
                artist TEXT,
                title TEXT,
                duration REAL DEFAULT 0,
                played_at INTEGER,
                scrobbled INTEGER DEFAULT 0
            )
        """)

def log_play(track: Track, played_at: int, scrobbled: int = 1):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT INTO plays (path, artist, title, duration, played_at, scrobbled)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                artist=excluded.artist,
                title=excluded.title,
                duration=excluded.duration,
                played_at=excluded.played_at,
                scrobbled=excluded.scrobbled
        """, (str(track.path), track.artist, track.title, track.duration, played_at, scrobbled))


def db_total() -> int:
    try:
        with sqlite3.connect(DB_PATH) as conn:
            return conn.execute("SELECT COUNT(*) FROM plays").fetchone()[0]
    except Exception:
        return 0


def _read_creds() -> dict:
    try:
        out = {}
        for line in CREDS_FILE.read_text(encoding="utf-8").splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
        return out
    except Exception:
        return {}


def lastfm_api_secret() -> str:
    return _read_creds().get("api_secret", "") or os.environ.get("LASTFM_API_SECRET", "").strip()


def lastfm_api_key() -> str:
    """API key from env, or from .lastfm_creds written by lastfm_auth.py."""
    return _read_creds().get("api_key", "") or os.environ.get("LASTFM_API_KEY", "").strip()


def lastfm_session_key() -> str:
    """Session key from env, or from .lastfm_session written by lastfm_auth.py."""
    key = os.environ.get("LASTFM_SESSION_KEY", "").strip()
    if key:
        return key
    try:
        return SESSION_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def lastfm_scrobble(track: Track, timestamp: int) -> str:
    """Fire-and-forget Last.fm scrobble (only if key + session are configured)."""
    api_key = lastfm_api_key()
    session_key = lastfm_session_key()
    if not api_key or not session_key:
        return "skipped (no LASTFM_SESSION_KEY - run lastfm_auth.py)"
    fields = {
        "method": "track.scrobble",
        "api_key": api_key,
        "sk": session_key,
        "artist": track.artist,
        "track": track.title,
        "timestamp": str(timestamp),
        "format": "json",
    }
    if track.duration:
        fields["duration"] = str(int(track.duration))
    secret = lastfm_api_secret()
    if secret:
        raw = "".join(f"{k}{fields[k]}" for k in sorted(fields) if k != "format") + secret
        fields["api_sig"] = hashlib.md5(raw.encode()).hexdigest()
    data = urllib.parse.urlencode(fields).encode()
    try:
        req = urllib.request.Request(
            "https://ws.audioscrobbler.com/2.0/",
            data=data,
            headers={"User-Agent": "tui-scrobble/1.0",
                     "Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read().decode())
        return "submitted" if "scrobbles" in payload else str(payload)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        try:
            err = json.loads(body)
            msg = f"{exc.code}: {err.get('message')} (error {err.get('error')})"
        except Exception:
            msg = f"{exc.code}: {body[:120]}"
        _log_error(track, fields, msg)
        return f"error {msg}"
    except Exception as exc:
        _log_error(track, fields, repr(exc))
        return f"error: {exc}"


def _log_error(track: Track, fields: dict, message: str) -> None:
    """Keep a small debug trail (never logs the secret/session key)."""
    try:
        safe = {k: v for k, v in fields.items() if k not in ("sk", "api_sig")}
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message} | {safe}\n"
        with (Path(__file__).with_name(".lastfm_errors.log")).open("a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass

# ─── Scanner ─────────────────────────────────────────────────────

def probe_duration(path: Path) -> float:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=15,
        )
        return float(out.stdout.strip())
    except Exception:
        return 0.0
TRACKNO_RE = re.compile(r"^\s*\d{1,3}\s*[-._]\s+")


def read_tags(path: Path) -> Tuple[Optional[str], Optional[str]]:
    if MutagenFile is None:
        return None, None
    try:
        m = MutagenFile(str(path), easy=True)
        if not m or not getattr(m, "tags", None):
            return None, None
        artist = (m.tags.get("artist") or [None])[0]
        title = (m.tags.get("title") or [None])[0]
        return (artist or None), (title or None)
    except Exception:
        return None, None


def parse_stem(stem: str) -> Tuple[str, str]:
    stem = TRACKNO_RE.sub("", stem)
    if " - " in stem:
        artist, title = stem.split(" - ", 1)
    else:
        artist, title = "Unknown", stem
    return artist.strip(), title.strip()


AUDIO_EXTS = {".mp3", ".flac", ".m4a", ".ogg", ".wav"}


def load_cache(root: Path) -> dict:
    """path -> {m, s, a, t, d} from .library_cache.json (empty on miss)."""
    try:
        data = json.loads(LIB_CACHE.read_text(encoding="utf-8"))
        if data.get("root") != str(root):
            return {}
        return data.get("tracks", {})
    except Exception:
        return {}


def save_cache(root: Path, entries: dict) -> None:
    try:
        LIB_CACHE.write_text(
            json.dumps({"root": str(root), "tracks": entries}, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


def tracks_from_cache(root: Path, cache: dict) -> List[Track]:
    """Instant list built from cache only (no disk/tag access)."""
    tracks = []
    for path_str, e in cache.items():
        p = Path(path_str)
        if not p.exists():
            continue
        tracks.append(Track(path=p, artist=e.get("a", ""), title=e.get("t", ""),
                            duration=float(e.get("d") or 0)))
    return sorted(tracks, key=lambda t: (t.artist.lower(), t.title.lower()))


def scan_music(root: Path, cache: Optional[dict] = None,
               on_progress=None) -> Tuple[List[Track], dict]:
    """Walk the library once, reusing cached tags for unchanged files."""
    cache = dict(cache or {})
    entries: dict = {}
    tracks: List[Track] = []
    if not root.exists():
        return tracks, entries

    files = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            p = Path(dirpath) / name
            if p.suffix.lower() in AUDIO_EXTS:
                files.append(p)

    total = len(files)
    for i, f in enumerate(files):
        try:
            st = f.stat()
            mtime, size = st.st_mtime, st.st_size
        except OSError:
            continue
        key = str(f)
        old = cache.get(key)
        if old and old.get("m") == mtime and old.get("s") == size:
            artist, title = old.get("a", ""), old.get("t", "")
            duration = float(old.get("d") or 0)
        else:
            tag_artist, tag_title = read_tags(f)
            file_artist, file_title = parse_stem(f.stem)
            artist = tag_artist or file_artist
            title = tag_title or file_title
            duration = float(old.get("d") or 0) if old else 0.0
        entries[key] = {"m": mtime, "s": size, "a": artist, "t": title, "d": duration}
        tracks.append(Track(path=f, artist=artist, title=title, duration=duration))
        if on_progress and i % 25 == 0:
            on_progress(i + 1, total)

    tracks.sort(key=lambda t: (t.artist.lower(), t.title.lower()))
    return tracks, entries

# ─── Visualizer ──────────────────────────────────────────────────
VIZ_FRAMES = [
    ".,-~=*#%#*=~-.,",
    ",-~=*#%@%#*=~-,",
    "-~=*#%@%@%#*=~-",
    "~=*#%@%@@@%@%#*=",
    "=*#%@%@@@@@@%@%#",
    "*#%@%@@@@@@@@@%@",
    "#%@%@@@@@@@@@@@@@",
    "=*#%@%@@@@@@%@%#",
]

class VisualizerScreen(Screen):
    """Independent full-screen visualizer view."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("q", "app.pop_screen", "Back"),
        Binding("space", "toggle_play", "Play"),
    ]

    def compose(self) -> ComposeResult:
        yield Static("VISUALIZER  [ESC] BACK", id="viz-head")
        yield Visualizer(id="viz-full")

    def on_mount(self) -> None:
        self.query_one(Visualizer).playing = self.app.playing

    def action_toggle_play(self) -> None:
        self.app.action_toggle_play()


class Visualizer(Static):
    """Animated ASCII spectrum visualizer"""
    playing = reactive(False)
    frame_idx = reactive(0)
    _timer: Optional[Timer] = None

    def watch_playing(self, playing: bool):
        if playing:
            self._timer = self.set_interval(0.1, self.next_frame)
        elif self._timer:
            self._timer.stop()
            self._timer = None
            self.frame_idx = 0
            self.update(self.render_frame(0))

    def next_frame(self):
        self.frame_idx = (self.frame_idx + 1) % len(VIZ_FRAMES)
        self.update(self.render_frame(self.frame_idx))

    def render_frame(self, idx: int) -> str:
        frame = VIZ_FRAMES[idx]
        return f"[bold cyan]{frame}[/bold cyan]"

# ─── Player Backend ──────────────────────────────────────────────
class Player:
    def __init__(self):
        self.proc: Optional[subprocess.Popen] = None
        self.current: Optional[Track] = None
        self.position = 0.0
        self.duration = 0.0
        self._pos_thread: Optional[threading.Thread] = None
        self._stop_pos = threading.Event()

    def play(self, track: Track, start: float = 0.0) -> bool:
        self.stop()
        self.current = track
        self._stop_pos.clear()
        args = [FFPLAY, "-nodisp", "-autoexit", "-loglevel", "quiet"]
        if start > 0:
            args += ["-ss", f"{start:.2f}"]
        args.append(str(track.path))
        try:
            self.proc = subprocess.Popen(
                args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )
            self._start_position_tracker(start)
            return True
        except FileNotFoundError:
            return False

    def _start_position_tracker(self, offset: float = 0.0):
        def track_pos():
            start = time.time() - offset
            while self.proc and self.proc.poll() is None and not self._stop_pos.is_set():
                self.position = time.time() - start
                time.sleep(0.5)
            self.position = 0
        self._pos_thread = threading.Thread(target=track_pos, daemon=True)
        self._pos_thread.start()

    def stop(self):
        self._stop_pos.set()
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self.proc = None
        self.current = None
        self.position = 0

    def toggle_pause(self):
        # ffplay doesn't support pause via signal easily; restart from position
        pass

    @property
    def is_playing(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

# ─── Track List Widget ───────────────────────────────────────────
class TrackList(ListView):
    BINDINGS = [
        Binding("enter", "select_cursor", "Play", show=True),
        Binding("space", "select_cursor", "Play", show=False),
    ]

    def __init__(self, tracks: Optional[List[Track]] = None, id: Optional[str] = None):
        super().__init__(id=id)
        self.tracks: List[Track] = tracks or []

    async def set_tracks(self, tracks: List[Track]) -> None:
        self.tracks = tracks
        await self.clear()
        items = [ListItem(Label(t.display), id=f"track-{i}") for i, t in enumerate(tracks)]
        if items:
            await self.extend(items)
            self.index = 0
        else:
            self.index = None

    def compose(self) -> ComposeResult:
        for i, track in enumerate(self.tracks):
            yield ListItem(Label(track.display), id=f"track-{i}")

    def on_mount(self) -> None:
        if self.children and self.index is None:
            self.index = 0

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.item and event.item.id:
            try:
                idx = int(event.item.id.rsplit("-", 1)[1])
            except (ValueError, IndexError):
                return
            if 0 <= idx < len(self.tracks):
                self.app.play_track(self.tracks[idx])

# ─── Main App ────────────────────────────────────────────────────
class LibraryScanned(Message):
    def __init__(self, tracks: List[Track], entries: dict):
        super().__init__()
        self.tracks = tracks
        self.entries = entries



def fmt_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def bar(value: float, total: float, width: int = 14) -> str:
    """ASCII-only progress bar, e.g. [######--------]"""
    inner = max(1, width - 2)
    if total <= 0:
        filled = 0
    else:
        filled = int(round(inner * min(1.0, max(0.0, value / total))))
    return "[" + "#" * filled + "-" * (inner - filled) + "]"


class MusicPlayerApp(App):
    """Single status panel (track / player / scrobble) + one control bar."""

    CSS = """
    /* ── mini-disc era LCD console ─────────────────────────────── */
    Screen { background: #08090a; }

    #main { layout: horizontal; height: 1fr; }
    #sidebar { width: 26%; border-right: solid #2a3a1c; padding: 1; }
    #shell { width: 1fr; layout: horizontal; }
    #aside {
        width: 24%;
        border-left: solid #2a3a1c;
        padding: 1;
        layout: vertical;
    }
    #gutter {
        width: 4;
        padding: 1 0 0 0;
        color: #3f6b24;
        background: #060703;
        display: none;
    }
    #player { width: 1fr; padding: 1; layout: vertical; }
    /* BLK: keep the layout, just sink the list letters into the dark */
    #main.-blackout #sidebar { border-right: solid #131a0e; }
    #main.-blackout #sidebar ListItem { color: #14180f; background: #08090a; }
    #main.-blackout #sidebar ListItem.--highlight { color: #1b2114; background: #0d1109; }
    #main.-blackout #search { color: #14180f; border: ascii #18200f; }

    #logo {
        height: 7;
        padding: 0 1;
        color: #b6ff3d;
        border: ascii #3f6b24;
        background: #0c1507;
        text-style: bold;
    }

    #marquee {
        height: 3;
        padding: 0 1;
        background: #0c1507;
        border: ascii #2a4a18;
        color: #b6ff3d;
    }

    #lcd {
        height: 5;
        layout: horizontal;
        background: #0e1a07;
        padding: 0;
    }
    .lcdbox {
        width: 1fr;
        height: 5;
        padding: 0 1;
        background: #0e1a07;
        color: #b6ff3d;
        border: ascii #3f6b24;
        text-style: bold;
    }
    #lcd-track { width: 2fr; }

    .side-box {
        width: 100%;
        height: 12;
        padding: 0 1;
        margin-bottom: 1;
        background: #0c1507;
        border: ascii #2a4a18;
        color: #b6ff3d;
    }
    #viz-head { height: 1; color: #b6ff3d; text-style: bold; }
    #viz-full {
        height: 1fr;
        content-align: center middle;
        color: #b6ff3d;
        border: ascii #2a4a18;
        background: #0c1507;
    }
    #controls {
        height: 3;
        layout: horizontal;
        align: center middle;
        background: #0c1507;
        border-top: solid #2a3a1c;
        overflow: hidden;
    }
    #controls Button {
        min-width: 0;
        margin: 0;
        padding: 0;
        border: ascii #3f6b24;
        background: #101a08;
        color: #b6ff3d;
        border: ascii #3f6b24;
    }
    #controls Button:hover { background: #1d2f10; }
    #events {
        height: 4;
        margin-top: 1;
        padding: 0 1;
        background: #0c1507;
        border: ascii #2a4a18;
        color: #8fbf5a;
    }

    ListView { height: 100%; background: #08090a; }
    ListItem { padding: 0 1; color: #9fbf78; }
    ListItem.--highlight { background: #16260c; color: #b6ff3d; }
    #search {
        margin-bottom: 1;
        background: #101a08;
        color: #b6ff3d;
        border: tall #3f6b24;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit", show=False),
        Binding("space", "toggle_play", "Play", show=False),
        Binding("n", "next_track", "Next", show=False),
        Binding("p", "prev_track", "Prev", show=False),
        Binding("s", "stop", "Stop", show=False),
        Binding("/", "focus_search", "Search", show=False),
        Binding("r", "toggle_shuffle", "Random", show=False),
        Binding("b", "toggle_blackout", "Blackout", show=False),
    ]
    current_track: reactive[Optional[Track]] = reactive(None)
    playing = reactive(False)
    shuffle: reactive[bool] = reactive(False)
    position = reactive(0.0)
    duration = reactive(0.0)

    def __init__(self):
        super().__init__()
        self.cache = load_cache(MUSIC_ROOT)
        self.tracks = tracks_from_cache(MUSIC_ROOT, self.cache)
        self.player = Player()
        self.filtered_tracks = self.tracks
        self.current_index = -1
        self.scan_done = False
        self.scrobble_state = "idle"
        self.blacked_out = False
        self.show_lines = os.environ.get("AMPY_DEBUG", "") not in ("", "0", "false")
        self.events: Deque[Tuple[str, str, str]] = deque(maxlen=2)
        self._blink_until = 0.0
        self._blink_phase = False
        self._marquee_offset = 0
        self._marquee_text = "NO DISC -- insert a track from the list"
        self.scrobble_delay = 15
        self._scrobble_timer: Optional[Timer] = None
        self._pending_track: Optional[Track] = None
        self.scrobbled_count = 0
        init_db()

    # ── layout ───────────────────────────────────────────────────
    def compose(self) -> ComposeResult:
        with Container(id="main"):
            with Vertical(id="sidebar"):
                yield Input(placeholder="Search tracks...", id="search")
                yield TrackList(self.filtered_tracks, id="tracklist")
            with Vertical(id="aside"):
                yield Static("", id="queue", classes="side-box")
                yield Static("", id="stats", classes="side-box")
            with Horizontal(id="shell"):
                yield Static("", id="gutter")
                with Vertical(id="player"):
                    yield Static("", id="logo")
                    yield Static("", id="events")
                    yield Static("", id="marquee")
                    with Horizontal(id="lcd"):
                        yield Static("", id="lcd-track", classes="lcdbox")
                        yield Static("", id="lcd-scrob", classes="lcdbox")
                        yield Static("", id="lcd-player", classes="lcdbox")
        with Horizontal(id="controls"):
            yield Button("<<", id="btn-prev")
            yield Button(">", id="btn-play", variant="success")
            yield Button("||", id="btn-stop", variant="error")
            yield Button(">>", id="btn-next")
            yield Button("RND", id="btn-shuffle")
            yield Button("PAL", id="btn-palette")
            yield Button("BLK", id="btn-blackout")
            yield Button("VIS", id="btn-vis")
            yield Button("DBG", id="btn-debug")
            yield Button("EXIT", id="btn-quit", variant="error")


    def on_mount(self):
        self.set_interval(0.5, self.update_progress)
        for wid, title in (("#lcd-track", "TRACK"), ("#lcd-scrob", "SCROB"),
                           ("#lcd-player", "PLAYER"), ("#events", "EVENT STATUS"),
                           ("#marquee", "SONG INFO")):
            self.query_one(wid).border_title = title
        self.query_one("#queue", Static).border_title = "QUEUE"
        self.query_one("#stats", Static).border_title = "STATS"
        self.query_one("#logo", Static).border_title = "OH MY LOGO"
        logo = [
            "  ###   #   #  ####   #   #",
            " #   #  ## ##  #   #  #   #",
            " #####  # # #  ####   #   #",
            " #   #  #   #  #       ####",
            " #   #  #   #  #          #",
        ]
        self.query_one("#logo", Static).update(chr(10).join(logo))
        self.scrobbled_count = db_total()
        if self.show_lines:
            self.query_one("#gutter").display = True
            self.query_one("#btn-debug", Button).variant = "primary"
        self.set_interval(0.18, self._tick_blink)
        self.set_interval(0.28, self._tick_marquee)
        self.refresh_panel()
        if self.tracks:
            self.log_event("BOOT", f"{len(self.tracks)} tracks loaded (cache)")
            self.update_status(f"{len(self.tracks)} tracks from cache - rescanning...")
        else:
            self.log_event("BOOT", "no cache - scanning library")
            self.update_status("scanning library...")
        self.refresh_library()

    @work(thread=True, exclusive=True)
    def refresh_library(self) -> None:
        """Reuse cached tags, read only new/changed files, then refresh the list."""
        tracks, entries = scan_music(
            MUSIC_ROOT, self.cache,
            on_progress=lambda done, total: self.call_from_thread(
                self.update_status, f"scanning {done}/{total}..."),
        )
        save_cache(MUSIC_ROOT, entries)
        self.post_message(LibraryScanned(tracks, entries))

    async def on_library_scanned(self, event: LibraryScanned) -> None:
        self.cache = event.entries
        self.scan_done = True
        self.tracks = event.tracks
        query = self.query_one("#search", Input).value.strip().lower()
        self.filtered_tracks = [
            t for t in self.tracks
            if not query or query in t.artist.lower() or query in t.title.lower()
        ]
        await self.query_one("#tracklist", TrackList).set_tracks(self.filtered_tracks)
        self.refresh_panel()
        self.log_event("SCAN", f"{len(self.tracks)} tracks ready")
        self.set_marquee(f"{len(self.tracks)} tracks on disc - select and press >")
        self.update_status(f"{len(self.tracks)} tracks loaded")

    async def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search":
            query = event.value.lower()
            self.filtered_tracks = [
                t for t in self.tracks
                if not query or query in t.artist.lower() or query in t.title.lower()
            ]
            await self.query_one("#tracklist", TrackList).set_tracks(self.filtered_tracks)
            self.refresh_panel()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        handlers = {
            "btn-play": self.action_toggle_play,
            "btn-stop": self.action_stop,
            "btn-next": self.action_next_track,
            "btn-prev": self.action_prev_track,
            "btn-shuffle": self.action_toggle_shuffle,
            "btn-palette": self.action_command_palette,
            "btn-blackout": self.action_toggle_blackout,
            "btn-debug": self.action_toggle_debug,
            "btn-vis": self.action_show_visualizer,
            "btn-quit": self.action_quit,
        }
        button_id = event.button.id or ""
        self.log_event("BTN", button_id.replace("btn-", "").upper() + " pressed")
        handler = handlers.get(button_id)
        if handler:
            handler()

    # ── playback ─────────────────────────────────────────────────
    def play_track(self, track: Track):
        cached = float((self.cache.get(str(track.path)) or {}).get("d") or 0)
        self.duration = cached or 180.0
        track.duration = cached
        if not self.player.play(track):
            self.notify("ffplay not found!", severity="error")
            return
        self.current_track = track
        self.current_index = (self.filtered_tracks.index(track)
                              if track in self.filtered_tracks else -1)
        self.playing = True
        self.position = 0.0
        self.scrobble_state = f"wait {self.scrobble_delay}s"
        self._set_viz(True)
        self.refresh_panel()
        self.log_event("PLAY", f"{track.artist} - {track.title}")
        self.set_marquee(f"{track.artist} - {track.title}")
        threading.Thread(target=self._prefetch_durations, args=(track, 3), daemon=True).start()
        self._schedule_scrobble(track)

    def _schedule_scrobble(self, track: Track) -> None:
        """Scrobble only after the track has actually been playing for 15s."""
        if self._scrobble_timer:
            self._scrobble_timer.stop()
            self._scrobble_timer = None
        self._pending_track = track
        self._scrobble_timer = self.set_timer(self.scrobble_delay, self._commit_scrobble)
        self.log_event("SCRB", f"armed: +{self.scrobble_delay}s")

    def _commit_scrobble(self) -> None:
        track, self._pending_track = self._pending_track, None
        self._scrobble_timer = None
        if track is None or not self.playing or track is not self.current_track:
            self.scrobble_state = "cancelled"
            self.log_event("SCRB", "cancelled (stopped early)")
            self.refresh_panel()
            return
        now = int(time.time())
        log_play(track, now, 1)
        self.scrobbled_count = db_total()
        self.scrobble_state = "sending..."
        self.log_event("SCRB", "sending to Last.fm")
        self.refresh_panel()
        threading.Thread(target=self._scrobble_worker, args=(track, now), daemon=True).start()

    def _scrobble_worker(self, track: Track, now: int) -> None:
        result = lastfm_scrobble(track, now)
        self.call_from_thread(self._set_scrobble_state, result)

    def _set_scrobble_state(self, result: str) -> None:
        self.scrobble_state = result
        self.log_event("SCRB", ("OK  " if result == "submitted" else result)[:60])
        self.refresh_panel()

    def _prefetch_durations(self, track: Track, ahead: int = 3) -> None:
        """Probe (and cache) durations so play/progress are instant next time."""
        try:
            idx = self.tracks.index(track)
        except ValueError:
            idx = -1
        targets = self.tracks[idx: idx + max(1, ahead)] if idx >= 0 else [track]
        changed = False
        for t in targets:
            key = str(t.path)
            entry = self.cache.get(key)
            if entry and entry.get("d"):
                t.duration = float(entry["d"])
                continue
            dur = probe_duration(t.path)
            if not dur:
                continue
            if entry is None:
                try:
                    st = t.path.stat()
                except OSError:
                    continue
                entry = {"m": st.st_mtime, "s": st.st_size,
                         "a": t.artist, "t": t.title, "d": dur}
                self.cache[key] = entry
            else:
                entry["d"] = dur
            t.duration = dur
            changed = True
            if t is self.current_track:
                self.call_from_thread(self._apply_duration, dur)
        if changed and self.scan_done:
            save_cache(MUSIC_ROOT, self.cache)

    def _apply_duration(self, dur: float) -> None:
        self.duration = dur
        if self.current_track:
            self.current_track.duration = dur
        self.refresh_panel()

    def update_progress(self):
        if self.playing and self.player.is_playing:
            self.position = self.player.position
            total = self.duration or 180.0
            self.refresh_panel()
        elif self.playing and not self.player.is_playing:
            self.playing = False
            self._set_viz(False)
            self.refresh_panel()
            self.action_next_track()

    def stop_playback(self):
        """Stop but keep the loaded track, so ▶ resumes it."""
        self.player.stop()
        self._cancel_scrobble()
        self.playing = False
        self.position = 0
        self._set_viz(False)
        self.refresh_panel()

    # ── one place that renders every status ──────────────────────
    def refresh_panel(self) -> None:
        try:
            self._render_panel()
            self._update_gutter()
            self._set_viz(self.playing and self.player.is_playing)
        except Exception:
            pass

    # ── LCD sections ────────────────────────────────────────────
    def _render_panel(self) -> None:
        self._render_track_box()
        self._render_scrobble_box()
        self._render_player_box()
        self._render_aside()
        self.query_one("#btn-play", Button).label = "||" if self.playing else ">"
        self.query_one("#btn-shuffle", Button).label = "RND" if self.shuffle else "RND"
        self.query_one("#btn-shuffle", Button).variant = "primary" if self.shuffle else "default"
        self.query_one("#btn-blackout", Button).variant = (
            "primary" if self.blacked_out else "default")

    @staticmethod
    def _md(text: str, width: int) -> str:
        """Truncate/pad like a fixed-width LCD field."""
        text = text.replace(chr(10), " ")
        if len(text) > width:
            return text[: max(0, width - 2)] + ".."
        return text.ljust(width)

    def _render_aside(self) -> None:
        """Right pane: up-next queue + library stats."""
        upcoming: List[str] = []
        if self.filtered_tracks:
            if self.shuffle:
                upcoming = ["  (random)"]
            else:
                start = max(0, self.current_index + 1)
                for t in self.filtered_tracks[start:start + 8]:
                    upcoming.append(f"  {self._md(t.artist, 10)} {t.title[:14]}")
        if not upcoming:
            upcoming = ["  (end of list)"]
        lines = [self._md("UP NEXT", 30)] + upcoming[:8]
        try:
            self.query_one("#queue", Static).update(chr(10).join(lines))
        except Exception:
            pass

    def _render_track_box(self) -> None:
        track = self.current_track
        total = len(self.filtered_tracks)
        no = f"{self.current_index + 1:02d}" if self.current_index >= 0 else "--"
        if track:
            disc = track.path.parent.name
            lines = [
                self._md(f"NO {no}/{total:02d} {disc}", 46),
                self._md(track.title, 46),
                self._md(f"ART {track.artist}", 46),
            ]
        else:
            lines = ["NO --/--", "NO DISC", "ART ----"]
        self.query_one("#lcd-track", Static).update(chr(10).join(lines))

    def _render_scrobble_box(self) -> None:
        state = self.scrobble_state
        if state == "submitted":
            flag = "OK"
        elif state == "sending...":
            flag = "TX"
        elif state.startswith("skipped"):
            flag = "OFF"
        elif state.startswith("wait"):
            flag = "HOLD"
        elif state == "cancelled":
            flag = "SKIP"
        elif state.startswith("error") or state.startswith("rejected"):
            flag = "ERR"
        elif state == "idle":
            flag = "--"
        else:
            flag = state[:6].upper()

        user = os.environ.get("LASTFM_USER", "kanalsound")
        stamp = time.strftime("%H:%M") if state == "submitted" else "--:--"
        lines = [
            self._md(f"LAST.FM {flag}  {stamp}", 26),
            self._md(f"USER {user}", 26),
            self._md(f"LOG {self.scrobbled_count:>5} plays", 26),
        ]
        self.query_one("#lcd-scrob", Static).update(chr(10).join(lines))

    def _render_player_box(self) -> None:
        track = self.current_track
        if self.playing and self.player.is_playing:
            state = "PLAY"
        elif self.playing:
            state = "HOLD"
        elif track:
            state = "STOP"
        else:
            state = "STANDBY"

        pos = self.position if track else 0
        total = self.duration if track else 0
        clock = f"{fmt_time(pos)}/{fmt_time(total)}" if track else "--:--/--:--"
        mode = "RND" if self.shuffle else "SEQ"
        lines = [
            self._md(f"DECK-A {state}", 26),
            self._md(f"{clock} {bar(pos, total, 15)}", 26),
            self._md(f"MODE {mode}", 26),
        ]
        self.query_one("#lcd-player", Static).update(chr(10).join(lines))

    def _queue_position(self) -> str:
        total = len(self.filtered_tracks)
        if not total or self.current_index < 0:
            return f"-/{total}"
        return f"{self.current_index + 1}/{total}"

    def _tick_blink(self) -> None:
        """Event area blinks for ~1.6s whenever a new event arrives."""
        if time.monotonic() >= self._blink_until:
            return
        self._blink_phase = not self._blink_phase
        self._render_events()

    def _tick_marquee(self) -> None:
        text = self._marquee_text
        try:
            width = max(20, self.query_one("#marquee").size.width - 4)
        except Exception:
            width = 60
        loop = text + "   +++   "
        while len(loop) < width + 1:
            loop += loop
        self._marquee_offset = (self._marquee_offset + 1) % max(1, len(text) + 9)
        window = (loop * 2)[self._marquee_offset:self._marquee_offset + width]
        try:
            self.query_one("#marquee", Static).update(f"[#b6ff3d]{window}[/]")
        except Exception:
            pass

    def set_marquee(self, text: str) -> None:
        self._marquee_text = text or "NO DISC"
        self._marquee_offset = 0

    def log_event(self, kind: str, message: str) -> None:
        """Event status area: buttons, playback, scrobble, boot/scan."""
        self.events.append((time.strftime("%H:%M:%S"), kind, message))
        self._blink_until = time.monotonic() + 1.6
        self._blink_phase = True
        self._render_events()

    def _render_events(self) -> None:
        colours = {"BTN": "#ffd166", "SCRB": "#8fd3ff", "PLAY": "#b6ff3d",
                   "STOP": "#ff8b8b", "BOOT": "#9fbf78", "SCAN": "#9fbf78",
                   "ERR": "#ff6b6b"}
        lines = []
        last = len(self.events) - 1
        for i, (stamp, kind, msg) in enumerate(self.events):
            colour = colours.get(kind, "#9fbf78")
            blink = i == last and self._blink_phase and time.monotonic() < self._blink_until
            style = "[reverse]" if blink else ""
            lines.append(f"{style}[{colour}]{stamp} {kind:<4}[/] [dim]{msg}[/]")
        try:
            self.query_one("#events", Static).update(chr(10).join(lines))
        except Exception:
            pass

    def _cancel_scrobble(self) -> None:
        if self._scrobble_timer:
            self._scrobble_timer.stop()
            self._scrobble_timer = None
        if self._pending_track is not None:
            self._pending_track = None
            self.scrobble_state = "cancelled"
            self.log_event("SCRB", "cancelled")

    def update_status(self, message: str) -> None:
        try:
            self.set_marquee(message)
        except Exception:
            pass

    # ── actions ──────────────────────────────────────────────────
    def action_toggle_play(self):
        if not self.current_track:
            # nothing loaded yet: play whatever is highlighted in the list
            tracklist = self.query_one("#tracklist", TrackList)
            idx = tracklist.index or 0
            if 0 <= idx < len(self.filtered_tracks):
                self.play_track(self.filtered_tracks[idx])
            return
        if not self.playing:
            self.play_track(self.current_track)
        elif self.playing:
            self.player.stop()
            self._cancel_scrobble()
            self.playing = False
            self._set_viz(False)
            self.refresh_panel()

    def action_stop(self):
        self.stop_playback()

    def action_next_track(self):
        tracks = self.filtered_tracks
        if not tracks:
            return
        if self.shuffle and len(tracks) > 1:
            pool = [t for t in tracks if t is not self.current_track]
            self.play_track(random.choice(pool))
        elif 0 <= self.current_index < len(tracks) - 1:
            self.play_track(tracks[self.current_index + 1])

    def action_prev_track(self):
        tracks = self.filtered_tracks
        if not tracks:
            return
        if self.shuffle and len(tracks) > 1:
            pool = [t for t in tracks if t is not self.current_track]
            self.play_track(random.choice(pool))
        elif self.current_index > 0:
            self.play_track(tracks[self.current_index - 1])

    def action_toggle_shuffle(self):
        self.shuffle = not self.shuffle
        self.refresh_panel()

    def _set_viz(self, playing: bool) -> None:
        for viz in self.query(Visualizer):
            viz.playing = playing

    def action_show_visualizer(self):
        self.push_screen(VisualizerScreen())

    def action_toggle_debug(self):
        """Line-number gutter along the LCD pane (debug only)."""
        self.show_lines = not self.show_lines
        self.query_one("#gutter").display = self.show_lines
        self.query_one("#btn-debug", Button).variant = (
            "primary" if self.show_lines else "default")
        self._update_gutter()
        self.log_event("DBG", "line numbers " + ("on" if self.show_lines else "off"))

    def _update_gutter(self) -> None:
        if not self.show_lines:
            return
        try:
            rows = self.query_one("#player").size.height
            self.query_one("#gutter", Static).update(
                chr(10).join(f"{i:>2}" for i in range(1, max(1, rows) + 1)))
        except Exception:
            pass

    def action_toggle_blackout(self):
        """Hide / show the left pane (track list) for a pure LCD display."""
        self.blacked_out = not self.blacked_out
        self.query_one("#main").set_class(self.blacked_out, "-blackout")
        self.query_one("#btn-blackout", Button).variant = (
            "primary" if self.blacked_out else "default")
        self.log_event("BTN", "BLK " + ("on" if self.blacked_out else "off"))

    def action_focus_search(self):
        self.query_one("#search", Input).focus()

    def on_unmount(self):
        self.player.stop()


def main():
    app = MusicPlayerApp()
    app.run()


if __name__ == "__main__":
    main()
