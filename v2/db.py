"""
db.py — SQLite local library store for v2.

All Spotify data is cached here. Edits are staged as pending_changes.
Nothing touches Spotify until the user explicitly pushes.
"""

import json
import os
import sqlite3
import time
import unicodedata

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "library.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tracks (
    id              TEXT PRIMARY KEY,
    name            TEXT,
    artists         TEXT,   -- JSON ["Artist1", ...]
    artist_ids      TEXT,   -- JSON ["id1", ...]
    album           TEXT,
    album_art       TEXT,   -- URL
    duration_ms     INTEGER,
    uri             TEXT,
    release_year    INTEGER,
    popularity      INTEGER,
    explicit        INTEGER,
    -- audio features (all 0.0 until fetched)
    energy          REAL DEFAULT 0,
    valence         REAL DEFAULT 0,
    danceability    REAL DEFAULT 0,
    tempo           REAL DEFAULT 0,
    acousticness    REAL DEFAULT 0,
    speechiness     REAL DEFAULT 0,
    loudness        REAL DEFAULT 0,
    instrumentalness REAL DEFAULT 0,
    -- computed
    mood            TEXT DEFAULT '',
    language        TEXT DEFAULT '',
    genres          TEXT DEFAULT '[]',
    genre_group     TEXT DEFAULT '',
    features_fetched INTEGER DEFAULT 0,
    fetched_at      INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS playlists (
    id              TEXT PRIMARY KEY,
    name            TEXT,
    description     TEXT DEFAULT '',
    is_liked_songs  INTEGER DEFAULT 0,
    image_url       TEXT DEFAULT '',
    owner_id        TEXT DEFAULT '',
    track_count     INTEGER DEFAULT 0,
    local_only      INTEGER DEFAULT 0,   -- 1 = created in app, not yet on Spotify
    followed        INTEGER DEFAULT 0,   -- 1 = followed (read-only source, not owned)
    deleted         INTEGER DEFAULT 0
);

-- Kanban workspace: which playlist sits in which on-screen slot.
-- Survives restarts so the user picks up exactly where they left off.
CREATE TABLE IF NOT EXISTS workspace (
    slot_index      INTEGER PRIMARY KEY,
    playlist_id     TEXT
);

CREATE TABLE IF NOT EXISTS playlist_tracks (
    playlist_id     TEXT,
    track_id        TEXT,
    position        INTEGER,
    added_at        TEXT DEFAULT '',
    PRIMARY KEY (playlist_id, track_id)
);

CREATE TABLE IF NOT EXISTS top_tracks (
    track_id        TEXT,
    time_range      TEXT,
    rank            INTEGER,
    PRIMARY KEY (track_id, time_range)
);

