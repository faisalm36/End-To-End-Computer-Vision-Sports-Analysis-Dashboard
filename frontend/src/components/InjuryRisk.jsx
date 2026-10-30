// Roster injury-risk UI pieces (rir-1.0): band chip, delta, disclaimer, trend chart, factor breakdown,
// injury history form + list. Colour is never the only signal (icons + text labels everywhere).
import { useState } from 'react';
import { btn, card, focusRing, input, label } from './classes';
import { Icon, Spinner } from './ui';
import { BAND_META, BODY_PARTS, INJURY_DISCLAIMER, INJURY_TYPES, SIDES, pretty } from '../lib/injuryRisk';

export function InjuryDisclaimer({ className = '' }) {
  return (
    <div role="note" data-disclaimer className={`flex items-start gap-2 rounded-xl border border-risk-medium-ring bg-risk-medium-bg/60 px-4 py-3 text-caption text-fg-secondary ${className}`}>
      <Icon name="alert" className="mt-0.5 size-4 shrink-0 text-status-warning" />
      <p>{INJURY_DISCLAIMER}</p>
    </div>
  );
}

export function BandChip({ band, score, status, className = '' }) {
  if (status === 'injured') {
    return (
      <span data-band="injured" className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-chip bg-risk-high-bg px-2.5 py-0.5 text-caption font-semibold text-risk-high ring-1 ring-inset ring-risk-high-ring ${className}`}>
        <Icon name="x" className="size-3.5" /> Injured
      </span>
    );
  }
  const m = BAND_META[band] || BAND_META.low;
  return (
    <span data-band={band} className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-chip px-2.5 py-0.5 text-caption font-semibold ring-1 ring-inset ${m.cls} ${className}`}>
      <Icon name={m.icon} className="size-3.5" />
      {m.label}
      {score != null && <span className="font-mono tabular-nums">{Number(score).toFixed(0)}</span>}
    </span>
  );
}

export function Delta({ value }) {
  if (value == null) return <span className="text-fg-muted">—</span>;
  const up = value > 0.05;
  const down = value < -0.05;
  const cls = up ? 'text-risk-high' : down ? 'text-risk-low' : 'text-fg-muted';
  return (
    <span className={`inline-flex items-center gap-0.5 font-mono tabular-nums ${cls}`} aria-label={`change ${value > 0 ? '+' : ''}${value}`}>
      <span aria-hidden="true">{up ? '▲' : down ? '▼' : '■'}</span>
      {value > 0 ? '+' : ''}
      {Number(value).toFixed(1)}
    </span>
  );
}

export function SurfaceToggle({ value, onChange, idPrefix = 'surface' }) {
  return (
    <div role="radiogroup" aria-label="Next match surface" className="inline-flex rounded-control bg-surface-overlay p-1 ring-1 ring-inset ring-line-strong">
      {['grass', 'turf'].map((s) => (
        <button
          key={s}
          id={`${idPrefix}-${s}`}
          type="button"
          role="radio"
          aria-checked={value === s}
          onClick={() => onChange(s)}
          className={`h-8 rounded-lg px-4 text-body font-semibold transition-colors ${focusRing} ${value === s ? 'bg-accent text-on-accent' : 'text-fg-secondary hover:text-fg'}`}
        >
          {s === 'grass' ? '🌱 Grass' : '🟩 Turf'}
        </button>
      ))}
    </div>
  );
}

