import { openDB, DBSchema, IDBPDatabase } from 'idb';

export interface Track {
  id: string;
  name: string;
  artists: string[];
  album: string;
  album_art: string;
  duration_ms: number;
  uri: string;
  release_year: number;
  popularity: number;
  explicit: boolean;
  // Audio features
  energy: number;
  valence: number;
  danceability: number;
  tempo: number;
  acousticness: number;
  mood: string;
  language: string;
  genre_group: string;
  features_fetched: boolean;
}

export interface Playlist {
  id: string;
  name: string;
  description: string;
  is_liked_songs: boolean;
  image_url: string;
  owner_id: string;
  track_count: number;
  account: "old" | "new";
}

export interface PlaylistTrack {
  playlist_id: string;
  track_id: string;
  position: number;
  added_at: string;
}

interface LibraryDB extends DBSchema {
  tracks: {
    key: string;
    value: Track;
    indexes: { 'by-mood': string, 'by-language': string };
  };
  playlists: {
    key: string;
    value: Playlist;
    indexes: { 'by-account': string };
  };
  playlist_tracks: {
    key: string; // composite `${playlist_id}::${track_id}`
    value: PlaylistTrack;
    indexes: { 'by-playlist': string, 'by-track': string };
  };
  sync_state: {
    key: string;
    value: { account: "old" | "new", entity: string, last_synced: number, total: number, offset: number };
  }
}

let dbPromise: Promise<IDBPDatabase<LibraryDB>> | null = null;

export function getDB() {
  if (typeof window === 'undefined') return null; // Only run in browser
  
  if (!dbPromise) {
    dbPromise = openDB<LibraryDB>('spotify-library', 1, {
      upgrade(db) {
        const trackStore = db.createObjectStore('tracks', { keyPath: 'id' });
        trackStore.createIndex('by-mood', 'mood');
        trackStore.createIndex('by-language', 'language');

        const playlistStore = db.createObjectStore('playlists', { keyPath: 'id' });
        playlistStore.createIndex('by-account', 'account');

        const ptStore = db.createObjectStore('playlist_tracks', { keyPath: 'key' });
        ptStore.createIndex('by-playlist', 'playlist_id');
        ptStore.createIndex('by-track', 'track_id');

        db.createObjectStore('sync_state', { keyPath: 'key' });
      },
    });
  }
  return dbPromise;
}

export async function saveTracks(tracks: Track[]) {
  const db = await getDB();
  if (!db) return;
  const tx = db.transaction('tracks', 'readwrite');
  await Promise.all([
    ...tracks.map(t => tx.store.put(t)),
    tx.done
  ]);
}

export async function savePlaylists(playlists: Playlist[]) {
  const db = await getDB();
  if (!db) return;
  const tx = db.transaction('playlists', 'readwrite');
  await Promise.all([
    ...playlists.map(p => tx.store.put(p)),
    tx.done
  ]);
}
