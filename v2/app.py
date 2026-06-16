"""
app.py — Flask backend for Spotify Migrator v2 (Library Manager edition).
"""

import json
import os
import queue
import sqlite3
import sys
import threading
import time
import uuid

from flask import Flask, jsonify, redirect, render_template, request, Response, url_for

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auth as _auth
import db as _db
import lastfm as _lastfm
from spotify_sync import fetch_library, push_changes

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config["TEMPLATES_AUTO_RELOAD"] = True          # pick up index.html edits without a restart
app.jinja_env.auto_reload = True
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0         # always serve fresh static CSS/JS

_db.init_db()

# ── shared state ───────────────────────────────────────────────────────────────
_sp = {"old": None, "new": None}
_auth_label = None
_event_q: queue.Queue = queue.Queue()
_stop = threading.Event()
_bg_thread: threading.Thread | None = None
_conn = _db.get_conn()   # shared read connection (writes use their own)


# ── config ─────────────────────────────────────────────────────────────────────

def _cfg():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {}


def _save_cfg(d):
    with open(CONFIG_FILE, "w") as f:
        json.dump(d, f, indent=2)


def _push(**kw):
    _event_q.put(kw)


# ── try loading cached tokens on startup ───────────────────────────────────────
for _lbl in ("old", "new"):
    try:
        cfg = _cfg()
        if cfg.get("client_id"):
            sp = _auth.get_spotify(cfg["client_id"], cfg["client_secret"], _lbl)
            if sp:
                _sp[_lbl] = sp
    except Exception:
        pass


# ── routes ─────────────────────────────────────────────────────────────────────

@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/app")
def workbench():
    return render_template("index.html")


@app.route("/api/config", methods=["POST"])
def api_config():
    b = request.get_json(force=True)
    cfg = _cfg()
    cfg["client_id"] = b.get("client_id", "").strip()
    cfg["client_secret"] = b.get("client_secret", "").strip()
    if "lastfm_api_key" in b:
        cfg["lastfm_api_key"] = b.get("lastfm_api_key", "").strip()
    _save_cfg(cfg)
    return jsonify({"ok": True})


@app.route("/api/status")
def api_status():
    cfg = _cfg()
    result = {
        "has_config": bool(cfg.get("client_id")),
        "has_lastfm": bool(_lastfm.get_api_key(cfg)),
        "old": None, "new": None,
        "library_loaded": _conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0] > 0,
        "stats": _db.get_library_stats(_conn),
    }
    for label in ("old", "new"):
        if _sp[label]:
            result[label] = _auth.get_user_info(_sp[label])
    return jsonify(result)


@app.route("/auth/<label>")
def start_auth(label):
    global _auth_label
    if label not in ("old", "new"): return "bad label", 400
    cfg = _cfg()
    _auth_label = label
    return redirect(_auth.get_auth_url(cfg["client_id"], cfg["client_secret"], label))


@app.route("/callback")
def callback():
    global _auth_label
    code = request.args.get("code")
    label = _auth_label
    if not code or not label:
        return redirect("/app?error=missing_code")
    cfg = _cfg()
    try:
        sp = _auth.handle_callback(cfg["client_id"], cfg["client_secret"], label, code)
        _sp[label] = sp
        _auth_label = None
        return redirect(f"/app?auth_done={label}")
    except Exception as e:
        return redirect(f"/app?error={str(e)[:80]}")


# ── library fetch ──────────────────────────────────────────────────────────────

@app.route("/api/library/fetch", methods=["POST"])
def api_fetch():
    global _bg_thread, _stop
    b = request.get_json(force=True) or {}
    label = b.get("account", "new")
    sp = _sp.get(label)
    if not sp:
        return jsonify({"error": f"Account '{label}' not authenticated"}), 400

    while not _event_q.empty():
        try: _event_q.get_nowait()
        except: pass

    _stop = threading.Event()

    def run():
        try:
            fetch_library(sp, emit=_push)
        except Exception as e:
            _push(type="error", msg=str(e))

    _bg_thread = threading.Thread(target=run, daemon=True)
    _bg_thread.start()
    return jsonify({"ok": True})


# ── tracks query ───────────────────────────────────────────────────────────────