// SVG line chart: previous per-match scores (dots coloured by surface) + dashed projected point.
export function TrendChart({ previous = [], projection }) {
  const pts = previous.map((p) => ({ ...p, kind: 'past' }));
  if (projection) pts.push({ as_of: projection.as_of, score: projection.score, surface: projection.next_surface || 'unknown', kind: 'proj' });
  if (pts.length === 0) return <p className="text-caption text-fg-muted">No matches yet — the trend appears after the first match is analysed.</p>;
  const W = 640;
  const H = 220;
  const pad = { l: 36, r: 16, t: 12, b: 28 };
  const x = (i) => pad.l + (pts.length === 1 ? (W - pad.l - pad.r) / 2 : (i * (W - pad.l - pad.r)) / (pts.length - 1));
  const y = (s) => pad.t + (1 - s / 100) * (H - pad.t - pad.b);
  const past = pts.filter((p) => p.kind === 'past');
  const line = past.map((p, i) => `${i ? 'L' : 'M'}${x(i)},${y(p.score)}`).join(' ');
  const surfColor = (s) => (s === 'turf' || s === 'indoor' ? '#38bdf8' : s === 'grass' || s === 'hybrid' ? '#4ade80' : '#94a3b8');
  return (
    <figure>
      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label="Injury-risk score per match with projected next match">
        {[25, 50].map((t) => (
          <g key={t}>
            <line x1={pad.l} x2={W - pad.r} y1={y(t)} y2={y(t)} stroke="#334155" strokeDasharray="4 4" />
            <text x={4} y={y(t) + 4} fontSize="11" fill="#94a3b8">{t}</text>
          </g>
        ))}
        <line x1={pad.l} x2={W - pad.r} y1={y(0)} y2={y(0)} stroke="#334155" />
        {line && <path d={line} fill="none" stroke="#cbd5e1" strokeWidth="2" />}
        {projection && past.length > 0 && (
          <path d={`M${x(past.length - 1)},${y(past[past.length - 1].score)} L${x(pts.length - 1)},${y(projection.score)}`} stroke="#cbd5e1" strokeWidth="2" strokeDasharray="6 5" fill="none" />
        )}
        {pts.map((p, i) => (
          <g key={`${p.as_of}-${i}`}>
            <circle cx={x(i)} cy={y(p.score)} r={p.kind === 'proj' ? 7 : 5} fill={p.kind === 'proj' ? 'transparent' : surfColor(p.surface)} stroke={surfColor(p.surface)} strokeWidth="2.5" strokeDasharray={p.kind === 'proj' ? '3 2' : undefined}>
              <title>{`${p.kind === 'proj' ? 'Projected' : 'Match'} ${p.as_of}: ${p.score} (${p.surface})`}</title>
            </circle>
            {(pts.length <= 8 || i === pts.length - 1 || i === 0) && (
              <text x={x(i)} y={H - 8} fontSize="10" textAnchor="middle" fill="#94a3b8">{p.kind === 'proj' ? 'Next' : p.as_of.slice(5)}</text>
            )}
          </g>
        ))}
      </svg>
      <figcaption className="mt-2 flex flex-wrap gap-4 text-caption text-fg-muted">
        <span className="inline-flex items-center gap-1.5"><span className="size-2.5 rounded-full bg-[#4ade80]" /> Grass</span>
        <span className="inline-flex items-center gap-1.5"><span className="size-2.5 rounded-full bg-[#38bdf8]" /> Turf</span>
        <span className="inline-flex items-center gap-1.5"><span className="size-2.5 rounded-full bg-[#94a3b8]" /> Surface unknown</span>
        <span className="inline-flex items-center gap-1.5"><span className="size-2.5 rounded-full border-2 border-dashed border-fg-muted" /> Projected</span>
      </figcaption>
    </figure>
  );
}

export function FactorBreakdown({ factors = [] }) {
  if (!factors.length) return <p className="text-caption text-fg-muted">No risk factors raise this score — it sits at the baseline match injury rate.</p>;
  const max = Math.max(...factors.map((f) => Math.log(f.multiplier)), Math.log(2));
  return (
    <ul className="space-y-3">
      {factors.map((f) => (
        <li key={f.key} data-factor={f.key}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-body font-medium text-fg">{f.label}</span>
            <span className="flex items-center gap-2">
              <span
                title={f.citation || ''}
                className={`rounded-chip px-2 py-0.5 text-caption ring-1 ring-inset ${f.basis === 'evidence' ? 'bg-risk-low-bg text-risk-low ring-risk-low-ring' : 'bg-surface-overlay text-fg-secondary ring-line-strong'}`}
              >
                {f.basis === 'evidence' ? 'Research-based' : 'Design choice'}
              </span>
              <span className="font-mono tabular-nums text-fg">×{Number(f.multiplier).toFixed(2)}</span>
            </span>
          </div>
          <div className="mt-1.5 h-2 rounded-full bg-surface-overlay" aria-hidden="true">
            <div className="h-2 rounded-full bg-accent" style={{ width: `${Math.max(4, (Math.log(f.multiplier) / max) * 100)}%` }} />
          </div>
          <p className="mt-1 text-caption text-fg-muted">
            {f.detail}
            {f.citation && <span className="block italic">Source: {f.citation}</span>}
          </p>
        </li>
      ))}
    </ul>
  );
}

const EMPTY = { body_part: 'hamstring', injury_type: 'muscle_strain', side: 'na', injury_date: '', return_date: '', days_missed: '', is_recurrence: false, notes: '' };
const today = () => new Date().toISOString().slice(0, 10);

