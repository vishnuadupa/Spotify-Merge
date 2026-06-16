"""
spotify_sync.py — Fetches Spotify library into SQLite + pushes pending changes back.

  fetch_library(sp, emit)  — pulls liked + owned + followed playlists → db
  push_changes(sp, emit)   — applies staged edits to Spotify, matching playlists BY NAME

Name-match push (the key v2 rule):
  On push, for each local playlist with staged tracks:
    • if a Spotify playlist with the SAME NAME exists on the account → merge (no dupes)
    • otherwise → create a new playlist with that name and add the tracks
"""

import collections
import json
import threading
import time

import spotipy

from db import (
    get_conn, upsert_track, upsert_audio_features, upsert_playlist,
    add_playlist_track, get_pending_changes, clear_change, rollup_genre, resolve_language,
)

BATCH = 50
LIKED_ID = "__liked__"

# ── proactive rate limiter ───────────────────────────────────────────────────
# Spotify limits by a ROLLING 30-second window (dev mode ~180 req/30s, unofficial).
# We self-throttle well under that so we never trigger a 429 storm mid-fetch.
_RL_LOCK = threading.Lock()
_RL_TIMES = collections.deque()
_RL_WINDOW = 30.0
_RL_MAX = 100          # conservative cap per 30s window (~3.3 req/s avg)


def _throttle():
    """Block until making another request keeps us under _RL_MAX per 30s window."""
    with _RL_LOCK:
        now = time.time()
        while _RL_TIMES and now - _RL_TIMES[0] > _RL_WINDOW:
            _RL_TIMES.popleft()
        if len(_RL_TIMES) >= _RL_MAX:
            sleep_for = _RL_WINDOW - (now - _RL_TIMES[0]) + 0.05
            if sleep_for > 0:
                time.sleep(sleep_for)
            now = time.time()
            while _RL_TIMES and now - _RL_TIMES[0] > _RL_WINDOW:
                _RL_TIMES.popleft()
        _RL_TIMES.append(time.time())


def _retry(fn, *args, **kwargs):
    for attempt in range(8):
        _throttle()
        try:
            return fn(*args, **kwargs)
        except spotipy.SpotifyException as e:
            if e.http_status == 429:
                wait = int(getattr(e, 'headers', {}).get('Retry-After', 5)) + 1
                time.sleep(wait)
            elif e.http_status in (500, 502, 503):
                time.sleep(2 ** attempt)
            else:
                raise
    raise RuntimeError(f"Max retries for {fn}")


def _pages(sp, first):
    page = first
    while page:
        for item in (page.get("items") or []):
            yield item
        page = _retry(sp.next, page) if page.get("next") else None


def _batched(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i+n]


def _playlist_track_uris(sp, pl_id):
    """All non-local, non-episode track URIs currently in a Spotify playlist."""
    uris = []
    for item in _pages(sp, _retry(sp.playlist_items, pl_id, limit=100,
                                  market="from_token", additional_types=["track"])):
        if not item:
            continue
        track = item.get("track")
        if not track or not track.get("id") or item.get("is_local") or track.get("is_local"):
            continue
        if track.get("type") == "episode":
            continue
        linked = track.get("linked_from") or {}
        uri = linked.get("uri") or track.get("uri") or ""
        if uri:
            uris.append(uri)
    return uris


# ════════════════════════════════════════════════════════════════════════════
#  FETCH
# ════════════════════════════════════════════════════════════════════════════