@app.route("/api/tracks")
def api_tracks():
    q = request.args
    mood = q.get("mood", "")
    genre = q.get("genre", "")
    lang = q.get("language", "")
    decade = q.get("decade", "")
    playlist_id = q.get("playlist", "")
    search = q.get("q", "").strip().lower()
    energy_min = float(q.get("energy_min", 0))
    energy_max = float(q.get("energy_max", 1))
    bpm_min = float(q.get("bpm_min", 0))
    bpm_max = float(q.get("bpm_max", 300))
    sort = q.get("sort", "name")
    top = q.get("top", "")   # short_term | medium_term | long_term
    offset = int(q.get("offset", 0))
    limit = int(q.get("limit", 100))
    duplicates_only = q.get("duplicates", "")

    params = []
    clauses = ["1=1"]

    if playlist_id:
        clauses.append("t.id IN (SELECT track_id FROM playlist_tracks WHERE playlist_id=?)")
        params.append(playlist_id)
    if mood:
        clauses.append("t.mood=?")
        params.append(mood)
    if genre:
        clauses.append("t.genre_group=?")
        params.append(genre)
    if lang:
        clauses.append("t.language=?")
        params.append(lang)
    if decade:
        decade_start = int(decade)
        clauses.append("t.release_year>=? AND t.release_year<?")
        params += [decade_start, decade_start + 10]
    if search:
        clauses.append("(LOWER(t.name) LIKE ? OR LOWER(t.artists) LIKE ?)")
        params += [f"%{search}%", f"%{search}%"]
    clauses.append("t.energy>=? AND t.energy<=?")
    params += [energy_min, energy_max]
    if bpm_min > 0:
        clauses.append("t.tempo>=?")
        params.append(bpm_min)
    if bpm_max < 300:
        clauses.append("t.tempo<=?")
        params.append(bpm_max)
    if top:
        clauses.append("t.id IN (SELECT track_id FROM top_tracks WHERE time_range=?)")
        params.append(top)
    if duplicates_only:
        clauses.append("""
            t.id IN (
                SELECT track_id FROM playlist_tracks
                GROUP BY track_id HAVING COUNT(DISTINCT playlist_id) > 1
            )
        """)

    sort_col = {
        "name": "t.name", "energy": "t.energy DESC", "valence": "t.valence DESC",
        "tempo": "t.tempo DESC", "popularity": "t.popularity DESC",
        "year": "t.release_year DESC", "danceability": "t.danceability DESC",
        "top": "tt.rank ASC",
    }.get(sort, "t.name")

    join = "LEFT JOIN top_tracks tt ON tt.track_id=t.id AND tt.time_range=?" if sort == "top" else ""
    if sort == "top":
        params.insert(0, top or "medium_term")

    where = " AND ".join(clauses)
    sql = f"""
        SELECT t.*, GROUP_CONCAT(DISTINCT pt.playlist_id) as in_playlists
        FROM tracks t
        LEFT JOIN playlist_tracks pt ON pt.track_id=t.id
        {join}
        WHERE {where}
        GROUP BY t.id
        ORDER BY {sort_col}
        LIMIT ? OFFSET ?
    """
    params += [limit, offset]

    rows = _conn.execute(sql, params).fetchall()
    total = _conn.execute(f"SELECT COUNT(DISTINCT t.id) FROM tracks t {join} WHERE {where}",
                          params[:-2]).fetchone()[0]

    tracks = []
    for r in rows:
        d = dict(r)
        d["artists"] = json.loads(d.get("artists") or "[]")
        d["genres"] = json.loads(d.get("genres") or "[]")
        d["in_playlists"] = (d.get("in_playlists") or "").split(",") if d.get("in_playlists") else []
        tracks.append(d)

    return jsonify({"tracks": tracks, "total": total, "offset": offset})


# ── playlists ──────────────────────────────────────────────────────────────────

@app.route("/api/languages")
def api_languages():
    return jsonify(_db.get_languages(_conn))


@app.route("/api/genres")
def api_genres():
    return jsonify(_db.get_genres(_conn, request.args.get("language", "")))


@app.route("/api/recategorize", methods=["POST"])
def api_recategorize():
    with _db.get_conn() as c:
        result = _db.recategorize_all(c)
    return jsonify(result)


