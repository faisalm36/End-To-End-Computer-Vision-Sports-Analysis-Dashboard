// Roster injury risk (rir-1.0): next-match surface toggle + date, current -> projected per player.
// Screening/education index only, not medical advice.
import { useMemo, useState } from 'react';
import { Link } from 'react-router';
import { card, container, focusRing, input, label } from '../components/classes';
import { BandChip, Delta, InjuryDisclaimer, SurfaceToggle } from '../components/InjuryRisk';
import { ErrorBanner, Skeleton } from '../components/ui';
import { useRosterInjuryRisk } from '../lib/injuryRisk';

const BANDS = ['all', 'high', 'moderate', 'low'];
const todayISO = () => new Date().toISOString().slice(0, 10);

export default function InjuryRoster() {
  const [surface, setSurface] = useState('grass');
  const [nextDate, setNextDate] = useState(() => {
    const d = new Date();
    d.setDate(d.getDate() + 7);
    return d.toISOString().slice(0, 10);
  });
  const [teamId, setTeamId] = useState('');
  const [band, setBand] = useState('all');
  const { data, loading, error, reload } = useRosterInjuryRisk({ team_id: teamId || undefined, next_surface: surface, next_date: nextDate });
  const rows = useMemo(() => (data?.players || []).filter((r) => band === 'all' || (r.status === 'injured' ? band === 'high' : r.band === band)), [data, band]);
  const counts = useMemo(() => {
    const c = { high: 0, moderate: 0, low: 0 };
    (data?.players || []).forEach((r) => (c[r.status === 'injured' ? 'high' : r.band] += 1));
    return c;
  }, [data]);

  return (
    <div className={`${container} py-8`}>
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className={label}>Next-match effect · model rir-1.0</p>
          <h1 className="mt-1 text-headline font-semibold text-fg">Roster injury risk</h1>
          <p className="mt-1 max-w-2xl text-body text-fg-secondary">
            Each player’s score today and projected for your next match, based on injury history, recent matches, rest days, playing surface and age.
          </p>
        </div>
        <Link to="/roster" className={`text-body text-fg-muted hover:text-fg ${focusRing} rounded`}>Workload (ML) view →</Link>
      </header>

      <InjuryDisclaimer className="mt-5" />

      <section className={`${card} mt-5 flex flex-wrap items-end gap-4 p-4`} aria-label="Next match">
        <div>
          <span className={label}>Next match surface</span>
          <div className="mt-1"><SurfaceToggle value={surface} onChange={setSurface} idPrefix="roster-surface" /></div>
        </div>
        <label className="block">
          <span className={label}>Next match date</span>
          <input type="date" min={todayISO()} value={nextDate} onChange={(e) => setNextDate(e.target.value)} className={`${input} mt-1 w-44`} />
        </label>
        {data?.teams?.length > 1 && (
          <label className="block">
            <span className={label}>Team</span>
            <select value={teamId} onChange={(e) => setTeamId(e.target.value)} className={`${input} mt-1 w-48`}>
              <option value="">All teams</option>
              {data.teams.map((t) => <option key={t.team_id} value={t.team_id}>{t.team_name}</option>)}
            </select>
          </label>
        )}
        <label className="block">
          <span className={label}>Band</span>
          <select value={band} onChange={(e) => setBand(e.target.value)} className={`${input} mt-1 w-40`}>
            {BANDS.map((b) => <option key={b} value={b}>{b === 'all' ? 'All bands' : `${b[0].toUpperCase()}${b.slice(1)} (${counts[b]})`}</option>)}
          </select>
        </label>
      </section>

      {error ? (
        <ErrorBanner className="mt-5" onRetry={reload} title="Couldn’t load roster injury risk">{error.message}</ErrorBanner>
      ) : loading && !data ? (
        <div className="mt-5 space-y-2">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-12" />)}</div>
      ) : rows.length === 0 ? (
        <p className="mt-6 text-body text-fg-muted">No players in this view yet.</p>
      ) : (
        <div className={`${card} mt-5 overflow-x-auto`}>
          <table className="w-full min-w-[720px] text-left text-body">
            <thead>
              <tr className="border-b border-line text-caption text-fg-muted">
                <th scope="col" className="px-5 py-2.5 font-medium">Player</th>
                <th scope="col" className="px-3 py-2.5 font-medium">Current</th>
                <th scope="col" className="px-3 py-2.5 font-medium">Projected ({surface})</th>
                <th scope="col" className="px-3 py-2.5 font-medium">Δ</th>
                <th scope="col" className="px-3 py-2.5 font-medium">Top factor</th>
                <th scope="col" className="px-5 py-2.5 font-medium">Confidence</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.player_id} data-player={r.player_id} className="border-b border-line/60 last:border-0">
                  <td className="px-5 py-3">
                    <Link to={`/players/${r.player_id}/risk?surface=${surface}&date=${nextDate}`} className={`font-medium text-fg hover:underline ${focusRing} rounded`}>
                      <span className="font-mono text-fg-muted">{r.number != null ? `#${r.number} ` : ''}</span>{r.name}
                    </Link>
                    {!r.has_injury_history && (
                      <Link to={`/players/${r.player_id}/risk?add=1`} className="block text-caption text-accent hover:underline">No history — add injuries</Link>
                    )}
                  </td>
                  <td className="px-3 py-3"><BandChip band={r.current_band} score={r.current} status={r.status} /></td>
                  <td className="px-3 py-3"><BandChip band={r.band} score={r.projected} status={r.status} /></td>
                  <td className="px-3 py-3"><Delta value={r.delta} /></td>
                  <td className="px-3 py-3 text-fg-secondary">{r.top_factor || '—'}</td>
                  <td className="px-5 py-3 text-caption capitalize text-fg-muted">{r.confidence}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="mt-4 text-caption text-fg-muted">Bands: low &lt; 25 ≤ moderate &lt; 50 ≤ high. Scores are relative indicators, not calibrated probabilities.</p>
    </div>
  );
}
