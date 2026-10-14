// Match tags: key/value pairs such as Weather: Raining.
// Keys and values are compared case-insensitively ("Turf" == "turf") and shown
// in a normalised display casing so the data never splits on capitalisation.

// Union of the UI/UX Designer's presets and the product brief's presets.
export const PRESET_TAG_KEYS = [
  { key: 'Weather', icon: 'cloud', values: ['Sunny', 'Cloudy', 'Raining', 'Windy', 'Hot', 'Cold', 'Snow'] },
  { key: 'Pitch', icon: 'grass', values: ['Grass', 'Turf', '3G', 'Indoor', 'Wet', 'Muddy', 'Hard'] },
  { key: 'Home/Away', icon: 'home', values: ['Home', 'Away', 'Neutral'] },
  { key: 'Opponent', icon: 'shield', values: [] },
  { key: 'Opponent strength', icon: 'shield', values: ['Weaker', 'Similar', 'Stronger'] },
  { key: 'Competition', icon: 'trophy', values: ['League', 'Cup', 'Friendly', 'Tournament'] },
  { key: 'Attendance', icon: 'users', values: ['No fans', 'Few fans', 'Busy', 'Packed'] },
  { key: 'Kickoff time', icon: 'clock', values: ['Morning', 'Afternoon', 'Evening', 'Night'] },
];

// Keys shown as quick-add chips under the tag input.
export const QUICK_ADD_KEYS = ['Weather', 'Pitch', 'Home/Away', 'Opponent strength', 'Attendance', 'Kickoff time'];

export const MAX_TAG_LEN = 40;

export const norm = (s) => String(s ?? '').trim().replace(/\s+/g, ' ').toLowerCase();

// Display casing: known presets keep their spelling; otherwise capitalise the
// first letter of each word but leave inner casing ("3G", "U16") alone.
export function displayCase(s, known = []) {
  const clean = String(s ?? '').trim().replace(/\s+/g, ' ');
  const hit = known.find((k) => norm(k) === norm(clean));
  if (hit) return hit;
  return clean.replace(/(^|[\s/-])(\p{Ll})/gu, (_, sep, ch) => sep + ch.toUpperCase());
}

const presetFor = (key) => PRESET_TAG_KEYS.find((p) => norm(p.key) === norm(key));

export function cleanTag({ key, value }, index = []) {
  const knownKeys = [...PRESET_TAG_KEYS.map((p) => p.key), ...index.map((g) => g.key)];
  const k = displayCase(key, knownKeys).slice(0, MAX_TAG_LEN);
  const knownValues = [...(presetFor(k)?.values || []), ...(index.find((g) => norm(g.key) === norm(k))?.values || []).map((v) => v.value)];
  const v = displayCase(value, knownValues).slice(0, MAX_TAG_LEN);
  return { key: k, value: v };
}

// Every tag on a video/match object (tags:[{key,value}], the match's tags). The backend
// allows several values per key; filters and counts use all of them.
export function allTagsOf(video) {
  const raw = video?.tags;
  let list = [];
  if (Array.isArray(raw)) list = raw.filter((t) => t && t.key && t.value != null);
  else if (raw && typeof raw === 'object') list = Object.entries(raw).map(([key, value]) => ({ key, value }));
  const seen = new Map();
  for (const t of list) {
    const key = storedCase(t.key, PRESET_TAG_KEYS.map((p) => p.key));
    seen.set(`${norm(t.key)}\u0000${norm(t.value)}`, { key, value: storedCase(t.value, presetFor(key)?.values || []) });
  }
  return [...seen.values()];
}

// Server spelling wins (the backend keeps the first-seen casing, e.g. "Kickoff time");
// presets keep theirs, and only all-lowercase legacy values get capitalised.
function storedCase(s, known) {
  const clean = String(s ?? '').trim().replace(/\s+/g, ' ');
  const hit = known.find((k) => norm(k) === norm(clean));
  if (hit) return hit;
  return /\p{Lu}|\d/u.test(clean) ? clean : displayCase(clean);
}