CREATE TABLE IF NOT EXISTS pending_changes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    type            TEXT,   -- add_track | remove_track | add_liked | remove_liked | create_playlist
    payload         TEXT,   -- JSON
    created_at      INTEGER
);
"""


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    with get_conn() as c:
        c.executescript(_SCHEMA)
        # lightweight migration: add columns to pre-existing tables
        cols = [r[1] for r in c.execute("PRAGMA table_info(tracks)").fetchall()]
        if "genre_group" not in cols:
            c.execute("ALTER TABLE tracks ADD COLUMN genre_group TEXT DEFAULT ''")
        pcols = [r[1] for r in c.execute("PRAGMA table_info(playlists)").fetchall()]
        if "followed" not in pcols:
            c.execute("ALTER TABLE playlists ADD COLUMN followed INTEGER DEFAULT 0")


# ── genre rollup: Spotify's micro-genres → ~15 top-level buckets ─────────────
# Order matters: more specific buckets first (K-Pop before Pop, Desi before generic).
GENRE_BUCKETS = [
    ("K-Pop",          ["k-pop", "korean", "k-rap", "k-rock"]),
    ("Bollywood/Desi", ["bollywood", "desi", "filmi", "hindi", "punjabi", "bhangra",
                         "tamil", "telugu", "kannada", "malayalam", "indian"]),
    ("Afro",           ["afro", "amapiano", "afrobeat", "afropop"]),
    ("Latin",          ["latin", "reggaeton", "salsa", "bachata", "cumbia", "tango", "bossa"]),
    ("Hip-Hop/Rap",    ["hip hop", "rap", "trap", "drill", "grime"]),
    ("R&B/Soul",       ["r&b", "rnb", "soul", "funk", "motown", "neo soul"]),
    ("Electronic/EDM", ["edm", "house", "techno", "trance", "dubstep", "electro",
                         "drum and bass", "dnb", "garage", "synthwave"]),
    ("Metal",          ["metal", "metalcore", "deathcore"]),
    ("Rock",           ["rock", "punk", "grunge", "emo", "hardcore"]),
    ("Indie/Alt",      ["indie", "alt ", "alternative"]),
    ("Country/Folk",   ["country", "folk", "americana", "bluegrass"]),
    ("Jazz/Blues",     ["jazz", "blues", "swing"]),
    ("Classical",      ["classical", "orchestra", "piano", "baroque", "opera", "soundtrack", "score"]),
    ("Lo-fi/Chill",    ["lo-fi", "lofi", "chill", "ambient"]),
    ("Pop",            ["pop"]),
]


def rollup_genre(genres: list) -> str:
    """Map a track's micro-genre list to one top-level bucket."""
    if not genres:
        return ""
    text = " ".join(genres).lower()
    for bucket, keys in GENRE_BUCKETS:
        if any(k in text for k in keys):
            return bucket
    return "Other"


def get_genres(conn, language="") -> list:
    """Top-level genre buckets with counts, optionally scoped to a language."""
    if language:
        rows = conn.execute(
            "SELECT genre_group, COUNT(*) c FROM tracks WHERE genre_group!='' AND language=? "
            "GROUP BY genre_group ORDER BY c DESC", (language,)).fetchall()
    else:
        rows = conn.execute(
            "SELECT genre_group, COUNT(*) c FROM tracks WHERE genre_group!='' "
            "GROUP BY genre_group ORDER BY c DESC").fetchall()
    return [{"genre": r[0], "count": r[1]} for r in rows]


# ── language detection (no external lib) ──────────────────────────────────────

def detect_language(text: str) -> str:
    for ch in text:
        cp = ord(ch)
        if 0x0900 <= cp <= 0x097F: return "Hindi"
        if 0xAC00 <= cp <= 0xD7AF: return "Korean"
        if 0x4E00 <= cp <= 0x9FFF: return "Chinese/Japanese"
        if 0x0400 <= cp <= 0x04FF: return "Russian"
        if 0x0600 <= cp <= 0x06FF: return "Arabic"
        if 0x0E00 <= cp <= 0x0E7F: return "Thai"
        if 0x0980 <= cp <= 0x09FF: return "Bengali"
        if 0x0A80 <= cp <= 0x0AFF: return "Gujarati"
        if 0x0B80 <= cp <= 0x0BFF: return "Tamil"
        if 0x0C00 <= cp <= 0x0C7F: return "Telugu"
        if 0x0C80 <= cp <= 0x0CFF: return "Kannada"
        if 0x0D00 <= cp <= 0x0D7F: return "Malayalam"
        if 0x0A00 <= cp <= 0x0A7F: return "Punjabi"
        if 0x3040 <= cp <= 0x30FF: return "Japanese"
    return "English"


