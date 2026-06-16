import { useState } from 'react';
import { getDB, Track, saveTracks } from '@/lib/db';

export function useSyncManager() {
  const [isSyncing, setIsSyncing] = useState(false);
  const [progress, setProgress] = useState({ current: 0, total: 0 });

  const syncLikedSongs = async (account: "old" | "new") => {
    setIsSyncing(true);
    let offset = 0;
    const limit = 50;
    let total = 1; // will be updated on first request

    try {
      while (offset < total) {
        const res = await fetch(`/api/proxy/${account}/me/tracks?limit=${limit}&offset=${offset}`);
        if (!res.ok) throw new Error("Failed to fetch tracks");
        
        const data = await res.json();
        total = data.total;
        
        const tracks: Track[] = data.items.map((item: any) => ({
          id: item.track.id,
          name: item.track.name,
          artists: item.track.artists.map((a: any) => a.name),
          album: item.track.album.name,
          album_art: item.track.album.images[0]?.url || "",
          duration_ms: item.track.duration_ms,
          uri: item.track.uri,
          release_year: parseInt(item.track.album.release_date?.substring(0,4)) || 0,
          popularity: item.track.popularity,
          explicit: item.track.explicit,
          // defaults for audio features
          energy: 0, valence: 0, danceability: 0, tempo: 0, acousticness: 0,
          mood: "Unknown", language: "Unknown", genre_group: "Unknown", features_fetched: false
        }));

        await saveTracks(tracks);
        
        offset += limit;
        setProgress({ current: Math.min(offset, total), total });
      }
    } catch (err) {
      console.error(err);
    } finally {
      setIsSyncing(false);
    }
  };

  return { isSyncing, progress, syncLikedSongs };
}