// Tags for display/editing: one value per key (the UI's rule; the last one wins).
export function tagsOf(video) {
  const list = allTagsOf(video);
  const seen = new Map();
  for (const t of list) seen.set(norm(t.key), t);
  return [...seen.values()];
}

// One value per key: adding an existing key replaces its value.
// Returns { tags, replaced } where replaced is the old tag (or null).
export function upsertTag(tags, tag) {
  const i = tags.findIndex((t) => norm(t.key) === norm(tag.key));
  if (i < 0) return { tags: [...tags, tag], replaced: null };
  const next = [...tags];
  const replaced = next[i];
  next[i] = tag;
  return { tags: next, replaced: norm(replaced.value) === norm(tag.value) ? null : replaced };
}

export const removeTag = (tags, key) => tags.filter((t) => norm(t.key) !== norm(key));

export const tagId = (t) => `${norm(t.key)}=${norm(t.value)}`;

// Build the [{key, values:[{value,count}]}] index from a list of videos
// (used when GET /api/tags is unavailable).
export function indexFromVideos(videos) {
  const keys = new Map();
  for (const v of videos) {
    for (const t of allTagsOf(v)) {
      const k = norm(t.key);
      if (!keys.has(k)) keys.set(k, { key: t.key, values: new Map() });
      const vals = keys.get(k).values;
      const vk = norm(t.value);
      vals.set(vk, { value: vals.get(vk)?.value ?? t.value, count: (vals.get(vk)?.count ?? 0) + 1 });
    }
  }
  return [...keys.values()]
    .map((g) => ({ key: g.key, values: [...g.values.values()].sort((a, b) => b.count - a.count || a.value.localeCompare(b.value)) }))
    .sort((a, b) => a.key.localeCompare(b.key));
}

// Normalise GET /api/tags output.
export function normalizeTagIndex(raw) {
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((g) => g && g.key)
    .map((g) => ({
      key: displayCase(g.key),
      values: (Array.isArray(g.values) ? g.values : [])
        .map((v) => (typeof v === 'string' ? { value: v, count: 0 } : v))
        .filter((v) => v && v.value != null)
        .map((v) => ({ value: displayCase(v.value), count: Number(v.count) || 0 })),
    }));
}

// Suggestions: past keys first (by use), then presets.
export function keySuggestions(index) {
  const out = [];
  const add = (k) => {
    if (k && !out.some((x) => norm(x) === norm(k))) out.push(k);
  };
  [...index].sort((a, b) => sum(b) - sum(a)).forEach((g) => add(g.key));
  PRESET_TAG_KEYS.forEach((p) => add(p.key));
  return out;
}

const sum = (g) => g.values.reduce((a, v) => a + (v.count || 0), 0);

export function valueSuggestions(index, key) {
  const out = [];
  const add = (v) => {
    if (v && !out.some((x) => norm(x) === norm(v))) out.push(v);
  };
  index.find((g) => norm(g.key) === norm(key))?.values.forEach((v) => add(v.value));
  presetFor(key)?.values.forEach(add);
  return out;
}

export const iconForKey = (key) => presetFor(key)?.icon || 'tag';

// History filter: same key = OR, different keys = AND.
// selected: array of {key, value}.
export function matchesTagFilter(video, selected) {
  if (!selected.length) return true;
  const tags = allTagsOf(video);
  const byKey = new Map();
  for (const s of selected) {
    const k = norm(s.key);
    if (!byKey.has(k)) byKey.set(k, new Set());
    byKey.get(k).add(norm(s.value));
  }
  // The backend allows several values per key, so any of the video's values may match.
  for (const [k, values] of byKey) {
    if (!tags.some((x) => norm(x.key) === k && values.has(norm(x.value)))) return false;
  }
  return true;
}
