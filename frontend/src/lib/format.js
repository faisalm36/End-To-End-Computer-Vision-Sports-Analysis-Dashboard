import { PROCESSING_STAGES } from './api';

export function initials(nameOrEmail) {
  const s = String(nameOrEmail || '?').split('@')[0];
  const parts = s.split(/[\s._-]+/).filter(Boolean);
  if (!parts.length) return '?';
  return (parts.length > 1 ? parts[0][0] + parts[1][0] : parts[0].slice(0, 2)).toUpperCase();
}

export function formatBytes(bytes) {
  if (!Number.isFinite(bytes) || bytes < 0) return '—';
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}

export const toMB = (bytes) => (Number.isFinite(bytes) ? (bytes / 1024 ** 2).toFixed(1) : '0.0');

export function formatDuration(seconds) {
  const s = Number(seconds);
  if (!Number.isFinite(s) || s <= 0) return '—';
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.floor(s % 60);
  const pad = (n) => String(n).padStart(2, '0');
  return h ? `${h}:${pad(m)}:${pad(sec)}` : `${m}:${pad(sec)}`;
}

// Date-only strings (YYYY-MM-DD) are shown as-is in local calendar terms;
// timestamps are shown in the browser's local time zone.
export function formatDate(value, { withTime = false } = {}) {
  if (!value) return '—';
  const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(value);
  const d = dateOnly ? new Date(`${value}T12:00:00`) : new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  const opts = { year: 'numeric', month: 'short', day: 'numeric' };
  if (withTime && !dateOnly) Object.assign(opts, { hour: 'numeric', minute: '2-digit' });
  return d.toLocaleString(undefined, opts);
}

// Teams/date may live on the video or on its nested `match` object.
export const matchOf = (v) => ({
  match_date: v?.match_date ?? v?.match?.match_date ?? null,
  home_team: v?.home_team ?? v?.match?.home_team ?? null,
  away_team: v?.away_team ?? v?.match?.away_team ?? null,
});

export function videoTitle(v) {
  if (v?.title) return v.title;
  const m = matchOf(v);
  if (m.home_team && m.away_team) return `${m.home_team} vs ${m.away_team}`;
  return v?.file_name || v?.filename || `Video ${v?.video_id ?? v?.id ?? ''}`;
}

export const videoId = (v) => v?.id ?? v?.video_id;

export function stageTitle({ phase, stageIdx }) {
  if (phase === 'queued') return 'Queued, waiting to start';
  if (phase === 'complete') return 'Analysis complete';
  if (phase === 'failed') return 'Processing failed';
  return stageIdx >= 0 ? PROCESSING_STAGES[stageIdx].label : 'Processing your match';
}

// /me returns { user_id, name, first_name, last_name, email, role, created_at }.
export function displayName(user, { fallbackToEmail = true } = {}) {
  if (!user) return '';
  const full = user.name || [user.first_name, user.last_name].filter(Boolean).join(' ');
  if (full && full.trim()) return full.trim();
  return fallbackToEmail && user.email ? user.email.split('@')[0] : '';
}