def fetch_library(sp: spotipy.Spotify, emit=None):
    def log(msg, level="info"):
        if emit: emit(type="log", level=level, msg=msg)

    def prog(cat, done, total):
        if emit: emit(type="progress", cat=cat, done=done, total=total)

    conn = get_conn()

    # ── liked songs ──────────────────────────────────────────────────────────
    log("Fetching Liked Songs…")
    conn.execute("INSERT OR IGNORE INTO playlists (id,name,is_liked_songs,track_count) VALUES (?,?,1,0)",
                 (LIKED_ID, "Liked Songs"))
    conn.commit()

    first = _retry(sp.current_user_saved_tracks, limit=50)
    total_liked = first.get("total", 0)
    prog("liked_songs", 0, total_liked)

    pos = 0
    for item in _pages(sp, first):
        track = item.get("track")
        if not track or not track.get("id") or track.get("type") != "track":
            continue
        with conn:
            upsert_track(conn, track)
            add_playlist_track(conn, LIKED_ID, track["id"], pos, item.get("added_at", ""))
        pos += 1
        if pos % 50 == 0:
            prog("liked_songs", pos, total_liked)
    conn.execute("UPDATE playlists SET track_count=? WHERE id=?", (pos, LIKED_ID))
    conn.commit()
    prog("liked_songs", pos, total_liked)
    log(f"Liked Songs: {pos} tracks.", "success")

    # ── owned + followed playlists ───────────────────────────────────────────
    log("Fetching playlists (owned + followed)…")
    uid = _retry(sp.current_user)["id"]
    all_pls = [p for p in _pages(sp, _retry(sp.current_user_playlists, limit=50)) if p]
    log(f"Found {len(all_pls)} playlists.")
    prog("playlists", 0, len(all_pls))

    for i, pl in enumerate(all_pls):
        pl_id = pl["id"]
        is_followed = pl.get("owner", {}).get("id") != uid
        with conn:
            upsert_playlist(conn, pl, followed=is_followed)
        track_pos = 0
        try:
            for item in _pages(sp, _retry(sp.playlist_items, pl_id, limit=100,
                                          market="from_token", additional_types=["track"])):
                if not item:
                    continue
                track = item.get("track")
                if not track or not track.get("id") or item.get("is_local") or track.get("is_local"):
                    continue
                if track.get("type") == "episode":
                    continue
                with conn:
                    upsert_track(conn, track)
                    add_playlist_track(conn, pl_id, track["id"], track_pos, item.get("added_at", ""))
                track_pos += 1
        except Exception as e:
            log(f"  '{pl.get('name')}': track fetch skipped ({e})", "warning")
        conn.execute("UPDATE playlists SET track_count=? WHERE id=?", (track_pos, pl_id))
        conn.commit()
        prog("playlists", i + 1, len(all_pls))
    log("Playlists done.", "success")

    # ── top tracks ───────────────────────────────────────────────────────────
    log("Fetching top tracks…")
    for tr in ("short_term", "medium_term", "long_term"):
        try:
            items = _retry(sp.current_user_top_tracks, limit=50, time_range=tr).get("items", [])
            with conn:
                conn.execute("DELETE FROM top_tracks WHERE time_range=?", (tr,))
                for rank, t in enumerate(items):
                    if not t or not t.get("id"):
                        continue
                    upsert_track(conn, t)
                    conn.execute("INSERT OR REPLACE INTO top_tracks (track_id,time_range,rank) VALUES (?,?,?)",
                                 (t["id"], tr, rank))
            conn.commit()
        except Exception as e:
            log(f"Top tracks ({tr}): {e}", "warning")
    log("Top tracks saved.", "success")

    # ── audio features (BPM, energy, mood data) ──────────────────────────────
    # NOTE: Spotify deprecated /audio-features on 2024-11-27. Apps without a
    # prior quota extension get 403. We stop on the first 403 so we don't waste
    # dozens of calls; language + genre filtering still work without it.
    log("Fetching audio features (BPM / energy / mood)…")
    ids = [r[0] for r in conn.execute("SELECT id FROM tracks WHERE features_fetched=0").fetchall()]
    prog("audio_features", 0, len(ids))
    done = 0
    af_disabled = False
    for chunk in _batched(ids, 100):
        if af_disabled:
            break
        try:
            feats = _retry(sp.audio_features, chunk) or []
            with conn:
                for f in feats:
                    if f:
                        upsert_audio_features(conn, f)
            conn.commit()
        except spotipy.SpotifyException as e:
            if e.http_status in (401, 403, 404):
                af_disabled = True
                log("Audio features unavailable — Spotify deprecated this endpoint (Nov 2024) "
                    "for apps without prior access. Skipping BPM/energy/mood; "
                    "language + genre filters still work.", "warning")
            else:
                log(f"Audio features batch failed: {e}", "warning")
        except Exception as e:
            log(f"Audio features batch failed: {e}", "warning")
        done += len(chunk)
        prog("audio_features", done, len(ids))
    log("Audio features step done.", "success")

    # ── artist genres ────────────────────────────────────────────────────────
    log("Fetching artist genres…")
    artist_ids = [r[0] for r in conn.execute(
        "SELECT DISTINCT json_each.value FROM tracks, json_each(artist_ids)"
    ).fetchall()]
    done = 0
    for chunk in _batched(artist_ids, 50):
        try:
            res = _retry(sp.artists, chunk)
            with conn:
                for artist in (res.get("artists") or []):
                    if not artist:
                        continue
                    genres = json.dumps(artist.get("genres", []))
                    conn.execute("UPDATE tracks SET genres=? WHERE instr(artist_ids, ?)>0 AND genres='[]'",
                                 (genres, artist["id"]))
            conn.commit()
        except Exception as e:
            log(f"Artist genres chunk failed: {e}", "warning")
        done += len(chunk)
        if done % 200 == 0:
            prog("genres", done, len(artist_ids))

    # roll micro-genres up into top-level buckets + resolve language using genre
    # signals (so romanized titles like "Kesariya"/"Despacito" land in the right tab)
    log("Categorizing genres & languages…")
    rows = conn.execute("SELECT id, name, artists, album, genres FROM tracks").fetchall()
    with conn:
        for tid, name, aj, album, gj in rows:
            try:
                gl = json.loads(gj or "[]")
            except Exception:
                gl = []
            try:
                at = " ".join(json.loads(aj or "[]"))
            except Exception:
                at = ""
            conn.execute("UPDATE tracks SET genre_group=?, language=? WHERE id=?",
                         (rollup_genre(gl), resolve_language(name or "", gl, at, album or ""), tid))
    conn.commit()
    prog("genres", len(artist_ids), len(artist_ids))
    log("Genres categorized.", "success")

    log("Library fetch complete!", "success")
    if emit:
        emit(type="fetch_done")