# Romanized titles (Latin script) can't be told apart by script alone — "Kesariya",
# "Despacito", "Dynamite" all look English. Fall back to the artist's genre tags.
_GENRE_LANG = [
    ("Punjabi",    ["punjabi", "bhangra"]),
    ("Hindi",      ["bollywood", "filmi", "hindi", "desi", "haryanvi"]),
    ("Tamil",      ["tamil", "kollywood"]),
    ("Telugu",     ["telugu", "tollywood"]),
    ("Kannada",    ["kannada", "sandalwood"]),
    ("Malayalam",  ["malayalam", "mollywood"]),
    ("Korean",     ["k-pop", "korean", "k-rap", "k-rock", "k-indie", "k-ballad"]),
    ("Japanese",   ["j-pop", "japanese", "j-rock", "anime", "vocaloid", "city pop"]),
    ("Spanish",    ["reggaeton", "latin", "spanish", "salsa", "bachata", "cumbia",
                    "regional mexican", "corrido", "musica mexicana", "flamenco", "tejano"]),
    ("Portuguese", ["brazilian", "sertanejo", "funk carioca", "mpb", "bossa nova", "pagode", "forro"]),
    ("French",     ["french", "chanson", "variété", "rap francais"]),
    ("German",     ["german", "schlager", "deutschrap"]),
    ("Arabic",     ["arabic", "arab", "khaleeji", "raï"]),
    ("Turkish",    ["turkish", "turkce", "anatolian"]),
    ("Italian",    ["italian", "italiano"]),
    ("African",    ["afrobeats", "amapiano", "afropop", "naija", "highlife", "afro"]),
]


def infer_language_from_genres(genres: list) -> str:
    """Best-guess language from artist genre tags. Returns '' if no signal."""
    if not genres:
        return ""
    text = " ".join(genres).lower()
    for lang, keys in _GENRE_LANG:
        if any(k in text for k in keys):
            return lang
    return ""


# Explicit language words that regional releases embed in titles/albums:
# "Naatu Naatu - Telugu", "Why This Kolaveri Di (Tamil)", "... (Hindi Version)".
_TITLE_LANG_HINTS = [
    ("Telugu",["telugu"]), ("Tamil",["tamil"]), ("Hindi",["hindi","bhojpuri"]),
    ("Punjabi",["punjabi"]), ("Malayalam",["malayalam"]), ("Kannada",["kannada"]),
    ("Marathi",["marathi"]), ("Bengali",["bengali"]), ("Gujarati",["gujarati"]),
    ("Korean",["korean"]), ("Japanese",["japanese"]), ("Spanish",["spanish","español"]),
    ("Arabic",["arabic"]), ("French",["français","francais"]), ("Portuguese",["portuguese","português"]),
]


def resolve_language(name: str, genres: list, artists_text: str = "", album: str = "") -> str:
    """Best-effort with NO genre/audio data (Spotify 403s those for dev apps):
       1) native script in title or artist name (reliable)
       2) explicit language word in title/album text
       3) genre signal if any genres exist (rare now)
       4) default English."""
    # 1. script on title, then artist names
    lang = detect_language(name)
    if lang != "English":
        return lang
    if artists_text:
        a = detect_language(artists_text)
        if a != "English":
            return a
    # 2. explicit language keyword in title/album
    text = (name + " " + album).lower()
    for lng, keys in _TITLE_LANG_HINTS:
        if any(k in text for k in keys):
            return lng
    # 3. tag/genre signal (from Last.fm enrichment)
    g = infer_language_from_genres(genres)
    if g:
        return g
    # 4. Latin script WITH tag evidence but no regional signal → Western/English.
    if genres:
        return "English"
    # 5. No script, no keyword, no tags → we genuinely don't know. Never guess English.
    return "Unknown"


def recategorize_all(conn) -> dict:
    """Re-derive language + genre_group for every track from already-stored data.
    No Spotify calls — fixes mis-grouped romanized songs after a fetch."""
    import json as _json
    rows = conn.execute("SELECT id, name, artists, album, genres FROM tracks").fetchall()
    changed = 0
    with conn:
        for tid, name, aj, album, gj in rows:
            try:
                genres = _json.loads(gj or "[]")
            except Exception:
                genres = []
            try:
                artists_text = " ".join(_json.loads(aj or "[]"))
            except Exception:
                artists_text = ""
            lang = resolve_language(name or "", genres, artists_text, album or "")
            conn.execute("UPDATE tracks SET language=?, genre_group=? WHERE id=?",
                         (lang, rollup_genre(genres), tid))
            changed += 1
    return {"updated": changed}


