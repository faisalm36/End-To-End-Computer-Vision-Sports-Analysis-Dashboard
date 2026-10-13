import { useEffect, useState } from 'react';
import { getMatch, isUnsupported, updateMatch } from '../lib/api';
import { parseScore, RESULT_LABEL, resultFromScore, scoreFormFrom, scorePatch, validateScore } from '../lib/score';
import { btn, focusRing, input } from './classes';
import { Icon, Spinner } from './ui';

// Result chip. Neutral (slate) on purpose: green/amber/red are reserved for workload/status.
export function ResultChip({ result, className = '' }) {
  if (!result) return null;
  const tone = result === 'W' ? 'bg-slate-100 text-slate-950' : result === 'D' ? 'bg-slate-500 text-white' : 'bg-slate-700 text-white ring-1 ring-inset ring-slate-500';
  return (
    <span className={`inline-flex h-6 min-w-6 items-center justify-center rounded-md px-1.5 font-mono text-caption font-bold ${tone} ${className}`} title={RESULT_LABEL[result]}>
      <span aria-hidden="true">{result}</span>
      <span className="sr-only">{RESULT_LABEL[result]}</span>
    </span>
  );
}

// "Your team" Home/Away + two score boxes + live W/D/L preview.
// value = { our_side, home, away } (strings); onChange(next).
export function ScoreFields({ value, onChange, homeTeam, awayTeam, idPrefix, error, disabled = false }) {
  const h = parseScore(value.home);
  const a = parseScore(value.away);
  const preview = resultFromScore(h, a, value.our_side);
  const set = (patch) => onChange({ ...value, ...patch });
  const side = (s, text) => (
    <button
      type="button"
      role="radio"
      aria-checked={value.our_side === s}
      disabled={disabled}
      onClick={() => set({ our_side: s })}
      className={`h-8 rounded-md px-3 text-caption font-medium transition-colors ${focusRing} ${
        value.our_side === s ? 'bg-surface-overlay text-fg ring-1 ring-inset ring-line-strong' : 'text-fg-muted hover:text-fg'
      }`}
    >
      {text}
    </button>
  );
  const box = (key, teamName, labelText) => (
    <div className="min-w-0 flex-1">
      <label htmlFor={`${idPrefix}-${key}`} className="mb-1 block truncate text-caption text-fg-secondary" title={teamName || labelText}>
        {teamName || labelText}
        {value.our_side === key && <span className="text-fg-muted"> (you)</span>}
      </label>
      <input
        id={`${idPrefix}-${key}`}
        inputMode="numeric"
        maxLength={2}
        placeholder="–"
        disabled={disabled}
        value={value[key]}
        onChange={(e) => set({ [key]: e.target.value.replace(/[^\d]/g, '').slice(0, 2) })}
        aria-invalid={Boolean(error) || undefined}
        aria-describedby={`${idPrefix}-score-help`}
        className={`${input} h-10 text-center font-mono text-lg tabular-nums`}
      />
    </div>
  );
  return (
    <div>
      <div className="flex flex-wrap items-center gap-3">
        <span id={`${idPrefix}-side-label`} className="text-caption font-medium text-fg-secondary">
          Your team
        </span>
        <div role="radiogroup" aria-labelledby={`${idPrefix}-side-label`} className="inline-flex rounded-control bg-surface-sunken p-1 ring-1 ring-inset ring-line">
          {side('home', homeTeam ? `Home · ${homeTeam}` : 'Home')}
          {side('away', awayTeam ? `Away · ${awayTeam}` : 'Away')}
        </div>
      </div>
      <div className="mt-3 flex items-end gap-2">
        {box('home', homeTeam, 'Home')}
        <span aria-hidden="true" className="pb-2.5 font-mono text-fg-muted">
          –
        </span>
        {box('away', awayTeam, 'Away')}
        <div className="flex h-10 w-16 shrink-0 items-center justify-center" aria-live="polite">
          {preview ? <ResultChip result={preview} /> : <span className="text-caption text-fg-muted">W/D/L</span>}
        </div>
      </div>
      <p id={`${idPrefix}-score-help`} className={`mt-2 text-caption ${error ? 'text-status-danger' : 'text-fg-muted'}`}>
        {error || 'Optional. The result (W/D/L) is worked out from the score for your team.'}
      </p>
    </div>
  );
}

