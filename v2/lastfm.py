"""
lastfm.py — enrich tracks with community tags from Last.fm.

Spotify 403s genre/audio data for dev-mode apps, so we recover the language +
genre signal from Last.fm's `track.getTopTags`. Tags like "telugu", "bollywood",
"k-pop", "reggaeton" map cleanly to language and genre.

Deployable: uses ONE app-level API key (env LASTFM_API_KEY, or config.json
"lastfm_api_key"). End users never supply their own.
Get a free key: https://www.last.fm/api/account/create
"""

import os
import time
import requests

API = "https://ws.audioscrobbler.com/2.0/"


def get_api_key(cfg: dict | None = None) -> str:
    return (os.environ.get("LASTFM_API_KEY")
            or (cfg or {}).get("lastfm_api_key", "")).strip()


def track_tags(artist: str, track: str, key: str, session: requests.Session = None) -> list[str]:
    """Top community tags for a track. Empty list on miss/error."""
    s = session or requests
    try:
        r = s.get(API, params={
            "method": "track.gettoptags",
            "artist": artist, "track": track,
            "api_key": key, "format": "json", "autocorrect": 1,
        }, timeout=10)
        if r.status_code != 200:
            return []
        data = r.json()
        tags = (data.get("toptags") or {}).get("tag") or []
        # keep tags with meaningful weight; lowercase, deduped, order preserved
        out = []
        for t in tags:
            name = (t.get("name") or "").strip().lower()
            if name and name not in out:
                out.append(name)
        return out[:12]
    except Exception:
        return []