# ── mood classification ────────────────────────────────────────────────────────

def classify_mood(energy, valence, danceability, acousticness, instrumentalness, tempo) -> str:
    if not energy and not valence:
        return "Unknown"
    if instrumentalness > 0.6:
        return "Focus"
    if energy > 0.75 and valence < 0.35:
        return "Angry"
    if energy > 0.7 and danceability > 0.65:
        return "Dance"
    if valence > 0.65 and energy > 0.5:
        return "Happy"
    if valence < 0.35 and energy < 0.55:
        return "Sad"
    if energy < 0.4 and tempo < 110:
        return "Chill"
    if acousticness > 0.55 and valence > 0.4:
        return "Romantic"
    if energy > 0.7:
        return "Energetic"
    return "Neutral"


# ── upsert helpers ─────────────────────────────────────────────────────────────

def upsert_track(conn, t: dict):
    artists = json.dumps([a["name"] for a in t.get("artists", [])])
    artist_ids = json.dumps([a["id"] for a in t.get("artists", [])])
    art = (t.get("album", {}).get("images") or [{}])[0].get("url", "")
    year = 0
    rd = t.get("album", {}).get("release_date", "")
    if rd:
        try: year = int(rd[:4])
        except: pass
    lang = detect_language(t.get("name", ""))
    conn.execute("""
        INSERT INTO tracks (id,name,artists,artist_ids,album,album_art,duration_ms,
            uri,release_year,popularity,explicit,language,fetched_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
            name=excluded.name, artists=excluded.artists, artist_ids=excluded.artist_ids,
            album=excluded.album, album_art=excluded.album_art,
            release_year=excluded.release_year, popularity=excluded.popularity,
            explicit=excluded.explicit, language=excluded.language, fetched_at=excluded.fetched_at
    """, (
        t["id"], t.get("name",""), artists, artist_ids,
        t.get("album", {}).get("name",""), art, t.get("duration_ms", 0),
        t.get("uri",""), year, t.get("popularity", 0),
        1 if t.get("explicit") else 0, lang, int(time.time())
    ))


def upsert_audio_features(conn, f: dict):
    if not f or not f.get("id"):
        return
    mood = classify_mood(
        f.get("energy", 0), f.get("valence", 0),
        f.get("danceability", 0), f.get("acousticness", 0),
        f.get("instrumentalness", 0), f.get("tempo", 0)
    )
    conn.execute("""
        UPDATE tracks SET
            energy=?, valence=?, danceability=?, tempo=?,
            acousticness=?, speechiness=?, loudness=?, instrumentalness=?,
            mood=?, features_fetched=1
        WHERE id=?
    """, (
        f.get("energy", 0), f.get("valence", 0), f.get("danceability", 0), f.get("tempo", 0),
        f.get("acousticness", 0), f.get("speechiness", 0), f.get("loudness", 0),
        f.get("instrumentalness", 0), mood, f["id"]
    ))


def upsert_playlist(conn, pl: dict, is_liked=False, followed=False):
    img = (pl.get("images") or [{}])[0].get("url", "")
    conn.execute("""
        INSERT INTO playlists (id,name,description,is_liked_songs,image_url,owner_id,track_count,followed)
        VALUES (?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
            name=excluded.name, description=excluded.description,
            image_url=excluded.image_url, track_count=excluded.track_count,
            followed=excluded.followed
    """, (
        pl["id"], pl.get("name","Liked Songs" if is_liked else ""),
        pl.get("description",""), 1 if is_liked else 0,
        img, pl.get("owner",{}).get("id",""),
        pl.get("tracks",{}).get("total", 0),
        1 if followed else 0
    ))