const scoreLine = (m) =>
  Number.isInteger(m?.home_score) && Number.isInteger(m?.away_score) ? `${m.home_score}–${m.away_score}` : null;

// Video page: "Final score 2–1 · W · Edit score". Reads GET /api/matches/{id} for
// our_side and the scores, falls back to the video's own match summary.
export default function MatchScore({ video, demo = false, onSaved }) {
  const matchId = video?.match_id ?? video?.match?.match_id ?? null;
  const [match, setMatch] = useState(() => ({
    match_id: matchId,
    home_team: video?.home_team ?? video?.match?.home_team,
    away_team: video?.away_team ?? video?.match?.away_team,
    home_score: video?.match?.home_score ?? null,
    away_score: video?.match?.away_score ?? null,
    our_side: video?.our_side ?? 'home',
    result: video?.result ?? video?.match?.result ?? null,
  }));
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState(() => scoreFormFrom(match));
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (demo || matchId == null) return undefined;
    const controller = new AbortController();
    getMatch(matchId, { signal: controller.signal })
      .then((m) => m && setMatch((cur) => ({ ...cur, ...m })))
      .catch(() => {}); // older backend: keep the video's summary
    return () => controller.abort();
  }, [matchId, demo]);

  if (matchId == null && !demo) return null;

  const start = () => {
    setForm(scoreFormFrom(match));
    setError(null);
    setEditing(true);
    requestAnimationFrame(() => document.getElementById('video-score-home')?.focus());
  };
  const save = async (e) => {
    e.preventDefault();
    const bad = validateScore(form);
    if (bad) return setError(bad);
    const patch = scorePatch(form, match);
    if (!patch) return setEditing(false);
    setSaving(true);
    setError(null);
    try {
      let next;
      if (demo) {
        const h = parseScore(form.home);
        const a = parseScore(form.away);
        next = { ...match, home_score: h, away_score: a, our_side: form.our_side, result: resultFromScore(h, a, form.our_side) };
      } else {
        next = { ...match, ...(await updateMatch(matchId, patch)) };
      }
      setMatch(next);
      onSaved?.(next);
      setEditing(false);
    } catch (err) {
      setError(isUnsupported(err) ? 'This server can’t store scores yet.' : err?.message || 'Couldn’t save the score.');
    } finally {
      setSaving(false);
    }
  };

  const line = scoreLine(match);
  if (!editing) {
    return (
      <div className="mt-2 flex flex-wrap items-center gap-2 text-body">
        {line ? (
          <>
            <span className="text-fg-muted">Final score</span>
            <span className="font-mono font-semibold tabular-nums text-fg">{line}</span>
            <ResultChip result={match.result} />
            {match.our_side && <span className="text-caption text-fg-muted">You were {match.our_side}</span>}
          </>
        ) : match.result ? (
          <>
            <span className="text-fg-muted">Result</span>
            <ResultChip result={match.result} />
          </>
        ) : (
          <span className="text-caption text-fg-muted">No score yet</span>
        )}
        <button type="button" onClick={start} className={`${btn.ghost} h-8 px-2.5 text-caption`}>
          <Icon name="trophy" className="size-3.5" />
          {line || match.result ? 'Edit score' : 'Add score'}
        </button>
      </div>
    );
  }
  return (
    <form
      onSubmit={save}
      onKeyDown={(e) => e.key === 'Escape' && (e.stopPropagation(), setEditing(false))}
      className="mt-3 max-w-xl rounded-xl border border-slate-800 bg-slate-900/60 p-4"
      aria-label="Edit final score"
    >
      <ScoreFields value={form} onChange={setForm} homeTeam={match.home_team} awayTeam={match.away_team} idPrefix="video-score" error={error} disabled={saving} />
      <div className="mt-3 flex flex-wrap gap-2">
        <button type="submit" disabled={saving} className={`${btn.primary} h-9 px-4`}>
          {saving && <Spinner className="size-3.5" />}
          Save score
        </button>
        <button type="button" onClick={() => setEditing(false)} className={`${btn.ghost} h-9 px-3`}>
          Cancel
        </button>
        {(form.home || form.away) && (
          <button type="button" onClick={() => setForm({ ...form, home: '', away: '' })} className={`${btn.ghost} h-9 px-3 text-caption`}>
            Clear score
          </button>
        )}
      </div>
    </form>
  );
}