def _enrich_run():
    import requests as _rq
    cfg = _cfg()
    key = _lastfm.get_api_key(cfg)
    conn = _db.get_conn()
    rows = conn.execute("SELECT id, name, artists FROM tracks").fetchall()
    total = len(rows)
    sess = _rq.Session()
    _push(type="log", msg=f"Enriching {total} tracks from Last.fm…")
    _push(type="progress", cat="enrich", done=0, total=total)
    done = hit = 0
    for tid, name, aj in rows:
        try:
            artist = (json.loads(aj or "[]") or [""])[0]
        except Exception:
            artist = ""
        tags = _lastfm.track_tags(artist, name, key, sess) if (artist and name) else []
        if tags:
            hit += 1
            with conn:
                conn.execute("UPDATE tracks SET genres=? WHERE id=?", (json.dumps(tags), tid))
        done += 1
        if done % 25 == 0:
            _push(type="progress", cat="enrich", done=done, total=total)
        time.sleep(0.12)   # ~8 req/s — polite to Last.fm
    conn.commit()
    _db.recategorize_all(_db.get_conn())
    _push(type="progress", cat="enrich", done=total, total=total)
    _push(type="log", msg=f"Enriched {hit}/{total} tracks. Languages & genres re-grouped.", level="success")
    _push(type="enrich_done", hit=hit, total=total)


@app.route("/api/enrich", methods=["POST"])
def api_enrich():
    global _bg_thread
    if not _lastfm.get_api_key(_cfg()):
        return jsonify({"error": "No Last.fm API key set (Setup → Last.fm key)."}), 400
    while not _event_q.empty():
        try: _event_q.get_nowait()
        except: pass
    _bg_thread = threading.Thread(target=lambda: _run_safe(_enrich_run), daemon=True)
    _bg_thread.start()
    return jsonify({"ok": True})


def _run_safe(fn):
    try:
        fn()
    except Exception as e:
        _push(type="error", msg=str(e))


@app.route("/api/workspace", methods=["GET"])
def api_workspace_get():
    return jsonify(_db.get_workspace(_conn))


@app.route("/api/workspace", methods=["POST"])
def api_workspace_set():
    b = request.get_json(force=True) or {}
    slots = b.get("slots", [])
    with _db.get_conn() as c:
        _db.set_workspace(c, slots)
    return jsonify({"ok": True})


@app.route("/api/playlists")
def api_playlists():
    rows = _conn.execute("""
        SELECT p.*, COUNT(pt.track_id) as actual_count
        FROM playlists p
        LEFT JOIN playlist_tracks pt ON pt.playlist_id=p.id
        WHERE p.deleted=0
        GROUP BY p.id
        ORDER BY p.is_liked_songs DESC, p.name
    """).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/playlist/create", methods=["POST"])
def api_create_playlist():
    b = request.get_json(force=True)
    name = b.get("name","").strip()
    desc = b.get("description","").strip()
    track_ids = b.get("track_ids", [])
    if not name:
        return jsonify({"error": "Name required"}), 400

    local_id = f"__local__{uuid.uuid4().hex[:8]}"
    with _db.get_conn() as c:
        c.execute("INSERT INTO playlists (id,name,description,local_only) VALUES (?,?,?,1)",
                  (local_id, name, desc))
        for pos, tid in enumerate(track_ids):
            c.execute("INSERT OR IGNORE INTO playlist_tracks (playlist_id,track_id,position) VALUES (?,?,?)",
                      (local_id, tid, pos))
        _db.log_change(c, "create_playlist", {"id": local_id, "name": name, "description": desc})
        if track_ids:
            uris = [r[0] for r in c.execute(
                "SELECT uri FROM tracks WHERE id IN ({})".format(",".join("?"*len(track_ids))),
                track_ids
            ).fetchall()]
            for uri, tid in zip(uris, track_ids):
                _db.log_change(c, "add_track", {
                    "playlist_id": local_id, "track_id": tid, "uri": uri
                })
    return jsonify({"ok": True, "id": local_id})


@app.route("/api/playlist/<pl_id>/add", methods=["POST"])
def api_playlist_add(pl_id):
    b = request.get_json(force=True)
    track_ids = b.get("track_ids", [])
    if not track_ids:
        return jsonify({"error": "No tracks"}), 400

    with _db.get_conn() as c:
        for tid in track_ids:
            row = c.execute("SELECT uri FROM tracks WHERE id=?", (tid,)).fetchone()
            if not row: continue
            uri = row[0]
            existing = c.execute("SELECT 1 FROM playlist_tracks WHERE playlist_id=? AND track_id=?",
                                 (pl_id, tid)).fetchone()
            if not existing:
                pos = (c.execute("SELECT MAX(position) FROM playlist_tracks WHERE playlist_id=?",
                                 (pl_id,)).fetchone()[0] or 0) + 1
                c.execute("INSERT INTO playlist_tracks (playlist_id,track_id,position) VALUES (?,?,?)",
                          (pl_id, tid, pos))
                _db.log_change(c, "add_track", {"playlist_id": pl_id, "track_id": tid, "uri": uri})
    return jsonify({"ok": True})


