#!/usr/bin/env python3
"""
AMPy UI ontology - the single source of truth for DESIGN and DEBUG.

Two audiences:
  * design  : regions, roles, row budget, wording rules (ASCII only)
  * debug   : ids, ordered layout, invariants that are machine-checked

Usage:
    python ui_ontology.py            # check the live app, print a report
    python ui_ontology.py --json     # machine readable report
    python ui_ontology.py --md       # regenerate UI_ONTOLOGY.md
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ─────────────────────────────────────────────────────────────────
# 1. REGIONS - vertical order of the main view (top to bottom)
# ─────────────────────────────────────────────────────────────────
@dataclass
class Region:
    id: str
    role: str                 # what it is for
    height: int               # expected rows (0 = flexible)
    border: str = "ascii"
    title: str = ""           # border title
    data: str = ""            # which state feeds it
    visible: bool = True


REGIONS: List[Region] = [
    Region("logo", "brand / identity", 7, title="OH MY LOGO",
           data="static: AMPy 5-line ASCII wordmark"),
    Region("events", "event status blink area", 4, title="EVENT STATUS",
           data="deque(maxlen=2): BOOT/SCAN/PLAY/SCRB/BTN/DBG"),
    Region("marquee", "song info marquee", 3, title="SONG INFO",
           data="_marquee_text scrolled 0.28s"),
    Region("lcd", "status panels", 5,
           data="TRACK | SCROB | PLAYER"),
    Region("controls", "control bar", 3,
           data="10 buttons"),
]

LCD_PANELS: List[Region] = [
    Region("lcd-track", "track identity", 5, data="current_track, current_index"),
    Region("lcd-scrob", "scrobble state", 5, data="scrobble_state, scrobbled_count"),
    Region("lcd-player", "deck state", 5, data="playing, position, duration, shuffle"),
]

CHROME: List[Region] = [
    Region("main", "root 3-pane container", 0),
    Region("sidebar", "pane 1 - library list", 0, border="solid",
           data="filtered_tracks"),
    Region("search", "filter input", 3),
    Region("tracklist", "track list", 0),
    Region("aside", "pane 3 - queue + stats", 0, border="solid",
           data="filtered_tracks, plays.db"),
    Region("queue", "up-next list", 12, data="filtered_tracks, shuffle"),
    Region("stats", "library statistics", 12, data="db_stats()"),
    Region("shell", "pane 2 wrapper", 0),
    Region("gutter", "debug line numbers", 0, border="none",
           data="show_lines"),
    Region("player", "LCD pane", 0),
]

PANE_WIDTHS = {"sidebar": 26, "aside": 24}   # %, centre pane takes the rest

VISUALIZER_VIEW: List[Region] = [
    Region("viz-head", "view title", 1),
    Region("viz-full", "ascii spectrum", 0, title="VISUALIZER"),
]

# ─────────────────────────────────────────────────────────────────
# 2. CONTROLS - button -> action -> effect
# ─────────────────────────────────────────────────────────────────
CONTROLS: Dict[str, Dict[str, str]] = {
    "btn-prev":    {"label": "<<",  "action": "action_prev_track",  "effect": "prev track (random when shuffle)"},
    "btn-play":    {"label": ">",   "action": "action_toggle_play", "effect": "play/resume or hold"},
    "btn-stop":    {"label": "||",  "action": "action_stop",        "effect": "stop, keep track loaded"},
    "btn-next":    {"label": ">>",  "action": "action_next_track",  "effect": "next track (random when shuffle)"},
    "btn-shuffle": {"label": "RND", "action": "action_toggle_shuffle", "effect": "SEQ <-> RND"},
    "btn-palette": {"label": "PAL", "action": "action_command_palette", "effect": "command palette"},
    "btn-blackout":{"label": "BLK", "action": "action_toggle_blackout", "effect": "dim list letters"},
    "btn-vis":     {"label": "VIS", "action": "action_show_visualizer", "effect": "push VisualizerScreen"},
    "btn-debug":   {"label": "DBG", "action": "action_toggle_debug", "effect": "toggle line-number gutter"},
    "btn-quit":    {"label": "EXIT","action": "action_quit",        "effect": "leave app"},
}

BINDINGS: Dict[str, str] = {
    "q": "quit", "space": "toggle_play", "n": "next_track", "p": "prev_track",
    "s": "stop", "/": "focus_search", "r": "toggle_shuffle", "b": "toggle_blackout",
}
# The footer shows no keys at all (palette is a button only).
FOOTER_KEYS_VISIBLE = 0

# ─────────────────────────────────────────────────────────────────
# 3. STATE + EVENTS
# ─────────────────────────────────────────────────────────────────
STATE = {
    "current_track": "Optional[Track] - loaded disc",
    "playing": "bool - process alive and not stopped by user",
    "position": "float - seconds from ffplay tracker",
    "duration": "float - from library cache / ffprobe prefetch",
    "shuffle": "bool - RND mode",
    "scrobble_state": "idle|wait Ns|sending...|submitted|cancelled|skipped|error",
    "scrobbled_count": "int - rows in plays.db",
    "blacked_out": "bool - list letters sunk to #14180f",
    "show_lines": "bool - debug gutter",
    "scan_done": "bool - background library scan finished",
    "_scrobble_timer": "Timer - 15s delay before scrobbling",
}

EVENTS = {
    "BOOT": "startup: N tracks loaded (cache) or scanning",
    "SCAN": "background scan finished",
    "PLAY": "track started",
    "SCRB": "armed / sending / OK / cancelled",
    "BTN": "every control bar press",
    "DBG": "gutter toggled",
}
BLINK_MS = 1600          # newest event line reverse-video blink window
SCROBBLE_DELAY_S = 15    # scrobble only after this much playback

# ─────────────────────────────────────────────────────────────────
# 4. INVARIANTS - checked automatically by `check()`
# ─────────────────────────────────────────────────────────────────
REMOVED_IDS = ["#rule", "#progress", "#status", "#vol-gauge", "#title", "#deck"]

EMOJI_RE = re.compile(
    "[\u2190-\u21ff\u2300-\u23ff\u2460-\u27bf\u2b00-\u2bff"
    "\U0001f000-\U0001faff\u2600-\u26ff\ufe0f]"
)


@dataclass
class Finding:
    level: str      # "error" | "warn" | "info"
    rule: str
    detail: str


def _text_of(widget) -> str:
    try:
        return str(widget.render())
    except Exception:
        try:
            return str(widget._content)
        except Exception:
            return ""


async def check(app) -> List[Finding]:
    """Mount the real app headless and verify the ontology."""
    out: List[Finding] = []
    screen_h = 40
    async with app.run_test(size=(120, screen_h)) as pilot:
        for _ in range(80):
            await pilot.pause()
            await asyncio.sleep(0.02)
            if app.scan_done:
                break

        # R1: every modelled region exists
        for region in REGIONS + LCD_PANELS + CHROME + VISUALIZER_VIEW:
            try:
                app.query_one(f"#{region.id}")
            except Exception:
                if region.id in ("viz-head", "viz-full"):
                    continue          # only present on the pushed screen
                out.append(Finding("error", "R1.exists", f"missing #{region.id}"))

        # R2: row heights match the design
        for region in REGIONS:
            try:
                h = app.query_one(f"#{region.id}").region.height
            except Exception:
                continue
            if h != region.height:
                out.append(Finding("error", "R2.height",
                                   f"#{region.id} h={h} expected {region.height}"))

        # R3: removed elements stay removed
        for rid in REMOVED_IDS:
            try:
                app.query_one(rid)
                out.append(Finding("error", "R3.removed", f"{rid} is back"))
            except Exception:
                pass

        # R4: no percentage readout anywhere (bar is enough)
        for widget in app.query("Static"):
            if "%" in _text_of(widget):
                out.append(Finding("warn", "R4.nopercent",
                                   f"'{_text_of(widget)}' shows a percentage"))

        # R5: ASCII only (no emoji / pictographs)
        for widget in app.query("Static"):
            bad = EMOJI_RE.findall(_text_of(widget))
            if bad:
                out.append(Finding("error", "R5.ascii",
                                   f"#{widget.id} has symbols {bad[:4]}"))

        # R6: controls fit in their pane
        controls = app.query_one("#controls")
        last = controls.children[-1]
        if last.region.right > controls.region.right:
            out.append(Finding("error", "R6.fits",
                               f"controls need {last.region.right - controls.region.x} "
                               f"cols, have {controls.region.width}"))

        # R7: all buttons present and wired
        ids = {b.id for b in controls.children}
        for bid in CONTROLS:
            if bid not in ids:
                out.append(Finding("error", "R7.button", f"missing {bid}"))

        # R8: footer shows no key hints
        visible = [b.key for b in app.BINDINGS if b.show]
        if len(visible) != FOOTER_KEYS_VISIBLE:
            out.append(Finding("warn", "R8.footer", f"visible keys {visible}"))

        # R9: menu state machine - STOP keeps the track, VIS is a screen
        track = app.filtered_tracks[0] if app.filtered_tracks else None
        if track:
            app.play_track(track)
            await asyncio.sleep(0.4)
            if not app.playing:
                out.append(Finding("error", "R9.play", "ffplay did not start"))
            app.action_stop()
            await pilot.pause()
            if app.playing or app.current_track is None:
                out.append(Finding("error", "R9.stop",
                                   "STOP must keep current_track for resume"))
            app.action_show_visualizer()
            await pilot.pause()
            if type(app.screen).__name__ != "VisualizerScreen":
                out.append(Finding("error", "R9.vis", "VIS did not push a screen"))
            await pilot.press("escape")
            await pilot.pause()
            app.action_stop()
            await pilot.pause()

        # R11: three columns + full-width control bar
        main = app.query_one("#main")
        side = app.query_one("#sidebar")
        aside = app.query_one("#aside")
        centre = app.query_one("#shell")
        total = main.region.width
        for name, expect in PANE_WIDTHS.items():
            got = app.query_one(f"#{name}").region.width * 100 / total
            if abs(got - expect) > 6:
                out.append(Finding("warn", "R11.pane",
                                   f"#{name} is {got:.0f}% (design {expect}%)"))
        if centre.region.width <= 0:
            out.append(Finding("error", "R11.pane", "#shell has no width"))
        if side.region.right > aside.region.x or aside.region.right > centre.region.x:
            out.append(Finding("error", "R11.pane", "panes overlap"))
        ctl_row = app.query_one("#controls")
        if ctl_row.region.width != app.size.width:
            out.append(Finding("warn", "R11.controls",
                               f"control bar {ctl_row.region.width} != screen {app.size.width}"))

        # R10: total vertical budget
        used = sum(app.query_one(f"#{r.id}").region.height for r in REGIONS)
        if used > screen_h - 4:
            out.append(Finding("warn", "R10.budget", f"{used} rows used of {screen_h}"))

        out.append(Finding("info", "summary",
                           f"{len(REGIONS)} regions, {used} rows, "
                           f"{len(CONTROLS)} controls, {len(BINDINGS)} bindings"))
    return out


# ─────────────────────────────────────────────────────────────────
# 5. reporting
# ─────────────────────────────────────────────────────────────────
def render_markdown() -> str:
    lines = ["# AMPy UI ontology", "",
             "Auto-generated by `ui_ontology.py --md`. Do not edit by hand.", "",
             "## Vertical layout (main view)", "",
             "| # | id | role | rows | border | title | data |",
             "|---|----|------|------|--------|-------|------|"]
    for i, r in enumerate(REGIONS, 1):
        lines.append(f"| {i} | `{r.id}` | {r.role} | {r.height} | {r.border} "
                     f"| {r.title or '-'} | {r.data} |")
    lines += ["", f"**Row budget:** {sum(r.height for r in REGIONS)} rows", "",
              "## LCD panels", "",
              "| id | role | rows | data |", "|----|------|------|------|"]
    for r in LCD_PANELS:
        lines.append(f"| `{r.id}` | {r.role} | {r.height} | {r.data} |")
    lines += ["", "## Controls", "",
              "| button | label | action | effect |",
              "|--------|-------|--------|--------|"]
    for bid, c in CONTROLS.items():
        lines.append(f"| `{bid}` | `{c['label']}` | `{c['action']}` | {c['effect']} |")
    lines += ["", "## Key bindings (hidden from footer)", "",
              "| key | action |", "|-----|--------|"]
    for k, a in BINDINGS.items():
        lines.append(f"| `{k}` | `{a}` |")
    lines += ["", "## State", "", "| field | meaning |", "|-------|---------|"]
    for k, v in STATE.items():
        lines.append(f"| `{k}` | {v} |")
    lines += ["", "## Events", "", "| kind | meaning |", "|------|---------|"]
    for k, v in EVENTS.items():
        lines.append(f"| `{k}` | {v} |")
    lines += ["", "## Rules", "",
              f"- newest event line blinks for {BLINK_MS} ms",
              f"- scrobble fires only after {SCROBBLE_DELAY_S}s of playback",
              "- ASCII only: no emoji, no pictographs, no percentage text",
              "- STOP keeps the track loaded so `>` can resume",
              "- `VIS` lives in its own `VisualizerScreen`",
              "- removed ids must stay removed: " + ", ".join(f"`{r}`" for r in REMOVED_IDS),
              ""]
    return "\n".join(lines)


async def _run() -> List[Finding]:
    import tui_player
    return await check(tui_player.MusicPlayerApp())


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "--md":
        print(render_markdown())
        return 0
    findings = asyncio.run(_run())
    if mode == "--json":
        print(json.dumps([f.__dict__ for f in findings], indent=2))
    else:
        icons = {"error": "FAIL", "warn": "WARN", "info": "INFO"}
        for f in findings:
            print(f"[{icons.get(f.level, f.level)}] {f.rule:12s} {f.detail}")
    return 1 if any(f.level == "error" for f in findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
