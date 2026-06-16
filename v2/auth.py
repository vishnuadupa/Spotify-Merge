"""
auth.py — OAuth management for both Spotify accounts.

Uses a local Flask server as the redirect_uri so the user just clicks
"Authorize" in the browser — no token copy-pasting.
"""

import json
import os
import time
import threading
import webbrowser
from urllib.parse import urlencode, urlparse, parse_qs

import requests
import spotipy
from spotipy.oauth2 import SpotifyOAuth

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REDIRECT_URI = "http://127.0.0.1:5174/callback"

SCOPES = " ".join([
    "user-library-read",
    "user-library-modify",
    "playlist-read-private",
    "playlist-read-collaborative",
    "playlist-modify-private",
    "playlist-modify-public",
    "user-follow-read",
    "user-follow-modify",
    "user-read-private",
    "user-read-email",
])


def _cache_path(label: str) -> str:
    return os.path.join(BASE_DIR, f".cache-{label}")


def make_auth_manager(client_id: str, client_secret: str, label: str) -> SpotifyOAuth:
    return SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=REDIRECT_URI,
        scope=SCOPES,
        cache_path=_cache_path(label),
        open_browser=False,
    )


def get_spotify(client_id: str, client_secret: str, label: str) -> spotipy.Spotify:
    """Return an authenticated Spotify client, loading from cache if valid."""
    mgr = make_auth_manager(client_id, client_secret, label)
    token = mgr.get_cached_token()
    if token and not mgr.is_token_expired(token):
        return spotipy.Spotify(auth_manager=mgr, retries=0)
    return None


def get_auth_url(client_id: str, client_secret: str, label: str) -> str:
    mgr = make_auth_manager(client_id, client_secret, label)
    return mgr.get_authorize_url()


def handle_callback(client_id: str, client_secret: str, label: str, code: str) -> spotipy.Spotify:
    """Exchange auth code for token, cache it, return Spotify client."""
    mgr = make_auth_manager(client_id, client_secret, label)
    token = mgr.get_access_token(code, as_dict=True, check_cache=False)
    return spotipy.Spotify(auth_manager=mgr, retries=0)


def get_user_info(sp: spotipy.Spotify) -> dict:
    try:
        u = sp.current_user()
        return {"id": u["id"], "name": u.get("display_name") or u["id"], "ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}
