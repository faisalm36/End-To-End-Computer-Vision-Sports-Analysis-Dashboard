import { useEffect, useState } from 'react';
import { getMetricDefs } from './api';
import { FALLBACK_AVAILABILITY } from './metrics';

// GET /api/metrics (public) -> [{key, label, unit, availability: 'ready'|'soon', is_estimate, ...}].
// Loaded once per page load and shared. Until it answers (or if it fails / is missing on
// an older backend) availability comes from FALLBACK_AVAILABILITY in lib/metrics.js.
let cache = null; // { byKey, source }
let inflight = null;

// Tests reset the module cache between cases.
export function resetMetricDefsCache() {
  cache = null;
  inflight = null;
}

function load() {
  if (cache) return Promise.resolve(cache);
  if (!inflight) {
    inflight = getMetricDefs()
      .then((list) => {
        const byKey = {};
        for (const d of list) if (d && typeof d.key === 'string') byKey[d.key] = d;
        cache = Object.keys(byKey).length ? { byKey, source: 'server' } : { byKey: {}, source: 'fallback' };
        return cache;
      })
      .catch(() => {
        inflight = null; // retry on a later mount
        return { byKey: {}, source: 'fallback' };
      });
  }
  return inflight;
}

export function makeAvailability(byKey = {}) {
  return (key) => {
    const a = String(byKey[key]?.availability ?? '').toLowerCase();
    if (a === 'ready' || a === 'soon') return a;
    return FALLBACK_AVAILABILITY[key] ?? null;
  };
}

// { availability(key) -> 'ready'|'soon'|null, defs, source: 'server'|'fallback'|'loading' }
// Decimal places from the registry (`decimals`), else the caller's fallback.
export function makeDigits(byKey = {}) {
  return (key, fallback = 1) => {
    const d = byKey[key]?.decimals;
    return Number.isInteger(d) && d >= 0 && d <= 4 ? d : fallback;
  };
}

// "Estimated from video" badge: the registry's is_estimate, default true for physical stats.
export function makeEstimate(byKey = {}) {
  return (key) => (typeof byKey[key]?.is_estimate === 'boolean' ? byKey[key].is_estimate : true);
}

export function useMetricDefs({ enabled = true } = {}) {
  const [state, setState] = useState(() => cache ?? { byKey: {}, source: enabled ? 'loading' : 'fallback' });
  useEffect(() => {
    if (!enabled || cache) return undefined;
    let alive = true;
    load().then((c) => alive && setState(c));
    return () => {
      alive = false;
    };
  }, [enabled]);
  return {
    availability: makeAvailability(state.byKey),
    digits: makeDigits(state.byKey),
    isEstimate: makeEstimate(state.byKey),
    defs: state.byKey,
    source: state.source,
  };
}
