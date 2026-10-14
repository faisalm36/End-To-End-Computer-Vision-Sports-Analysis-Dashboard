// Roster injury-risk view (backend v0.7.0 provisional contract: GET /api/roster/risk).
// Workload indicator, not medical advice. Thresholds come from the response.
import { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import { useAuth } from '../auth/useAuth';
import { btn, card, container, focusRing, input, label } from '../components/classes';
import { DataQualityBadge, FactorBars, FeatureGrid, RiskLevelBadge, ScoreNote, WorkloadDisclaimer } from '../components/Risk';
import { ErrorBanner, Icon, NoticeBanner, Skeleton } from '../components/ui';
import { getPlayerRisk, getRosterRisk } from '../lib/api';
import { formatDate } from '../lib/format';
import { WORKLOAD_DISCLAIMER } from '../lib/metrics';
import { countByLevel, isScored, LEVEL_META, mostlyUnscored, normalizeRosterRisk, sortByRisk, teamsFrom, thresholdText } from '../lib/risk';
import { SAMPLE_ROSTER_RISK } from '../lib/sampleData';

// FastAPI's own "route not found" body is exactly {detail: "Not Found"}.
// Only a FastAPI "route not found" 404 means the endpoint isn't deployed yet.
// 503 is an ops problem (encryption key / model) — show the server's reason.
const isRouteMissing = (err) => err?.status === 404 && (!err?.data?.detail || err.data.detail === 'Not Found');

function sourceText(p) {
  if (!p.source) return 'No workload data yet';
  const when = p.match_date ? formatDate(p.match_date) : p.computed_at ? formatDate(p.computed_at) : null;
  const src = p.source === 'csv' ? 'Athlete log (CSV)' : p.source === 'match' ? 'Match tracking' : String(p.source);
  return when ? `${src} · ${when}` : src;
}

function PlayerHistory({ playerId, thresholds }) {
  const [state, setState] = useState({ kind: 'loading', items: [] });
  useEffect(() => {
    const ctrl = new AbortController();
    (async () => {
      try {
        const items = await getPlayerRisk(playerId, { thresholds, signal: ctrl.signal });
        setState({ kind: 'ready', items });
      } catch (err) {
        if (err?.kind === 'abort') return;
        setState({ kind: isRouteMissing(err) || err?.status === 404 ? 'none' : 'error', items: [], message: err?.message });
      }
    })();
    return () => ctrl.abort();
  }, [playerId, thresholds]);

  if (state.kind === 'loading') return <Skeleton className="h-8 w-full" />;
  if (state.kind === 'error') return <p className="text-caption text-fg-muted">Couldn’t load score history ({state.message}).</p>;
  if (state.kind === 'none' || !state.items.length) return <p className="text-caption text-fg-muted">No earlier scores on this server.</p>;
  return (
    <ul className="space-y-1.5" data-history>
      {state.items.slice(0, 5).map((h, i) => (
        <li key={i} className="flex flex-wrap items-center justify-between gap-2 text-caption">
          <span className="text-fg-secondary">
            {formatDate(h.date)}
            {h.source && <span className="text-fg-muted"> · {h.source === 'csv' ? 'CSV' : h.source === 'match' ? 'Match' : h.source}</span>}
          </span>
          <span className="flex flex-wrap items-center justify-end gap-1.5">
            <DataQualityBadge quality={h.data_quality} />
            <RiskLevelBadge level={h.level} riskPercent={h.risk_percent} />
          </span>
          <ScoreNote item={h} className="w-full text-right" />
        </li>
      ))}
    </ul>
  );
}

function PlayerRow({ p, open, onToggle, thresholds, sample }) {
  const top = p.factors[0];
  const panelId = `risk-panel-${p.player_id}`;
  return (
    <li data-risk-player={p.player_id} data-level={p.level} className="border-b border-line last:border-b-0">
      <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-2 px-4 py-3 sm:px-5 lg:grid-cols-[minmax(0,2fr)_9rem_minmax(0,1.6fr)_minmax(0,1.3fr)_auto]">
        <div className="min-w-0">
          <p className="truncate text-body font-medium text-fg">
            <span className="font-mono text-fg-muted">{p.jersey_number != null ? `#${p.jersey_number}` : '—'}</span> {p.name}
          </p>
          <p className="truncate text-caption text-fg-muted">{[p.position, p.team?.team_name].filter(Boolean).join(' · ') || 'No team'}</p>
        </div>
        <div className="justify-self-end lg:justify-self-start">
          <RiskLevelBadge level={p.level} riskPercent={p.risk_percent} />
        </div>
        <p className={`col-span-2 min-w-0 text-caption text-fg-secondary lg:col-span-1 ${isScored(p) ? 'truncate' : ''}`} data-top-factor>
          {!isScored(p) ? (
            <ScoreNote item={p} />
          ) : top ? (
            <>
              <span className="text-fg-muted">Top factor: </span>
              {top.label} <span className={top.direction === 'up' ? 'text-risk-high' : 'text-risk-low'}>{top.direction === 'up' ? '▲ raises' : '▼ lowers'}</span>
            </>
          ) : (
            <span className="text-fg-muted">No factors</span>
          )}
        </p>
        <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
          <span className="min-w-0 truncate text-caption text-fg-muted">{sourceText(p)}</span>
          <DataQualityBadge quality={p.data_quality} />
        </div>
        <button
          type="button"
          aria-expanded={open}
          aria-controls={panelId}
          onClick={onToggle}
          className={`${btn.ghost} h-9 justify-self-end px-3 text-caption`}
          aria-label={`${open ? 'Hide' : 'Show'} factors for ${p.name}`}
        >
          {open ? 'Hide' : 'Factors'}
          <span aria-hidden="true">{open ? '▴' : '▾'}</span>
        </button>
      </div>
      {open && (
        <div id={panelId} className="grid gap-6 border-t border-line bg-surface-sunken/40 px-4 py-4 sm:px-5 md:grid-cols-2" data-risk-panel>
          {isScored(p) ? (
            <div>
              <p className={label}>What drives this score</p>
              <p className="mt-1 text-caption text-fg-muted">Bars compare factors with each other; longer means a bigger effect on this score.</p>
              <FactorBars factors={p.factors} className="mt-3" />
            </div>
          ) : (
            <div>
              <p className={label}>Not scored</p>
              <p className="mt-1 text-body text-fg-secondary">{p.score_note}</p>
              <p className="mt-2 text-caption text-fg-muted">
                Athlete logs give the most reliable scores.{' '}
                <Link to="/roster/upload" className={`rounded underline hover:text-fg ${focusRing}`}>
                  Upload a CSV
                </Link>
              </p>
            </div>
          )}
          <div className="space-y-4">
            <div>
              <p className={label}>Workload inputs</p>
              <div className="mt-2">
                <FeatureGrid features={p.features} />
              </div>
            </div>
            <div className="text-caption text-fg-muted">
              <p>{sourceText(p)}</p>
              {p.model_version && <p>Model {p.model_version}{p.computed_at ? ` · scored ${formatDate(p.computed_at, { withTime: true })}` : ''}</p>}
              {p.video_id != null && (
                <Link to={`/videos/${p.video_id}`} className={`mt-1 inline-block rounded text-fg-secondary underline hover:text-fg ${focusRing}`}>
                  Open match results
                </Link>
              )}
            </div>
            {!sample && p.player_id != null && (
              <div>
                <p className={label}>Recent scores</p>
                <div className="mt-2">
                  <PlayerHistory playerId={p.player_id} thresholds={thresholds} />
                </div>
              </div>
            )}
            <WorkloadDisclaimer />
          </div>
        </div>
      )}
    </li>
  );
}

export default function RosterRisk() {
  const { isDemo } = useAuth();
  const [params, setParams] = useSearchParams();
  const team = params.get('team_id') || '';
  const matchId = params.get('match_id') || '';
  const sort = params.get('sort') === 'asc' ? 'asc' : 'desc';
  const [state, setState] = useState({ kind: 'loading', data: null, error: null });
  const [knownTeams, setKnownTeams] = useState([]);
  const [openId, setOpenId] = useState(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    const ctrl = new AbortController();
    (async () => {
      let data;
      try {
        if (isDemo) {
          await Promise.resolve();
          const all = normalizeRosterRisk(SAMPLE_ROSTER_RISK);
          data = { ...all, players: team ? all.players.filter((p) => String(p.team?.team_id) === team) : all.players, sample: true };
          setKnownTeams(teamsFrom(all.players));
        } else {
          data = await getRosterRisk({ team_id: team || undefined, match_id: matchId || undefined, signal: ctrl.signal });
        }
      } catch (err) {
        if (err?.kind === 'abort' || ctrl.signal.aborted) return;
        setState({ kind: isRouteMissing(err) ? 'unavailable' : 'error', data: null, error: err });
        return;
      }
      if (ctrl.signal.aborted) return;
      setState({ kind: 'ready', data, error: null });
      setKnownTeams((prev) => {
        const map = new Map(prev.map((t) => [String(t.team_id), t]));
        for (const t of teamsFrom(data.players)) map.set(String(t.team_id), t);
        return [...map.values()].sort((a, b) => String(a.team_name).localeCompare(String(b.team_name)));
      });
    })();
    return () => ctrl.abort();
    // Sorting is client-side (unknown scores always last), so it doesn't refetch.
  }, [isDemo, team, matchId, reload]);

  const players = useMemo(() => sortByRisk(state.data?.players || [], sort), [state.data, sort]);
  const counts = useMemo(() => countByLevel(players), [players]);

  const setParam = (key, value) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };

  const header = (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <p className={label}>Workload</p>
        <h1 className="mt-1 text-3xl font-bold tracking-tight text-fg">Roster risk</h1>
        <p className="mt-1 max-w-2xl text-body text-fg-muted">
          Injury-risk scores from match tracking and uploaded athlete logs, highest first. <strong className="font-semibold text-fg-secondary">{WORKLOAD_DISCLAIMER}.</strong>
        </p>
      </div>
      <Link to="/roster/upload" className={`${btn.secondary} shrink-0`}>
        <Icon name="upload" className="size-4" />
        Upload athlete log (CSV)
      </Link>
    </div>
  );

  if (state.kind === 'loading') {
    return (
      <div className={`${container} py-8 sm:py-10`} aria-busy="true">
        {header}
        <div className={`${card} mt-8 space-y-3 p-5`}>
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </div>
      </div>
    );
  }

  if (state.kind === 'unavailable') {
    return (
      <div className={`${container} py-8 sm:py-10`} data-unavailable>
        {header}
        <div className={`${card} mt-8 p-5 sm:p-6`}>
          <h2 className="text-title text-fg">Roster risk isn’t available on this server yet</h2>
          <p className="mt-1 text-body text-fg-muted">
            This backend doesn’t have injury-risk scoring yet (needs v0.7.0). Match results and player stats still work as before.
          </p>
        </div>
      </div>
    );
  }

  if (state.kind === 'error') {
    const s = state.error?.status;
    const title = s === 401 ? 'Your session has expired' : s === 422 ? 'The server rejected these filters' : s === 404 ? 'Not found' : s === 503 ? 'Risk scoring is unavailable' : 'Couldn’t load roster risk';
    return (
      <div className={`${container} py-8 sm:py-10`}>
        {header}
        <ErrorBanner className="mt-8" title={title} onRetry={s === 401 ? undefined : () => setReload((k) => k + 1)}>
          {state.error?.message}
          {(s === 404 || s === 422) && (team || matchId) && (
            <button type="button" className={`ml-2 rounded underline ${focusRing}`} onClick={() => setParams(new URLSearchParams(), { replace: true })}>
              Clear filters
            </button>
          )}
        </ErrorBanner>
      </div>
    );
  }

  const data = state.data;
  const tText = thresholdText(data.thresholds);
  const unscored = players.filter((p) => !isScored(p)).length;
  const hasDemo = players.some((p) => p.data_quality === 'demo');
  const csvCta = mostlyUnscored(players) && (
    <div className={`${card} mt-6 flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:justify-between sm:p-6`} data-csv-cta>
      <div>
        <h2 className="text-title text-fg">{players.length ? `${unscored} of ${players.length} players have no workload score yet` : 'No workload scores yet'}</h2>
        <p className="mt-1 max-w-2xl text-body text-fg-muted">
          Athlete logs (GPS distance, sprints, heart rate, minutes) are the main source of scores. Broadcast video without a pitch calibration can’t be scored.
        </p>
      </div>
      <Link to="/roster/upload" className={`${btn.primary} shrink-0`}>
        <Icon name="upload" className="size-4" />
        Upload athlete log (CSV)
      </Link>
    </div>
  );
  return (
    <div className={`${container} py-8 sm:py-10`}>
      {header}

      {data.sample && <NoticeBanner className="mt-6">Demo mode: showing sample risk scores, not real players.</NoticeBanner>}
      {!data.sample && hasDemo && (
        <NoticeBanner className="mt-6">
          <span data-demo-warning>Some scores below are demo data (seed or stub values from the server), not real measurements. They’re marked “Demo data”.</span>
        </NoticeBanner>
      )}

      <div className="mt-6 flex flex-col gap-4 sm:flex-row sm:flex-wrap sm:items-end">
        <div className="sm:w-56">
          <label htmlFor="risk-team" className="mb-1.5 block text-body font-medium text-fg-secondary">
            Team
          </label>
          <select id="risk-team" className={input} value={team} onChange={(e) => setParam('team_id', e.target.value)}>
            <option value="">All teams</option>
            {knownTeams.map((t) => (
              <option key={t.team_id} value={String(t.team_id)}>
                {t.team_name}
              </option>
            ))}
          </select>
        </div>
        <div role="group" aria-label="Sort by risk" className="inline-flex w-full rounded-control bg-surface-overlay p-1 ring-1 ring-inset ring-line-strong sm:w-auto">
          {[
            ['desc', 'Highest first'],
            ['asc', 'Lowest first'],
          ].map(([v, text]) => (
            <button
              key={v}
              type="button"
              aria-pressed={sort === v}
              onClick={() => setParam('sort', v === 'desc' ? '' : v)}
              className={`h-9 flex-1 rounded-[0.5rem] px-3 text-body font-medium sm:flex-none ${focusRing} ${sort === v ? 'bg-accent text-on-accent' : 'text-fg-secondary hover:text-fg'}`}
            >
              {text}
            </button>
          ))}
        </div>
        {matchId && (
          <span className="inline-flex h-9 items-center gap-2 self-start rounded-chip bg-surface-overlay px-3 text-caption text-fg-secondary ring-1 ring-inset ring-line-strong sm:self-auto">
            Match {matchId}
            <button type="button" onClick={() => setParam('match_id', '')} aria-label="Clear match filter" className={`rounded text-fg-muted hover:text-fg ${focusRing}`}>
              <Icon name="x" className="size-3.5" />
            </button>
          </span>
        )}
      </div>

      <div className="mt-6 flex flex-wrap items-center gap-2" data-level-counts>
        {['red', 'yellow', 'green', 'unknown'].map((lv) => (
          <span key={lv} className="inline-flex items-center gap-1.5 text-caption text-fg-secondary">
            <RiskLevelBadge level={lv} />
            <span className="font-mono tabular-nums" data-count={lv}>
              {counts[lv] || 0}
            </span>
            <span className="sr-only">{LEVEL_META[lv].label} players</span>
          </span>
        ))}
      </div>
      <p className="mt-2 text-caption text-fg-muted" data-thresholds>
        {tText ? `Levels: ${tText}` : 'Levels as reported by the server.'}
        {data.model_version && ` · Model ${data.model_version}`}
        {data.generated_at && ` · Updated ${formatDate(data.generated_at, { withTime: true })}`}
      </p>

      {csvCta}
      {!players.length ? (
        <div className={`${card} mt-6 p-6`}>
          <p className="text-body text-fg-secondary">{team ? 'No players on this team yet.' : 'No players on your roster yet.'}</p>
        </div>
      ) : (
        <div className={`${card} mt-6 overflow-hidden`}>
          <div className="hidden grid-cols-[minmax(0,2fr)_9rem_minmax(0,1.6fr)_minmax(0,1.3fr)_auto] gap-x-3 border-b border-line px-5 py-2 lg:grid" aria-hidden="true">
            {['Player', 'Risk', 'Top factor', 'Source', ''].map((h, i) => (
              <span key={i} className={label}>
                {h}
              </span>
            ))}
          </div>
          <ul aria-label="Players by injury risk">
            {players.map((p) => (
              <PlayerRow
                key={p.player_id ?? p.name}
                p={p}
                thresholds={data.thresholds}
                sample={Boolean(data.sample)}
                open={openId === p.player_id}
                onToggle={() => setOpenId((id) => (id === p.player_id ? null : p.player_id))}
              />
            ))}
          </ul>
        </div>
      )}
      <WorkloadDisclaimer className="mt-4" />
    </div>
  );
}