def add_playlist_track(conn, playlist_id, track_id, position, added_at=""):
    conn.execute("""
        INSERT OR IGNORE INTO playlist_tracks (playlist_id,track_id,position,added_at)
        VALUES (?,?,?,?)
    """, (playlist_id, track_id, position, added_at))


# ── change log ─────────────────────────────────────────────────────────────────

def log_change(conn, type_: str, payload: dict):
    conn.execute(
        "INSERT INTO pending_changes (type,payload,created_at) VALUES (?,?,?)",
        (type_, json.dumps(payload), int(time.time()))
    )


def get_pending_changes(conn) -> list:
    rows = conn.execute("SELECT * FROM pending_changes ORDER BY id").fetchall()
    return [dict(r) for r in rows]


def clear_change(conn, change_id: int):
    conn.execute("DELETE FROM pending_changes WHERE id=?", (change_id,))


def undo_last_change(conn) -> dict | None:
    row = conn.execute("SELECT * FROM pending_changes ORDER BY id DESC LIMIT 1").fetchone()
    if not row:
        return None
    change = dict(row)
    p = json.loads(change["payload"])
    # reverse the effect locally
    if change["type"] == "add_track":
        conn.execute("DELETE FROM playlist_tracks WHERE playlist_id=? AND track_id=?",
                     (p["playlist_id"], p["track_id"]))
    elif change["type"] == "remove_track":
        conn.execute("INSERT OR IGNORE INTO playlist_tracks (playlist_id,track_id,position) VALUES (?,?,0)",
                     (p["playlist_id"], p["track_id"]))
    elif change["type"] == "create_playlist":
        conn.execute("DELETE FROM playlists WHERE id=?", (p["id"],))
    conn.execute("DELETE FROM pending_changes WHERE id=?", (change["id"],))
    return change


# ── query helpers ──────────────────────────────────────────────────────────────

def get_languages(conn) -> list:
    """Return [{language, count}] ordered by count desc — drives the language tabs."""
    rows = conn.execute("""
        SELECT language, COUNT(*) c FROM tracks
        WHERE language != ''
        GROUP BY language ORDER BY c DESC
    """).fetchall()
    return [{"language": r[0], "count": r[1]} for r in rows]


# ── workspace (Kanban slots) ────────────────────────────────────────────────

def get_workspace(conn) -> list:
    """Return playlist_id per slot index, 0..N. Empty slots -> None."""
    rows = conn.execute("SELECT slot_index, playlist_id FROM workspace ORDER BY slot_index").fetchall()
    return [{"slot": r[0], "playlist_id": r[1]} for r in rows]


def set_workspace(conn, slots: list):
    """Replace the whole workspace. slots = list of playlist_id (or None) by index."""
    conn.execute("DELETE FROM workspace")
    for i, pid in enumerate(slots):
        conn.execute("INSERT INTO workspace (slot_index, playlist_id) VALUES (?,?)", (i, pid))


def get_library_stats(conn) -> dict:
    total = conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
    total_ms = conn.execute("SELECT SUM(duration_ms) FROM tracks").fetchone()[0] or 0
    playlists = conn.execute("SELECT COUNT(*) FROM playlists WHERE deleted=0").fetchone()[0]
    pending = conn.execute("SELECT COUNT(*) FROM pending_changes").fetchone()[0]
    top_mood = conn.execute(
        "SELECT mood, COUNT(*) c FROM tracks WHERE mood!='' GROUP BY mood ORDER BY c DESC LIMIT 1"
    ).fetchone()
    return {
        "total_tracks": total,
        "total_hours": round(total_ms / 3_600_000, 1),
        "total_playlists": playlists,
        "pending_changes": pending,
        "top_mood": top_mood[0] if top_mood else "—",
    }