@app.route("/api/playlist/<pl_id>/remove", methods=["POST"])
def api_playlist_remove(pl_id):
    b = request.get_json(force=True)
    track_ids = b.get("track_ids", [])
    with _db.get_conn() as c:
        for tid in track_ids:
            row = c.execute("SELECT uri FROM tracks WHERE id=?", (tid,)).fetchone()
            uri = row[0] if row else ""
            c.execute("DELETE FROM playlist_tracks WHERE playlist_id=? AND track_id=?", (pl_id, tid))
            _db.log_change(c, "remove_track", {"playlist_id": pl_id, "track_id": tid, "uri": uri})
    return jsonify({"ok": True})


# ── changes ────────────────────────────────────────────────────────────────────

@app.route("/api/changes")
def api_changes():
    rows = _db.get_pending_changes(_conn)
    return jsonify(rows)


@app.route("/api/undo", methods=["POST"])
def api_undo():
    with _db.get_conn() as c:
        change = _db.undo_last_change(c)
    return jsonify({"ok": True, "undone": change})


@app.route("/api/push", methods=["POST"])
def api_push():
    global _bg_thread, _stop
    b = request.get_json(force=True) or {}
    label = b.get("account", "new")
    sp = _sp.get(label)
    if not sp:
        return jsonify({"error": "Not authenticated"}), 400

    while not _event_q.empty():
        try: _event_q.get_nowait()
        except: pass

    _stop = threading.Event()

    def run():
        try:
            push_changes(sp, emit=_push)
        except Exception as e:
            _push(type="error", msg=str(e))

    _bg_thread = threading.Thread(target=run, daemon=True)
    _bg_thread.start()
    return jsonify({"ok": True})


# ── mood map ───────────────────────────────────────────────────────────────────

@app.route("/api/mood-map")
def api_mood_map():
    playlist_id = request.args.get("playlist", "")
    where = "WHERE t.features_fetched=1"
    params = []
    if playlist_id:
        where += " AND t.id IN (SELECT track_id FROM playlist_tracks WHERE playlist_id=?)"
        params.append(playlist_id)
    rows = _conn.execute(f"""
        SELECT t.id, t.name, t.artists, t.album_art, t.energy, t.valence,
               t.danceability, t.tempo, t.mood
        FROM tracks t {where}
        LIMIT 500
    """, params).fetchall()
    return jsonify([dict(r) for r in rows])


# ── duplicates ─────────────────────────────────────────────────────────────────

@app.route("/api/duplicates")
def api_duplicates():
    rows = _conn.execute("""
        SELECT t.id, t.name, t.artists, t.album_art, t.uri,
               GROUP_CONCAT(pt.playlist_id) as playlist_ids,
               COUNT(DISTINCT pt.playlist_id) as count
        FROM tracks t
        JOIN playlist_tracks pt ON pt.track_id=t.id
        GROUP BY t.id
        HAVING count > 1
        ORDER BY count DESC
        LIMIT 200
    """).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["artists"] = json.loads(d.get("artists") or "[]")
        d["playlist_ids"] = d.get("playlist_ids","").split(",")
        result.append(d)
    return jsonify(result)


# ── SSE stream ─────────────────────────────────────────────────────────────────

@app.route("/api/stream")
def api_stream():
    def generate():
        yield f"data: {json.dumps({'type':'connected'})}\n\n"
        while True:
            try:
                ev = _event_q.get(timeout=25)
                yield f"data: {json.dumps(ev)}\n\n"
                if ev.get("type") in ("fetch_done", "push_done", "enrich_done", "error"):
                    break
            except queue.Empty:
                yield ": keep-alive\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


if __name__ == "__main__":
    print("Spotify Library Manager v2 — http://127.0.0.1:5174")
    app.run(host="127.0.0.1", port=5174, debug=False, threaded=True)
