// Match score / result helpers (backend: PATCH /api/matches/{id}
// { home_score, away_score, our_side, result }; scores in pairs, result derived).

// W/D/L for "our" side from a score pair, or null.
export function resultFromScore(home, away, ourSide = 'home') {
  if (!Number.isInteger(home) || !Number.isInteger(away)) return null;
  const [us, them] = ourSide === 'away' ? [away, home] : [home, away];
  return us > them ? 'W' : us < them ? 'L' : 'D';
}

export const RESULT_LABEL = { W: 'Win', D: 'Draw', L: 'Loss' };

// '' -> null, '3' -> 3, anything else -> NaN (invalid).
export function parseScore(raw) {
  const v = String(raw ?? '').trim();
  if (v === '') return null;
  return /^\d{1,2}$/.test(v) ? Number(v) : NaN;
}

// Form value: { our_side: 'home'|'away', home: string, away: string }
export const scoreFormFrom = (m) => ({
  our_side: m?.our_side === 'away' ? 'away' : 'home',
  home: Number.isInteger(m?.home_score) ? String(m.home_score) : '',
  away: Number.isInteger(m?.away_score) ? String(m.away_score) : '',
});

export function validateScore(form) {
  const h = parseScore(form.home);
  const a = parseScore(form.away);
  if (Number.isNaN(h) || Number.isNaN(a)) return 'Scores are whole numbers from 0 to 99.';
  if ((h === null) !== (a === null)) return 'Enter both scores, or leave both blank.';
  return null;
}

// PATCH body with only what changed vs `initial` (a match object), or null if nothing did.
export function scorePatch(form, initial = null) {
  const h = parseScore(form.home);
  const a = parseScore(form.away);
  const patch = {};
  if ((initial?.our_side ?? 'home') !== form.our_side) patch.our_side = form.our_side;
  if ((initial?.home_score ?? null) !== h || (initial?.away_score ?? null) !== a) {
    patch.home_score = h;
    patch.away_score = a;
  }
  return Object.keys(patch).length ? patch : null;
}
