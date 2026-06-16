"""
migrator.py — Migration engine for v2.

Wraps every Spotify API call with automatic rate-limit retry (429 backoff).
Emits progress via a callback so the Flask SSE stream can forward it to the UI.
"""

import time
import threading
from typing import Callable, Optional, Iterator, Any

import spotipy

BATCH = 50
BATCH_PL = 100
BASE_PAUSE = 0.15


def _batched(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def _retry(fn, *args, max_retries=6, **kwargs):
    """Call fn(*args, **kwargs), retrying on 429 with Retry-After backoff."""
    for attempt in range(max_retries):
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
    raise RuntimeError(f"Max retries exceeded for {fn.__name__}")


class Migrator:
    def __init__(
        self,
        old: spotipy.Spotify,
        new: spotipy.Spotify,
        emit: Optional[Callable] = None,
        stop: Optional[threading.Event] = None,
    ):
        self.old = old
        self.new = new
        self._emit = emit or (lambda **kw: None)
        self._stop = stop or threading.Event()

    def _check(self):
        if self._stop.is_set():
            raise InterruptedError("Migration cancelled")

    def _log(self, msg: str, level: str = "info"):
        self._emit(type="log", level=level, msg=msg)

    def _progress(self, cat: str, done: int, total: int):
        self._emit(type="progress", cat=cat, done=done, total=total)

    # ------------------------------------------------------------------ paging

    def _pages(self, sp: spotipy.Spotify, first: dict) -> Iterator[Any]:
        page = first
        while page:
            for item in (page.get("items") or []):
                yield item
            self._check()
            page = _retry(sp.next, page) if page.get("next") else None

    # ------------------------------------------------------------------ liked songs

    def migrate_liked_songs(self):
        cat = "liked_songs"
        self._log("Liked Songs: reading old account...")
        old_ids = [
            it["track"]["id"]
            for it in self._pages(self.old, _retry(self.old.current_user_saved_tracks, limit=50))
            if it.get("track") and it["track"].get("id") and it["track"].get("type") == "track"
        ]
        old_ids = list(reversed(old_ids))

        self._log(f"Liked Songs: {len(old_ids)} found on old account. Checking new account...")
        existing = {
            it["track"]["id"]
            for it in self._pages(self.new, _retry(self.new.current_user_saved_tracks, limit=50))
            if it.get("track") and it["track"].get("id")
        }

        to_add = [i for i in old_ids if i not in existing]
        skipped = len(old_ids) - len(to_add)
        self._log(f"Liked Songs: {skipped} already on new account, adding {len(to_add)}.")
        self._progress(cat, 0, len(to_add))

        added = 0
        failed = 0
        for chunk in _batched(to_add, BATCH):
            self._check()
            try:
                _retry(self.new.current_user_saved_tracks_add, chunk)
                added += len(chunk)
            except Exception as e:
                self._log(f"Liked Songs: batch failed — {e}", "error")
                failed += len(chunk)
            self._progress(cat, added + failed, len(to_add))
            time.sleep(BASE_PAUSE)

        level = "success" if not failed else "warning"
        self._log(f"Liked Songs: done — {added} added, {skipped} skipped, {failed} failed.", level)
        return {"added": added, "skipped": skipped, "failed": failed}

    # ------------------------------------------------------------------ followed artists

    def migrate_followed_artists(self):
        cat = "followed_artists"
        self._log("Followed Artists: reading old account...")

        def fetch_artists(sp):
            ids, after = [], None
            while True:
                res = _retry(sp.current_user_followed_artists, limit=50, after=after)["artists"]
                ids.extend(a["id"] for a in res["items"])
                if res.get("next") and res["items"]:
                    after = res["items"][-1]["id"]
                else:
                    break
            return ids

        old_ids = fetch_artists(self.old)
        existing = set(fetch_artists(self.new))
        to_add = [i for i in old_ids if i not in existing]
        skipped = len(old_ids) - len(to_add)
        self._log(f"Followed Artists: {skipped} already followed, adding {len(to_add)}.")
        self._progress(cat, 0, len(to_add))

        added = 0
        for chunk in _batched(to_add, BATCH):
            self._check()
            try:
                _retry(self.new.user_follow_artists, chunk)
                added += len(chunk)
            except Exception as e:
                self._log(f"Followed Artists: batch failed — {e}", "error")
            self._progress(cat, added, len(to_add))
            time.sleep(BASE_PAUSE)

        self._log(f"Followed Artists: done — {added} followed, {skipped} skipped.", "success")
        return {"added": added, "skipped": skipped}

    # ------------------------------------------------------------------ playlists

    def _get_playlist_tracks(self, sp: spotipy.Spotify, pl_id: str) -> list[str]:
        uris = []
        for it in self._pages(sp, _retry(sp.playlist_items, pl_id, limit=100, market="from_token", additional_types=["track"])):
            if not it:
                continue
            track = it.get("track")
            if not track or it.get("is_local") or track.get("is_local"):
                continue
            linked = track.get("linked_from") or {}
            uri = linked.get("uri") or track.get("uri") or ""
            if uri and not uri.startswith("spotify:episode:"):
                uris.append(uri)
        return uris

    def migrate_owned_playlists(self):
        cat = "owned_playlists"
        old_uid = _retry(self.old.current_user)["id"]
        new_uid = _retry(self.new.current_user)["id"]

        self._log("Playlists: reading old account...")
        owned = [
            pl for pl in self._pages(self.old, _retry(self.old.current_user_playlists, limit=50))
            if pl and pl.get("owner", {}).get("id") == old_uid
        ]

        self._log("Playlists: reading new account...")
        new_by_name = {}
        for pl in self._pages(self.new, _retry(self.new.current_user_playlists, limit=50)):
            if pl and pl.get("owner", {}).get("id") == new_uid:
                new_by_name[pl["name"]] = pl["id"]

        self._log(f"Playlists: {len(owned)} owned on old account.")
        self._progress(cat, 0, len(owned))

        total_added = total_skipped = total_failed = 0

        for i, pl in enumerate(owned):
            self._check()
            pl_id, pl_name = pl["id"], pl["name"]
            self._log(f"  '{pl_name}': fetching tracks...")

            try:
                old_uris = self._get_playlist_tracks(self.old, pl_id)
            except Exception as e:
                self._log(f"  '{pl_name}': failed to read — {e}", "error")
                total_failed += 1
                self._progress(cat, i + 1, len(owned))
                continue

            if pl_name in new_by_name:
                target_id = new_by_name[pl_name]
                self._log(f"  '{pl_name}': exists on new account, checking for missing tracks...")
                try:
                    existing_uris = set(self._get_playlist_tracks(self.new, target_id))
                except Exception:
                    existing_uris = set()

                to_add = [u for u in old_uris if u not in existing_uris]
                skipped = len(old_uris) - len(to_add)
                total_skipped += skipped
                self._log(f"  '{pl_name}': {skipped} already present, adding {len(to_add)}.")

                for chunk in _batched(to_add, BATCH_PL):
                    self._check()
                    try:
                        _retry(self.new.playlist_add_items, target_id, chunk)
                        total_added += len(chunk)
                    except Exception as e:
                        self._log(f"  '{pl_name}': batch failed — {e}", "error")
                        total_failed += len(chunk)
                    time.sleep(BASE_PAUSE)
            else:
                self._log(f"  '{pl_name}': not found on new account, creating...")
                try:
                    new_pl = _retry(self.new._post, "me/playlists", payload={
                        "name": pl_name,
                        "public": bool(pl.get("public")),
                        "description": (pl.get("description") or "")[:300],
                    })
                    target_id = new_pl["id"]
                    new_by_name[pl_name] = target_id
                    for chunk in _batched(old_uris, BATCH_PL):
                        self._check()
                        _retry(self.new.playlist_add_items, target_id, chunk)
                        total_added += len(chunk)
                        time.sleep(BASE_PAUSE)
                    self._log(f"  '{pl_name}': created with {len(old_uris)} tracks.", "success")
                except Exception as e:
                    self._log(f"  '{pl_name}': create failed — {e}", "error")
                    total_failed += 1

            self._progress(cat, i + 1, len(owned))

        self._log(f"Playlists: done — {total_added} tracks added, {total_skipped} skipped, {total_failed} failed.", "success")
        return {"added": total_added, "skipped": total_skipped, "failed": total_failed}

    # ------------------------------------------------------------------ saved albums

    def migrate_saved_albums(self):
        cat = "saved_albums"
        self._log("Saved Albums: reading old account...")
        old_ids = [
            it["album"]["id"]
            for it in self._pages(self.old, _retry(self.old.current_user_saved_albums, limit=50))
            if it.get("album") and it["album"].get("id")
        ]
        existing = {
            it["album"]["id"]
            for it in self._pages(self.new, _retry(self.new.current_user_saved_albums, limit=50))
            if it.get("album") and it["album"].get("id")
        }
        to_add = [i for i in old_ids if i not in existing]
        skipped = len(old_ids) - len(to_add)
        self._log(f"Saved Albums: {skipped} already saved, adding {len(to_add)}.")
        self._progress(cat, 0, len(to_add))

        added = 0
        for chunk in _batched(to_add, BATCH):
            self._check()
            try:
                _retry(self.new.current_user_saved_albums_add, chunk)
                added += len(chunk)
            except Exception as e:
                self._log(f"Saved Albums: batch failed — {e}", "error")
            self._progress(cat, added, len(to_add))
            time.sleep(BASE_PAUSE)

        self._log(f"Saved Albums: done — {added} added, {skipped} skipped.", "success")
        return {"added": added, "skipped": skipped}

    # ------------------------------------------------------------------ run all

    def run(self, cats: dict) -> dict:
        results = {}
        if cats.get("liked_songs"):
            results["liked_songs"] = self.migrate_liked_songs()
        if cats.get("owned_playlists"):
            results["owned_playlists"] = self.migrate_owned_playlists()
        if cats.get("followed_artists"):
            results["followed_artists"] = self.migrate_followed_artists()
        if cats.get("saved_albums"):
            results["saved_albums"] = self.migrate_saved_albums()
        self._emit(type="done", results=results)
        return results