# ════════════════════════════════════════════════════════════════════════════
#  PUSH  (name-match: merge into same-named playlist, else create)
# ════════════════════════════════════════════════════════════════════════════

def push_changes(sp: spotipy.Spotify, emit=None):
    def log(msg, level="info"):
        if emit: emit(type="log", level=level, msg=msg)

    conn = get_conn()
    changes = get_pending_changes(conn)
    if not changes:
        log("Nothing to push.", "info")
        if emit: emit(type="push_done", pushed=0)
        return

    log(f"Resolving {len(changes)} staged change(s)…")

    # 1. Group staged track ops by LOCAL playlist id
    #    adds[pl_id] = {track_id: uri};  removes[pl_id] = {track_id: uri}
    adds, removes = {}, {}
    liked_add, liked_remove = {}, {}
    for ch in changes:
        p = json.loads(ch["payload"])
        pid = p.get("playlist_id")
        if ch["type"] == "add_track":
            (liked_add if pid == LIKED_ID else adds.setdefault(pid, {}))[p["track_id"]] = p.get("uri", "")
        elif ch["type"] == "remove_track":
            (liked_remove if pid == LIKED_ID else removes.setdefault(pid, {}))[p["track_id"]] = p.get("uri", "")
        # create_playlist is implicit — handled when we resolve the name below

    # 2. Build a name→id map of the user's CURRENT Spotify playlists (owned only)
    uid = _retry(sp.current_user)["id"]
    name_to_id = {}
    for pl in _pages(sp, _retry(sp.current_user_playlists, limit=50)):
        if pl and pl.get("owner", {}).get("id") == uid:
            name_to_id[pl["name"].strip().lower()] = pl["id"]

    pushed = failed = created = 0

    # 3. Liked songs (no name matching needed)
    if liked_add:
        try:
            for chunk in _batched(list(liked_add.keys()), BATCH):
                _retry(sp.current_user_saved_tracks_add, chunk)
            pushed += len(liked_add)
            log(f"  ✓ Liked Songs: +{len(liked_add)}", "success")
        except Exception as e:
            failed += len(liked_add)
            log(f"  ✗ Liked Songs add failed: {e}", "error")
    if liked_remove:
        try:
            for chunk in _batched(list(liked_remove.keys()), BATCH):
                _retry(sp.current_user_saved_tracks_delete, chunk)
            pushed += len(liked_remove)
            log(f"  ✓ Liked Songs: −{len(liked_remove)}", "success")
        except Exception as e:
            failed += len(liked_remove)
            log(f"  ✗ Liked Songs remove failed: {e}", "error")

    # 4. Each playlist: resolve by NAME, merge or create
    touched_pl_ids = set(adds) | set(removes)
    for local_pid in touched_pl_ids:
        row = conn.execute("SELECT name, description FROM playlists WHERE id=?", (local_pid,)).fetchone()
        if not row:
            continue
        name, desc = row[0], (row[1] or "")
        key = name.strip().lower()

        # resolve target Spotify playlist id
        target_id = name_to_id.get(key)
        if not target_id:
            try:
                new_pl = _retry(sp._post, "me/playlists",
                                payload={"name": name, "public": False, "description": desc[:300]})
                target_id = new_pl["id"]
                name_to_id[key] = target_id
                created += 1
                log(f"  + Created playlist '{name}'", "success")
            except Exception as e:
                failed += 1
                log(f"  ✗ Could not create '{name}': {e}", "error")
                continue

        # additions — dedupe against what's already on Spotify
        want = adds.get(local_pid, {})
        if want:
            try:
                existing = set(_playlist_track_uris(sp, target_id))
                to_add = [uri for uri in want.values() if uri and uri not in existing]
                for chunk in _batched(to_add, 100):
                    _retry(sp.playlist_add_items, target_id, chunk)
                pushed += len(to_add)
                skipped = len(want) - len(to_add)
                msg = f"  ✓ '{name}': +{len(to_add)}"
                if skipped:
                    msg += f" ({skipped} already present)"
                log(msg, "success")
            except Exception as e:
                failed += len(want)
                log(f"  ✗ '{name}' add failed: {e}", "error")

        # removals
        gone = removes.get(local_pid, {})
        if gone:
            try:
                uris = [u for u in gone.values() if u]
                for chunk in _batched(uris, 100):
                    _retry(sp.playlist_remove_all_occurrences_of_items, target_id, chunk)
                pushed += len(uris)
                log(f"  ✓ '{name}': −{len(uris)}", "success")
            except Exception as e:
                failed += len(gone)
                log(f"  ✗ '{name}' remove failed: {e}", "error")

        # re-point the local playlist row at the real Spotify id
        if local_pid != target_id:
            with conn:
                conn.execute("UPDATE playlists SET id=?, local_only=0 WHERE id=?", (target_id, local_pid))
                conn.execute("UPDATE playlist_tracks SET playlist_id=? WHERE playlist_id=?", (target_id, local_pid))
                conn.execute("UPDATE workspace SET playlist_id=? WHERE playlist_id=?", (target_id, local_pid))

    # 5. clear the staged changes
    with conn:
        for ch in changes:
            clear_change(conn, ch["id"])

    log(f"Push complete — {pushed} ops applied, {created} playlists created, {failed} failed.",
        "success" if not failed else "warning")
    if emit:
        emit(type="push_done", pushed=pushed, created=created, failed=failed)
