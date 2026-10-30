#!/usr/bin/env python3
"""
Last.fm one-time desktop auth helper (two-step, non-interactive friendly).

Gets a session key for scrobbling (needed by tui_player.py / scrobbler.py).

Credentials are read from env or CLI flags:
    LASTFM_API_KEY / --key
    LASTFM_API_SECRET / --secret

Steps:
    python lastfm_auth.py token     # prints authorize URL, saves .lastfm_token
    #   -> open URL in browser, click "Yes, allow access"
    python lastfm_auth.py finish    # exchanges token for session key

After `finish`, .lastfm_session and .lastfm_creds are written (both gitignored),
so tui_player.py / scrobbler.py work without environment variables.
"""
import getpass
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

API = "https://ws.audioscrobbler.com/2.0/"
HERE = Path(__file__).resolve().parent
SESSION_FILE = HERE / ".lastfm_session"
TOKEN_FILE = HERE / ".lastfm_token"
CREDS_FILE = HERE / ".lastfm_creds"


def arg(flag: str) -> str:
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return ""


def credentials() -> tuple[str, str]:
    key = os.environ.get("LASTFM_API_KEY", "").strip() or arg("--key")
    secret = os.environ.get("LASTFM_API_SECRET", "").strip() or arg("--secret")
    if not key:
        key = input("Last.fm API key: ").strip()
    if not secret:
        secret = getpass.getpass("Last.fm Shared secret (hidden): ").strip()
    if not key or not secret:
        sys.exit("API key and shared secret are both required.")
    return key, secret


def call(method: str, key: str, secret: str, **params) -> dict:
    params.update({"method": method, "api_key": key})
    raw = "".join(f"{k}{params[k]}" for k in sorted(params)) + secret
    params["api_sig"] = hashlib.md5(raw.encode()).hexdigest()
    params["format"] = "json"
    url = API + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        sys.exit(f"Last.fm HTTP {exc.code}: {exc.read().decode(errors='replace')}")


def cmd_token(key: str, secret: str) -> int:
    data = call("auth.getToken", key, secret)
    token = data.get("token")
    if not token:
        print(json.dumps(data, indent=2))
        return 1
    TOKEN_FILE.write_text(token, encoding="utf-8")
    url = f"https://www.last.fm/api/auth/?api_key={key}&token={token}"
    print(f"token: {token}")
    print(f"authorize: {url}")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    return 0


def cmd_finish(key: str, secret: str) -> int:
    try:
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        sys.exit("No .lastfm_token - run: python lastfm_auth.py token")
    data = call("auth.getSession", key, secret, token=token)
    session = data.get("session", {})
    session_key = session.get("key")
    if not session_key:
        print(json.dumps(data, indent=2))
        return 1
    SESSION_FILE.write_text(session_key, encoding="utf-8")
    CREDS_FILE.write_text(f"api_key={key}\napi_secret={secret}\n", encoding="utf-8")
    TOKEN_FILE.unlink(missing_ok=True)
    print(f"OK user={session.get('name')} session key saved to {SESSION_FILE.name}")
    return 0


def main() -> int:
    steps = [a for a in sys.argv[1:] if not a.startswith("--")]
    step = steps[0] if steps else "token"
    key, secret = credentials()
    if step == "token":
        return cmd_token(key, secret)
    if step == "finish":
        return cmd_finish(key, secret)
    sys.exit(f"Unknown step {step!r} (use: token | finish)")


if __name__ == "__main__":
    raise SystemExit(main())