export function InjuryForm({ initial, onSubmit, onCancel }) {
  const [f, setF] = useState(() => ({ ...EMPTY, ...(initial || {}), return_date: initial?.return_date || '', days_missed: initial?.days_missed ?? '', notes: initial?.notes || '' }));
  const [ongoing, setOngoing] = useState(Boolean(initial && !initial.return_date && initial.days_missed == null));
  const [err, setErr] = useState(null);
  const [saving, setSaving] = useState(false);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value });
  const submit = async (e) => {
    e.preventDefault();
    if (!f.injury_date) return setErr('Injury date is required.');
    if (f.injury_date > today()) return setErr('Injury date can’t be in the future.');
    if (!ongoing && f.return_date && f.return_date < f.injury_date) return setErr('Return date must be on or after the injury date.');
    const body = {
      body_part: f.body_part, injury_type: f.injury_type, side: f.side, injury_date: f.injury_date, is_recurrence: f.is_recurrence,
      return_date: ongoing ? null : f.return_date || null,
      days_missed: ongoing || f.days_missed === '' ? null : Number(f.days_missed),
      notes: f.notes || null,
    };
    setSaving(true);
    setErr(null);
    try {
      await onSubmit(body);
    } catch (ex) {
      setErr(ex?.message || 'Couldn’t save the injury.');
    } finally {
      setSaving(false);
    }
  };
  const sel = (k, opts, lbl) => (
    <label className="block">
      <span className={label}>{lbl}</span>
      <select value={f[k]} onChange={set(k)} className={`${input} mt-1`}>
        {opts.map((o) => <option key={o} value={o}>{pretty(o)}</option>)}
      </select>
    </label>
  );
  return (
    <form onSubmit={submit} className="space-y-4" aria-label="Injury history entry">
      <div className="grid gap-4 sm:grid-cols-3">
        {sel('body_part', BODY_PARTS, 'Body part')}
        {sel('injury_type', INJURY_TYPES, 'Injury type')}
        {sel('side', SIDES, 'Side')}
      </div>
      <div className="grid gap-4 sm:grid-cols-3">
        <label className="block">
          <span className={label}>Injury date</span>
          <input type="date" required max={today()} value={f.injury_date} onChange={set('injury_date')} className={`${input} mt-1`} />
        </label>
        <label className="block">
          <span className={label}>Return date</span>
          <input type="date" disabled={ongoing} min={f.injury_date || undefined} value={f.return_date} onChange={set('return_date')} className={`${input} mt-1`} />
        </label>
        <label className="block">
          <span className={label}>…or days missed</span>
          <input type="number" min="0" max="3650" disabled={ongoing || Boolean(f.return_date)} value={f.days_missed} onChange={set('days_missed')} className={`${input} mt-1`} placeholder="e.g. 21" />
        </label>
      </div>
      <div className="flex flex-wrap gap-6">
        <label className="inline-flex items-center gap-2 text-body text-fg-secondary">
          <input type="checkbox" checked={ongoing} onChange={(e) => setOngoing(e.target.checked)} className="size-4 accent-accent" />
          Still injured (no return yet)
        </label>
        <label className="inline-flex items-center gap-2 text-body text-fg-secondary">
          <input type="checkbox" checked={f.is_recurrence} onChange={set('is_recurrence')} className="size-4 accent-accent" />
          Re-injury of the same area
        </label>
      </div>
      <label className="block">
        <span className={label}>Notes (encrypted, optional)</span>
        <textarea rows={2} maxLength={2000} value={f.notes} onChange={set('notes')} className={`${input} mt-1 h-auto py-2`} placeholder="e.g. grade 2 sprain, physio cleared" />
      </label>
      {err && <p role="alert" className="text-caption text-status-danger">{err}</p>}
      <div className="flex gap-2">
        <button type="submit" disabled={saving} className={btn.primary}>{saving && <Spinner className="size-3.5" />}{initial ? 'Save changes' : 'Add injury'}</button>
        {onCancel && <button type="button" onClick={onCancel} className={btn.ghost}>Cancel</button>}
      </div>
    </form>
  );
}

export function InjuryList({ items = [], onEdit, onDelete }) {
  if (!items.length) return <p className="text-caption text-fg-muted">No injuries recorded yet.</p>;
  return (
    <ul className={`divide-y divide-line ${card}`}>
      {items.map((i) => (
        <li key={i.injury_id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3" data-injury={i.injury_id}>
          <div>
            <p className="text-body font-medium text-fg">
              {pretty(i.body_part)} · {pretty(i.injury_type)}{i.side !== 'na' ? ` (${i.side})` : ''}
              {i.active && <span className="ml-2 rounded-chip bg-risk-high-bg px-2 py-0.5 text-caption text-risk-high">Active</span>}
              {i.is_recurrence && <span className="ml-2 rounded-chip bg-surface-overlay px-2 py-0.5 text-caption text-fg-secondary">Recurrence</span>}
            </p>
            <p className="text-caption text-fg-muted">
              {i.injury_date} → {i.return_date || (i.days_missed != null ? `${i.days_missed} days missed` : 'ongoing')}
              {i.notes ? ` · ${i.notes}` : ''}
            </p>
          </div>
          <div className="flex gap-2">
            <button type="button" className={`${btn.ghost} h-8 px-3 text-caption`} onClick={() => onEdit(i)}>Edit</button>
            <button type="button" className={`${btn.ghost} h-8 px-3 text-caption text-status-danger`} onClick={() => onDelete(i)}>Delete</button>
          </div>
        </li>
      ))}
    </ul>
  );
}
