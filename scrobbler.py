#!/usr/bin/env python3
"""music-scrobble: Last.fm scrobble checker with SQLite DB"""
import sqlite3, os, sys, time, json, hashlib

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plays.db")
CREDS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".lastfm_creds")


def _creds():
    out = {}
    try:
        with open(CREDS_FILE, encoding="utf-8") as f:
            for line in f:
                if "=" in line:
                    k, v = line.split("=", 1)
                    out[k.strip()] = v.strip()
    except OSError:
        pass
    return out


def _api_secret():
    secret = _creds().get("api_secret", "")
    if secret:
        return secret
    return os.environ.get("LASTFM_API_SECRET", "").strip()


def _api_key():
    key = _creds().get("api_key", "")
    return key or os.environ.get("LASTFM_API_KEY", "").strip()


API_KEY = _api_key()

def init():
    conn = sqlite3.connect(DB)
    conn.execute("CREATE TABLE IF NOT EXISTS plays (id INTEGER PRIMARY KEY, path TEXT UNIQUE, artist TEXT, title TEXT, duration INTEGER, played_at INTEGER, scrobbled INTEGER DEFAULT 0)")
    conn.commit()

def parse_filename(path):
    base = os.path.splitext(os.path.basename(path))[0]
    if " - " in base:
        parts = base.split(" - ", 1)
        return parts[0].strip(), parts[1].strip()
    return "", base

import requests

SESSION_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".lastfm_session")


def session_key():
    """Session key from env, or from .lastfm_session (created by lastfm_auth.py)."""
    key = os.environ.get("LASTFM_SESSION_KEY", "").strip()
    if key:
        return key
    try:
        with open(SESSION_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def scrobble(path, artist=None, title=None, duration=0):
    if not API_KEY:
        return {"status": "no LASTFM_API_KEY", "path": path}
    sk = session_key()
    if not sk:
        return {"status": "no session key - run: python lastfm_auth.py", "path": path}
    a, t = parse_filename(path)
    artist = artist or a
    title = title or t
    now = int(time.time())
    data = {
        "method": "track.scrobble", "api_key": API_KEY, "sk": sk,
        "artist": artist, "track": title, "timestamp": str(now), "format": "json",
    }
    if duration:
        data["duration"] = str(int(duration))
    secret = _api_secret()
    if secret:
        raw = "".join(f"{k}{data[k]}" for k in sorted(data) if k != "format") + secret
        data["api_sig"] = hashlib.md5(raw.encode()).hexdigest()
    try:
        r = requests.post("https://ws.audioscrobbler.com/2.0/", data=data, timeout=10)
        try:
            payload = r.json()
        except ValueError:
            payload = {"raw": r.text[:200]}
        if r.status_code == 200 and "error" not in payload and "scrobbles" in payload:
            # update db every time
            init()
            conn = sqlite3.connect(DB)
            conn.execute("""
                INSERT INTO plays (path, artist, title, duration, played_at, scrobbled)
                VALUES (?, ?, ?, ?, ?, 1)
                ON CONFLICT(path) DO UPDATE SET
                    artist=excluded.artist,
                    title=excluded.title,
                    duration=excluded.duration,
                    played_at=excluded.played_at,
                    scrobbled=1
            """, (path, artist, title, int(duration or 0), now))
            conn.commit()
            conn.close()
            return {"status": "submitted", "artist": artist, "track": title, "path": path,
                    "ignored": payload["scrobbles"].get("@attr", {}).get("ignored")}
        return {"status": "rejected", "http": r.status_code, "artist": artist,
                "track": title, "lastfm_error": payload, "path": path}
    except Exception as e:
        return {"status": "error", "error": str(e), "path": path}

def play_folder(folder):
    files = sorted(f for f in os.listdir(folder) if f.lower().endswith(".mp3"))
    results = []
    for f in files:
        path = os.path.join(folder, f)
        r = scrobble(path)
        results.append(r)
    return results

def resend_pending():
    """Re-submit every row marked scrobbled=0 (after lastfm_auth.py)."""
    init()
    conn = sqlite3.connect(DB)
    rows = conn.execute("SELECT path, artist, title, duration FROM plays WHERE scrobbled=0").fetchall()
    conn.close()
    return [scrobble(p, a, t, d) for (p, a, t, d) in rows]

def db_stats():
    init()
    conn = sqlite3.connect(DB)
    rows = conn.execute("SELECT * FROM plays").fetchall()
    return {"total": len(rows), "rows": rows}

def check_lastfm_library():
    """Check Last.fm library for tracks we've played"""
    if not API_KEY:
        return {"error": "no LASTFM_API_KEY"}
    import requests
    # Get recent tracks
    r = requests.get("https://ws.audioscrobbler.com/2.0/", params={
        "method": "user.getrecenttracks",
        "user": "kanalsound",
        "api_key": API_KEY,
        "limit": 50,
        "format": "json"
    })
    if r.status_code != 200:
        return {"error": f"HTTP {r.status_code}", "body": r.text[:500]}
    data = r.json()
    tracks = data.get("recenttracks", {}).get("track", [])
    return {"total": len(tracks), "tracks": [{"artist": t.get("artist", {}).get("#text", ""), "title": t.get("name", ""), "date": t.get("date", {}).get("uts", "")} for t in tracks]}

if __name__ == "__main__":
    init()
    if len(sys.argv) > 1:
        if sys.argv[1] == "play":
            folder = sys.argv[2] if len(sys.argv) > 2 else "C:/Users/dance/Music/mp3/sanjay_nara"
            results = play_folder(folder)
            print(json.dumps(results, indent=2, ensure_ascii=False))
        elif sys.argv[1] == "stats":
            print(json.dumps(db_stats(), indent=2, ensure_ascii=False))
        elif sys.argv[1] == "lastfm":
            print(json.dumps(check_lastfm_library(), indent=2, ensure_ascii=False))
        elif sys.argv[1] == "scrobble":
            print(json.dumps(scrobble(sys.argv[2]), indent=2, ensure_ascii=False))
        elif sys.argv[1] == "resend":
            print(json.dumps(resend_pending(), indent=2, ensure_ascii=False))
    else:
        print("music-scrobble ready")