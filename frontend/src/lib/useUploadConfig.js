import { useEffect, useState } from 'react';
import { FALLBACK_EXTENSIONS, FALLBACK_MAX_UPLOAD_MB, VIDEO_MIME, getConfig } from './api';

// Normalise GET /api/config into upload rules; fall back to env/mp4+mov.
function toRules(cfg, source) {
  const mb = Number(cfg?.max_upload_mb);
  const exts = Array.isArray(cfg?.allowed_extensions)
    ? cfg.allowed_extensions.map((e) => String(e).trim().toLowerCase().replace(/^\./, '')).filter(Boolean)
    : [];
  // Show the common formats first: MP4, MOV, then the rest as sent.
  const order = ['mp4', 'mov', 'avi', 'mkv'];
  const rank = (e) => (order.includes(e) ? order.indexOf(e) : order.length);
  const extensions = (exts.length ? [...new Set(exts)] : FALLBACK_EXTENSIONS).sort((a, b) => rank(a) - rank(b));
  const maxUploadMb = Number.isFinite(mb) && mb > 0 ? mb : FALLBACK_MAX_UPLOAD_MB;
  const upper = extensions.map((e) => e.toUpperCase());
  const typesText = upper.length > 1 ? `${upper.slice(0, -1).join(', ')} or ${upper[upper.length - 1]}` : upper[0];
  const accept = [...extensions.map((e) => `.${e}`), ...extensions.map((e) => VIDEO_MIME[e]).filter(Boolean)].join(',');
  return { extensions, maxUploadMb, typesText, accept, source };
}

const FALLBACK_RULES = toRules(null, 'fallback');
let cache = null; // resolved rules, shared across mounts
let inflight = null;

// Tests reset the shared cache between cases.
export function resetUploadConfigCache() {
  cache = null;
  inflight = null;
}

export function useUploadConfig() {
  const [rules, setRules] = useState(cache || FALLBACK_RULES);
  useEffect(() => {
    if (cache) return undefined;
    let alive = true;
    inflight ||= getConfig()
      .then((cfg) => (cache = toRules(cfg, 'server')))
      .catch(() => {
        inflight = null; // retry on next mount
        return FALLBACK_RULES;
      });
    inflight.then((r) => alive && setRules(r));
    return () => {
      alive = false;
    };
  }, []);
  return rules;
}
