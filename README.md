# Spotify Library Migrator

Transfers your complete Spotify library from an **OLD** account to a **NEW** (Premium) account via a desktop GUI:

| Category | What happens |
|---|---|
| Liked Songs | Copied oldest-first to preserve rough order |
| My Playlists | Created on new account; if a same-name playlist exists, only missing tracks are added |
| Followed Playlists | Followed on new account (not duplicated) |
| Followed Artists | Followed on new account |
| Saved Albums | Saved on new account |
| Saved Shows (Podcasts) | Saved on new account |
| Saved Episodes | Saved on new account |

**All transfers are safe**: duplicates are detected and skipped. If the app crashes mid-run, re-launching resumes from where it left off.

---

## One-time Spotify setup

1. Log into the **NEW (Premium) account**, go to <https://developer.spotify.com/dashboard>, click **Create app**.
   - App name: anything (e.g. `library-merge`)
   - Which API/SDKs: **Web API**
   - Redirect URI: `http://127.0.0.1:8888/callback` ← exactly this
2. Open the app → **Settings** → copy **Client ID** and **Client Secret**.
3. In **Settings → User Management**, add **both** account emails to the allowlist.

---

## Install & run

```bash
pip install -r requirements.txt
python gui.py
```

### How to use

1. **Setup tab** — paste Client ID and Client Secret, click *Save Credentials*.
2. Click **Connect OLD Account** — a browser opens, log in as the OLD account.
3. Click **Connect NEW Account** — browser opens again, log in as the NEW account.
   > If the browser reuses the old session, log out of Spotify in the browser (or use Incognito), then retry.
4. Click **Continue to Migrate →**.
5. **Migrate tab** — tick the categories you want, optionally enable *Dry Run* to preview without writing.
6. Click **Start Migration**. Watch per-category progress bars and live log output.
7. If anything goes wrong the state is saved automatically. Re-run to resume.

---

## Files

| File | Purpose |
|---|---|
| `gui.py` | Desktop GUI — main entry point |
| `core.py` | Migration logic (no UI dependency) |
| `state.py` | Crash-safe checkpoint state |
| `config.py` | Credential persistence |
| `config.json` | Your Client ID / Secret (auto-created, keep private) |
| `.cache-old` / `.cache-new` | OAuth token cache (auto-created) |
| `.migration_state.json` | Resume checkpoint (auto-created, delete to start fresh) |

---

## Limits & notes

- Exact "date added" timestamps for Liked Songs cannot be recreated; ordering is approximately preserved.
- Local files in playlists are skipped (they aren't Spotify catalog tracks).
- Cannot transfer: listening history, Wrapped stats, Made For You playlists, collaborative playlist edits.
- Dev-mode apps allow up to 25 users on the allowlist — sufficient for this use case.
