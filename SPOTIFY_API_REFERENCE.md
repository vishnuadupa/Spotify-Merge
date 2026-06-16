# Spotify Web API Quick Reference
**Full schema:** `spotify-api-schema.yaml` (283 KB)

## Authentication
- **OAuth 2.0** via `https://accounts.spotify.com/authorize`
- Base URI: `https://api.spotify.com/v1`
- Required scopes for our work:
  - `user-library-modify` (remove from liked songs)
  - `playlist-modify-private` (modify playlists)
  - `playlist-modify-public` (modify playlists)

## Endpoints for Deduplication

### Get Liked Songs
```
GET /me/tracks
  ?limit=50&offset=0
  Returns: paginated list of user's liked tracks (max 50 per page)
  Response: { items: [{track: {...}}, ...], total, next, ... }
```

### Remove from Liked Songs
```
DELETE /me/tracks
  Body: { ids: ["track_id_1", "track_id_2", ...] }  (max 50 per request)
  Returns: 204 No Content on success
```

### Get Playlist Tracks
```
GET /playlists/{playlist_id}/items
  ?limit=50&offset=0
  Returns: paginated list of playlist tracks
```

### Remove from Playlist
```
DELETE /playlists/{playlist_id}/tracks
  Body: { tracks: [{uri: "spotify:track:..."}, ...] }  (max 100 per request)
  Returns: { snapshot_id: "..." }
  Note: snapshot_id changes after each modification (use for undo/verification)
```

### Add to Playlist
```
POST /playlists/{playlist_id}/tracks
  Body: { uris: ["spotify:track:...", ...] }  (max 100 per request)
  Returns: { snapshot_id: "..." }
```

## Rate Limiting
- **Rollng 30-second window**, no published cap (community: ~180 req/30s in dev)
- 429 response includes `Retry-After` header (seconds to wait)
- Our app uses: `_throttle()` proactive limiter (~3.3 req/s) + `_retry()` exponential backoff

## Deprecated Endpoints (403 for new apps)
- `/v1/audio-features` - killed 2024-11-27
- `/v1/audio-analysis` - killed 2024-11-27
- `/recommendations` - killed 2024-11-27

## IDs vs URIs
- **Track ID**: `5QDLhrAOJJdNAmCTJ8xMyW` (short form, used internally)
- **Track URI**: `spotify:track:5QDLhrAOJJdNAmCTJ8xMyW` (full form, used in API requests)
- **Track URL**: `https://open.spotify.com/track/5QDLhrAOJJdNAmCTJ8xMyW` (web link)
