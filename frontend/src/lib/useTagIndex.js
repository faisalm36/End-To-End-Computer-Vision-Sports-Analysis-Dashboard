import { useEffect, useState } from 'react';
import { getTags, isUnsupported, listVideos } from './api';
import { SAMPLE_VIDEOS } from './sampleData';
import { indexFromVideos, normalizeTagIndex } from './tags';

// The user's past tags for autocomplete: GET /api/tags, or (if that endpoint
// doesn't exist yet) derived from GET /api/videos. Never throws.
export function useTagIndex({ isDemo = false, videos = null } = {}) {
  const [index, setIndex] = useState(() => (isDemo ? indexFromVideos(SAMPLE_VIDEOS) : videos ? indexFromVideos(videos) : []));
  useEffect(() => {
    if (isDemo) return undefined;
    const controller = new AbortController();
    const { signal } = controller;
    getTags({ signal })
      .then((raw) => setIndex(normalizeTagIndex(raw)))
      .catch(async (err) => {
        if (signal.aborted || err?.kind === 'abort') return;
        if (!isUnsupported(err)) return;
        try {
          const list = videos ?? (await listVideos({ signal }));
          if (!signal.aborted) setIndex(indexFromVideos(list));
        } catch {
          /* no suggestions beyond presets */
        }
      });
    return () => controller.abort();
  }, [isDemo, videos]);
  return index;
}
