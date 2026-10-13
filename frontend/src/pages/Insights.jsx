import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router';
import { useAuth } from '../auth/useAuth';
import { btn, card, container, focusRing, input, label } from '../components/classes';
import { TagChip } from '../components/Tags';
import { EmptyState, ErrorBanner, Icon, NoticeBanner, Skeleton } from '../components/ui';
import { getInsights, getVideoStats, isUnsupported, listVideos, normalizeStatus } from '../lib/api';
import { computeInsights, INSIGHT_METRICS, MIN_PAIRS_FOR_CARD, MIN_SAMPLE, normalizeInsights, tagKeysOf } from '../lib/insights';
import { WORKLOAD_DISCLAIMER } from '../lib/metrics';
import { isNum, normalizePlayers } from '../lib/playerStats';
import { SAMPLE_INSIGHT_MATCHES } from '../lib/sampleData';
import { norm } from '../lib/tags';
import { useMetricDefs } from '../lib/useMetricDefs';

const MAX_VIDEOS = 60; // client-side fallback cap (one stats request per video)
const MAX_PLAYER_LIST_VIDEOS = 12; // server mode: stats of recent videos, only to list players

const fmtNum = (v, d = 1) => (isNum(v) ? v.toFixed(d) : '\u2014');
const unitOf = (def) => (def.unit ? ` ${def.unit}` : '');

function Segmented({ value, onChange, options, labelText }) {
  return (
    <div role="radiogroup" aria-label={labelText} className="inline-flex flex-wrap rounded-control bg-surface-sunken p-1 ring-1 ring-inset ring-line">
      {options.map((o) => (
        <button
          key={o.key}
          type="button"
          role="radio"
          aria-checked={value === o.key}
          onClick={() => onChange(o.key)}
          className={`h-8 rounded-md px-3 text-caption font-medium transition-colors ${focusRing} ${
            value === o.key ? 'bg-accent/10 text-accent ring-1 ring-inset ring-accent/50' : 'text-fg-muted hover:text-fg'
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

function ViewToggle({ table, onToggle }) {
  return (
    <button type="button" onClick={onToggle} aria-pressed={table} className={`${btn.ghost} h-8 px-2.5 text-caption`}>
      {table ? 'View as chart' : 'View as table'}
    </button>
  );
}

// Hover/focus tooltip wrapper for a chart mark.
function Tip({ text, children }) {
  return (
    <span className="group/tip relative block" tabIndex={0} aria-label={text}>
      {children}
      <span
        role="tooltip"
        className="pointer-events-none absolute bottom-full left-1/2 z-20 mb-2 hidden -translate-x-1/2 whitespace-nowrap rounded-lg bg-surface-overlay px-2.5 py-1.5 text-caption text-fg shadow-panel ring-1 ring-line-strong group-hover/tip:block group-focus/tip:block"
      >
        {text}
      </span>
    </span>
  );
}

function erdSecondary(metric, g) {
  if (metric === 'distance' && isNum(g.avg_distance_covered_meters)) return `${Math.round(g.avg_distance_covered_meters)} m`;
  if (metric === 'speed' && isNum(g.avg_top_speed_kmh)) return `${Number(g.avg_top_speed_kmh).toFixed(1)} km/h`;
  if (metric === 'sprints' && isNum(g.avg_minutes_played)) return `${Number(g.avg_minutes_played).toFixed(1)} min avg`;
  if (metric === 'workload' && isNum(g.avg_fatigue_risk_score)) return `fatigue ${Math.round(g.avg_fatigue_risk_score)}`;
  return null;
}

function sortGroups(groups, field) {
  const ranked = groups.filter((g) => !g.low_sample).sort((a, b) => (b[field] ?? -Infinity) - (a[field] ?? -Infinity));
  const low = groups.filter((g) => g.low_sample).sort((a, b) => a.value.localeCompare(b.value));
  return [...ranked, ...low];
}

function WorkloadBar({ wl }) {
  const total = wl ? wl.low + wl.medium + wl.high : 0;
  if (!total) return <div className="h-3 rounded-full bg-surface-sunken ring-1 ring-inset ring-line" />;
  const seg = [
    ['Low', wl.low, 'bg-risk-low'],
    ['Medium', wl.medium, 'bg-risk-medium'],
    ['High', wl.high, 'bg-risk-high'],
  ];
  return (
    <div className="flex h-3 overflow-hidden rounded-full bg-surface-sunken ring-1 ring-inset ring-line">
      {seg.map(([name, n, cls]) =>
        n ? <div key={name} className={cls} style={{ width: `${(n / total) * 100}%` }} title={`${name}: ${n} (${Math.round((n / total) * 100)}%)`} /> : null,
      )}
    </div>
  );
}

function ByCondition({ data, metric, tagKey, scopeLabel, availability }) {
  const [table, setTable] = useState(false);
  const def = INSIGHT_METRICS[metric];
  const groups = sortGroups(data.groups, def.field);
  const base = data.baseline?.[def.field];
  const vals = groups.map((g) => g[def.field]).filter(isNum);
  const hasData = vals.length > 0 || metric === 'workload';
  const max = Math.max(...vals, isNum(base) ? base : 0) * 1.1 || 1;
  const pct = (v) => (isNum(v) ? Math.min(100, (v / max) * 100) : 0);

  return (
    <section aria-labelledby="by-condition" className={`${card} p-5 sm:p-6`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 id="by-condition" className="text-title text-fg">
            By condition
          </h2>
          <p className="mt-1 text-caption text-fg-muted">
            {def.label} per {tagKey.toLowerCase()} value · {scopeLabel}
            {metric === 'workload' ? ` · ${WORKLOAD_DISCLAIMER}` : ''}
          </p>
        </div>
        <ViewToggle table={table} onToggle={() => setTable((t) => !t)} />
      </div>

      {!hasData ? (
        <p className="mt-6 rounded-xl border border-dashed border-line-strong p-4 text-body text-fg-muted">
          {def.registry && availability(def.registry) === 'soon'
            ? `${def.label} isn’t measured yet (coming soon), so there’s nothing to compare.`
            : 'No values for this metric in your tagged matches yet.'}
        </p>
      ) : table ? (
        <div className="mt-5 overflow-x-auto" tabIndex={0} role="region" aria-label="Insights table">
          <p className="sticky left-0 mb-1 flex items-center gap-1 text-caption text-fg-muted sm:hidden" aria-hidden="true">
            Scroll sideways for all columns <span>→</span>
          </p>
          <table className="min-w-full text-body">
            <thead className="border-b border-line text-left text-label uppercase text-fg-muted">
              <tr>
                <th scope="col" className="py-2 pr-4">{tagKey}</th>
                <th scope="col" className="py-2 pr-4 text-right">{metric === 'workload' ? 'Low / Med / High' : `Avg ${def.label.toLowerCase()}`}</th>
                <th scope="col" className="py-2 text-right">Matches</th>
              </tr>
            </thead>
            <tbody>
              {groups.map((g) => (
                <tr key={g.value} className="border-b border-line last:border-0">
                  <td className="py-2 pr-4 text-fg">{g.value}{g.low_sample ? ' (low sample)' : ''}</td>
                  <td className="py-2 pr-4 text-right font-mono tabular-nums text-fg">
                    <span>
                      {metric === 'workload' && g.workload ? `${g.workload.low} / ${g.workload.medium} / ${g.workload.high}` : `${fmtNum(g[def.field], def.digits)}${unitOf(def)}`}
                      {erdSecondary(metric, g) && <span className="mt-0.5 block text-caption text-fg-muted" data-erd-secondary>{erdSecondary(metric, g)}</span>}
                    </span>
                  </td>
                  <td className="py-2 text-right font-mono tabular-nums text-fg-secondary">{g.matches}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <ul className="mt-6 space-y-5">
          {groups.map((g) => {
            const low = g.low_sample;
            return (
              <li key={g.value} className={low ? 'opacity-50' : ''}>
                <div className="grid grid-cols-[6.5rem_1fr_auto] items-center gap-3 sm:grid-cols-[9rem_1fr_7rem]">
                  <span className="truncate text-body text-fg" title={g.value}>{g.value}</span>
                  {metric === 'workload' ? (
                    <Tip text={g.workload ? `${g.value}: ${g.workload.low} low, ${g.workload.medium} medium, ${g.workload.high} high player-matches` : `${g.value}: no workload data`}>
                      <WorkloadBar wl={g.workload} />
                    </Tip>
                  ) : (
                    <Tip text={`${g.value}: ${fmtNum(g[def.field], def.digits)}${unitOf(def)} average over ${g.matches} match${g.matches === 1 ? '' : 'es'}`}>
                      <div className="relative h-3 rounded-full bg-surface-sunken ring-1 ring-inset ring-line">
                        <div className={`h-full rounded-full ${def.bar}`} style={{ width: `${pct(g[def.field])}%` }} />
                        {isNum(base) && <span aria-hidden="true" className="absolute -inset-y-1 w-0.5 bg-slate-200" style={{ left: `${pct(base)}%` }} />}
                      </div>
                    </Tip>
                  )}
                  <span className="text-right font-mono text-body tabular-nums text-fg">
                    {metric === 'workload' ? fmtNum(g.avg_workload, 1) : fmtNum(g[def.field], def.digits)}
                    <span className="ml-1 text-caption text-fg-muted">{metric === 'workload' ? '/ 3' : def.unit}</span>
                  </span>
                </div>
                <p className="mt-1 text-caption text-fg-muted sm:pl-[9.75rem]">
                  n = {g.matches} match{g.matches === 1 ? '' : 'es'}
                  {isNum(g.matches_with_data) && g.matches_with_data < g.matches ? ` (${g.matches_with_data} with stats)` : ''}
                  {low ? ` · Low sample (need ${MIN_SAMPLE}), not ranked` : ''}
                </p>
              </li>
            );
          })}
        </ul>
      )}
      {hasData && !table && metric !== 'workload' && isNum(base) && (
        <p className="mt-5 flex items-center gap-2 text-caption text-fg-muted">
          <span aria-hidden="true" className="inline-block h-3 w-0.5 bg-slate-200" />
          {scopeLabel === 'Squad' ? 'Squad' : 'Player'} average across all analysed matches: {fmtNum(base, def.digits)}
          {unitOf(def)}
        </p>
      )}
      {metric === 'workload' && hasData && !table && (
        <p className="mt-5 flex flex-wrap gap-4 text-caption text-fg-muted">
          <span className="flex items-center gap-1.5"><span className="size-2 rounded-full bg-risk-low" />Low</span>
          <span className="flex items-center gap-1.5"><span className="size-2 rounded-full bg-risk-medium" />Medium</span>
          <span className="flex items-center gap-1.5"><span className="size-2 rounded-full bg-risk-high" />High</span>
          <span>Number on the right: average score, 1 = Low, 3 = High.</span>
        </p>
      )}
    </section>
  );
}

// W/D/L per tag value, from the match results (score entry on the video page or at
// upload). `unknown` = tagged matches without a result yet; counted, not charted as a result.
const WDL_SEG = [
  ['w', 'Won', 'bg-slate-100'],
  ['d', 'Drew', 'bg-slate-400'],
  ['l', 'Lost', 'bg-slate-600'],
];

function ResultsCard({ data, tagKey }) {
  const [table, setTable] = useState(false);
  const groups = data.groups.filter((g) => g.wdl);
  const known = (w) => w.w + w.d + w.l;
  const anyKnown = groups.some((g) => known(g.wdl) > 0);
  return (
    <section aria-labelledby="wdl-title" className={`${card} p-5 sm:p-6`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 id="wdl-title" className="text-title text-fg">
            Results (W / D / L)
          </h2>
          <p className="mt-1 text-caption text-fg-muted">Your results per {tagKey.toLowerCase()} value. Correlation, not cause.</p>
        </div>
        {anyKnown && <ViewToggle table={table} onToggle={() => setTable((t) => !t)} />}
      </div>
      {!anyKnown ? (
        <p className="mt-4 text-body text-fg-muted">
          No results recorded for these matches yet. Add the final score on a match’s results page (or when you upload) and W/D/L shows up here.
          {groups.length > 0 && ` ${groups.reduce((a, g) => a + g.wdl.unknown, 0)} tagged matches have no result.`}
        </p>
      ) : table ? (
        <div className="mt-5 overflow-x-auto" tabIndex={0} role="region" aria-label="Insights table">
          <p className="sticky left-0 mb-1 flex items-center gap-1 text-caption text-fg-muted sm:hidden" aria-hidden="true">
            Scroll sideways for all columns <span>→</span>
          </p>
          <table className="min-w-full whitespace-nowrap text-body">
            <thead className="border-b border-line text-left text-label uppercase text-fg-muted">
              <tr>
                <th scope="col" className="py-2 pr-4">{tagKey}</th>
                <th scope="col" className="py-2 pr-4 text-right">W</th>
                <th scope="col" className="py-2 pr-4 text-right">D</th>
                <th scope="col" className="py-2 pr-4 text-right">L</th>
                <th scope="col" className="py-2 text-right">No result</th>
              </tr>
            </thead>
            <tbody>
              {groups.map((g) => (
                <tr key={g.value} className="border-b border-line font-mono tabular-nums last:border-0">
                  <td className="py-2 pr-4 font-sans text-fg">{g.value}</td>
                  <td className="py-2 pr-4 text-right text-fg">{g.wdl.w}</td>
                  <td className="py-2 pr-4 text-right text-fg">{g.wdl.d}</td>
                  <td className="py-2 pr-4 text-right text-fg">{g.wdl.l}</td>
                  <td className="py-2 text-right text-fg-muted">{g.wdl.unknown}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <>
          <ul className="mt-5 space-y-4">
            {groups.map((g) => {
              const t = known(g.wdl);
              const all = t + g.wdl.unknown;
              const lowSample = t < MIN_SAMPLE;
              return (
                <li key={g.value} className={lowSample ? 'opacity-60' : ''}>
                  <div className="flex items-baseline justify-between gap-3 text-body">
                    <span className="truncate text-fg">{g.value}</span>
                    <span className="shrink-0 font-mono tabular-nums text-fg-secondary">
                      {g.wdl.w}W {g.wdl.d}D {g.wdl.l}L
                    </span>
                  </div>
                  <Tip text={`${g.value}: won ${g.wdl.w}, drew ${g.wdl.d}, lost ${g.wdl.l}, no result ${g.wdl.unknown}`}>
                    <div className="mt-1.5 flex h-3 overflow-hidden rounded-full bg-surface-sunken ring-1 ring-inset ring-line">
                      {all > 0 &&
                        WDL_SEG.map(([k, name, cls]) =>
                          g.wdl[k] ? <div key={k} className={cls} style={{ width: `${(g.wdl[k] / all) * 100}%` }} title={`${name} ${g.wdl[k]}`} /> : null,
                        )}
                    </div>
                  </Tip>
                  <p className="mt-1 text-caption text-fg-muted">
                    n = {t} with a result{g.wdl.unknown ? ` · ${g.wdl.unknown} unknown` : ''}
                    {lowSample ? ` · Low sample (need ${MIN_SAMPLE})` : ''}
                  </p>
                </li>
              );
            })}
          </ul>
          <p className="mt-5 flex flex-wrap gap-4 text-caption text-fg-muted">
            {WDL_SEG.map(([k, name, cls]) => (
              <span key={k} className="flex items-center gap-1.5">
                <span className={`size-2 rounded-full ${cls}`} />
                {name}
              </span>
            ))}
            <span className="flex items-center gap-1.5">
              <span className="size-2 rounded-full ring-1 ring-inset ring-line-strong" />
              No result yet
            </span>
          </p>
        </>
      )}
    </section>
  );
}

function NextMatchCard({ data, tagKey, scopeLabel }) {
  const values = data.groups.map((g) => g.value);
  const [picked, setPicked] = useState(null);
  const value = values.find((v) => norm(v) === norm(picked)) ?? values[0];
  const rows = data.next_match_effect.filter((e) => norm(e.value) === norm(value));
  // pairs = tagged matches followed by another analysed match (same for every metric).
  const pairsFor = (v) => Math.max(0, ...data.next_match_effect.filter((e) => norm(e.value) === norm(v)).map((e) => e.pairs ?? e.n));
  const totalPairs = values.reduce((a, v) => a + pairsFor(v), 0);
  const headline = rows.find((e) => e.metric === 'distance' && e.n >= MIN_SAMPLE && isNum(e.change_pct));

  return (
    <section aria-labelledby="next-title" className={`${card} p-5 sm:p-6`}>
      <h2 id="next-title" className="text-title text-fg">
        Next-match effect
      </h2>
      <p className="mt-1 text-caption text-fg-muted">Average change in the following match. Correlation, not cause.</p>
      {totalPairs < MIN_PAIRS_FOR_CARD ? (
        <p className="mt-4 text-body text-fg-muted">
          Not enough matches yet. This needs at least {MIN_PAIRS_FOR_CARD} tagged matches that were followed by another analysed match, and {MIN_SAMPLE} per value before we show a change.
        </p>
      ) : (
        <>
          <div className="mt-4 flex flex-wrap gap-1.5" role="group" aria-label={`Choose a ${tagKey} value`}>
            {values.map((v) => (
              <TagChip
                key={v}
                tag={{ key: tagKey, value: v }}
                variant="selectable"
                selected={norm(v) === norm(value)}
                onToggle={() => setPicked(v)}
                count={pairsFor(v)}
                showIcon={false}
              />
            ))}
          </div>
          {headline && (
            <p className="mt-4 text-body text-fg">
              After {value.toLowerCase()} games, next-match distance is{' '}
              <span className="font-mono tabular-nums">{Math.abs(headline.change_pct).toFixed(1)}%</span>{' '}
              {headline.change_pct < 0 ? 'lower' : 'higher'} than {scopeLabel === 'Squad' ? 'your squad’s' : 'this player’s'} average (n = {headline.n}).
            </p>
          )}
          <div className="mt-4 overflow-x-auto" tabIndex={0} role="region" aria-label="Insights table">
            <p className="sticky left-0 mb-1 flex items-center gap-1 text-caption text-fg-muted sm:hidden" aria-hidden="true">
              Scroll sideways for all columns <span>→</span>
            </p>
            <table className="min-w-full whitespace-nowrap text-body">
              <thead className="border-b border-line text-left text-label uppercase text-fg-muted">
                <tr>
                  <th scope="col" className="py-2 pr-4">Metric</th>
                  <th scope="col" className="py-2 pr-4 text-right">Baseline</th>
                  <th scope="col" className="py-2 pr-4 text-right">Next match</th>
                  <th scope="col" className="py-2 pr-4 text-right">Δ</th>
                  <th scope="col" className="py-2 text-right">n</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(INSIGHT_METRICS).map(([key, def]) => {
                  const e = rows.find((r) => r.metric === key);
                  const enough = e && e.n >= MIN_SAMPLE && !e.low_sample && isNum(e.next) && isNum(e.baseline);
                  // Short units keep the table inside the card; the Δ cell's title has the full change.
                  const unit = key === 'workload' ? ' / 3' : key === 'sprints' ? '' : unitOf(def);
                  const diff = enough ? e.next - e.baseline : null;
                  return (
                    <tr key={key} className="border-b border-line last:border-0">
                      <td className="py-2 pr-4 text-fg">{key === 'sprints' ? 'Sprints / player' : def.short || def.label}</td>
                      <td className="py-2 pr-4 text-right font-mono tabular-nums text-fg-secondary">
                        {e && isNum(e.baseline) ? `${fmtNum(e.baseline, def.digits)}${unit}` : '\u2014'}
                      </td>
                      {enough ? (
                        <>
                          <td className="py-2 pr-4 text-right font-mono tabular-nums text-fg">{`${fmtNum(e.next, def.digits)}${unit}`}</td>
                          <td
                            className="py-2 pr-4 text-right font-mono tabular-nums text-fg-delta"
                            title={`${diff >= 0 ? '+' : '−'}${fmtNum(Math.abs(diff), def.digits)}${unit} vs baseline`}
                          >
                            {diff >= 0 ? '▲' : '▼'}{' '}
                            {isNum(e.change_pct) ? `${Math.abs(e.change_pct).toFixed(1)}%` : `${fmtNum(Math.abs(diff), def.digits)}${unit}`}
                          </td>
                        </>
                      ) : (
                        <td colSpan={2} className="whitespace-normal py-2 pr-4 text-right text-caption text-fg-muted">
                          {e && !isNum(e.baseline) && e.n === 0 ? 'No data for this metric yet' : `Not enough matches yet (need ${MIN_SAMPLE})`}
                        </td>
                      )}
                      <td className="py-2 text-right font-mono tabular-nums text-fg-secondary">{e ? e.n : 0}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}

// [[id, name], ...] across all loaded matches.
function playersOf(matches) {
  const map = new Map();
  matches.forEach((m) => normalizePlayers(m.stats).forEach((p) => map.set(String(p.player_id), p.name)));
  return [...map.entries()].sort((a, b) => a[1].localeCompare(b[1]));
}

function LoadingCards() {
  return (
    <div className="mt-8 grid grid-cols-1 gap-6 lg:grid-cols-2" aria-busy="true">
      {[0, 1].map((i) => (
        <div key={i} className={`${card} space-y-4 p-6`}>
          <Skeleton className="h-4 w-40" />
          {[0, 1, 2].map((j) => (
            <Skeleton key={j} className="h-3 w-full" />
          ))}
        </div>
      ))}
      <p className="text-caption text-fg-muted">Loading insights…</p>
    </div>
  );
}

export default function Insights() {
  const { isDemo } = useAuth();
  // base: { status: loading|ready|error, videos, sample, error }
  const [base, setBase] = useState({ status: 'loading', videos: [], sample: false, error: null });
  const [reloadKey, setReloadKey] = useState(0);
  const [tagKey, setTagKey] = useState(null);
  const [metric, setMetric] = useState('distance');
  const [scope, setScope] = useState('squad');
  const [result, setResult] = useState({ status: 'idle', data: null, error: null });
  const statsCache = useRef(new Map()); // video id -> stats array
  const serverMode = useRef('unknown'); // unknown | yes | no
  const [serverPlayers, setServerPlayers] = useState([]);
  const { availability } = useMetricDefs({ enabled: !isDemo });

  // 1) The user's videos (for tag keys and the client-side fallback).
  useEffect(() => {
    const controller = new AbortController();
    const done = (next) => !controller.signal.aborted && setBase(next);
    if (isDemo) {
      Promise.resolve().then(() => done({ status: 'ready', videos: SAMPLE_INSIGHT_MATCHES.map((m) => m.video), sample: true, error: null }));
    } else {
      listVideos({ signal: controller.signal })
        .then((videos) => done({ status: 'ready', videos, sample: false, error: null }))
        .catch((err) => {
          if (err?.kind === 'abort') return;
          if (err?.isNetwork) done({ status: 'ready', videos: SAMPLE_INSIGHT_MATCHES.map((m) => m.video), sample: true, error: err });
          else done({ status: 'error', videos: [], sample: false, error: err });
        });
    }
    return () => controller.abort();
  }, [isDemo, reloadKey]);

  const keys = useMemo(() => tagKeysOf(base.videos), [base.videos]);
  const activeKey = keys.find((k) => norm(k) === norm(tagKey)) ?? keys.find((k) => norm(k) === 'weather') ?? keys[0] ?? null;

  // 2) Insights for the chosen key/scope: server first, else client-side.
  useEffect(() => {
    if (base.status !== 'ready' || !activeKey) return undefined;
    const controller = new AbortController();
    const { signal } = controller;
    const playerId = scope === 'squad' ? null : scope;
    (async () => {
      await Promise.resolve();
      if (signal.aborted) return;
      setResult((r) => ({ ...r, status: 'loading' }));
      if (base.sample) {
        setResult({
          status: 'ready',
          data: { ...computeInsights(SAMPLE_INSIGHT_MATCHES, activeKey, { playerId }), source: 'sample', players: playersOf(SAMPLE_INSIGHT_MATCHES) },
          error: null,
        });
        return;
      }
      if (serverMode.current !== 'no') {
        try {
          const raw = await getInsights(activeKey, { playerId, signal });
          serverMode.current = 'yes';
          setResult({ status: 'ready', data: normalizeInsights(raw), error: null });
          return;
        } catch (err) {
          if (signal.aborted || err?.kind === 'abort') return;
          if (!isUnsupported(err)) {
            setResult({ status: 'error', data: null, error: err });
            return;
          }
          serverMode.current = 'no';
        }
      }
      // Client-side: stats for every finished video (cached between key changes).
      const doneVideos = base.videos.filter((v) => normalizeStatus(v.status) === 'complete').slice(0, MAX_VIDEOS);
      const missing = doneVideos.filter((v) => !statsCache.current.has(String(v.id)));
      for (let i = 0; i < missing.length; i += 4) {
        const batch = missing.slice(i, i + 4);
        const res = await Promise.allSettled(batch.map((v) => getVideoStats(v.id, { signal })));
        if (signal.aborted) return;
        res.forEach((r, j) => statsCache.current.set(String(batch[j].id), r.status === 'fulfilled' ? r.value : null));
      }
      const matches = doneVideos.map((v) => ({ video: v, stats: statsCache.current.get(String(v.id)) })).filter((m) => Array.isArray(m.stats));
      setResult({ status: 'ready', data: { ...computeInsights(matches, activeKey, { playerId }), source: 'client', players: playersOf(matches) }, error: null });
    })();
    return () => controller.abort();
  }, [base, activeKey, scope]);

  // Server mode: /api/insights has no player list, so read it from recent videos' stats.
  const serverSource = result.data?.source === 'server';
  useEffect(() => {
    if (!serverSource || base.sample) return undefined;
    const controller = new AbortController();
    const recent = base.videos.filter((v) => normalizeStatus(v.status) === 'complete').slice(0, MAX_PLAYER_LIST_VIDEOS);
    Promise.allSettled(
      recent.map((v) =>
        statsCache.current.has(String(v.id))
          ? Promise.resolve(statsCache.current.get(String(v.id)))
          : getVideoStats(v.id, { signal: controller.signal }).then((st) => (statsCache.current.set(String(v.id), st), st)),
      ),
    ).then((res) => {
      if (controller.signal.aborted) return;
      setServerPlayers(playersOf(res.filter((r) => r.status === 'fulfilled' && Array.isArray(r.value)).map((r) => ({ stats: r.value }))));
    });
    return () => controller.abort();
  }, [serverSource, base]);

  // Player list for the scope select.
  const players = result.data?.players ?? (serverSource ? serverPlayers : []);

  const scopeLabel = scope === 'squad' ? 'Squad' : players.find(([id]) => id === scope)?.[1] || 'Player';
  const data = result.data;

  return (
    <div className={`${container} py-10 sm:py-12`}>
      <header className="flex flex-col gap-6 border-b border-line pb-6 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className={label}>Match tags</p>
          <h1 className="mt-2 text-3xl font-bold tracking-tight text-fg sm:text-4xl">Insights</h1>
          <p className="mt-2 max-w-2xl text-body text-fg-muted">Compare how your team plays across conditions you’ve tagged, like weather or pitch.</p>
        </div>
        {keys.length > 0 && (
          <div className="flex flex-wrap items-end gap-4">
            <div>
              <label htmlFor="compare-by" className="mb-1.5 block text-caption font-medium text-fg-secondary">
                Compare by
              </label>
              <select id="compare-by" value={activeKey ?? ''} onChange={(e) => setTagKey(e.target.value)} className={`${input} h-10 w-44`}>
                {keys.map((k) => (
                  <option key={k} value={k}>
                    {k}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <span className="mb-1.5 block text-caption font-medium text-fg-secondary">Metric</span>
              <Segmented
                labelText="Metric"
                value={metric}
                onChange={setMetric}
                options={[
                  { key: 'speed', label: 'Top speed' },
                  { key: 'distance', label: 'Distance' },
                  { key: 'sprints', label: 'Sprints' },
                  { key: 'hsr', label: 'HSR' },
                  { key: 'workload', label: 'Workload' },
                ]}
              />
            </div>
            <div>
              <label htmlFor="scope" className="mb-1.5 block text-caption font-medium text-fg-secondary">
                Scope
              </label>
              <select id="scope" value={scope} onChange={(e) => setScope(e.target.value)} className={`${input} h-10 w-44`}>
                <option value="squad">Squad</option>
                {players.map(([id, name]) => (
                  <option key={id} value={id}>
                    {name}
                  </option>
                ))}
              </select>
            </div>
          </div>
        )}
      </header>

      {base.sample && (
        <NoticeBanner
          className="mt-6"
          action={
            !isDemo && (
              <button type="button" onClick={() => setReloadKey((k) => k + 1)} className={`${btn.secondary} h-9 shrink-0`}>
                Retry
              </button>
            )
          }
        >
          {isDemo ? 'Demo mode: these insights use made-up sample matches.' : 'Backend not reachable, showing insights from made-up sample matches.'}
        </NoticeBanner>
      )}

      {base.status === 'loading' ? (
        <LoadingCards />
      ) : base.status === 'error' ? (
        <ErrorBanner className="mt-8" title="Couldn’t load your matches" onRetry={() => setReloadKey((k) => k + 1)}>
          {base.error?.message}
        </ErrorBanner>
      ) : keys.length === 0 ? (
        <div className="mt-8">
          <EmptyState
            icon="tag"
            title="Tag your matches to unlock insights"
            hint="Add tags like Weather: Raining or Pitch: Turf to your matches, then compare distance, speed and workload across them."
            action={
              <Link to="/profile" className={btn.primary}>
                Add tags to a match
              </Link>
            }
          />
        </div>
      ) : result.status === 'error' ? (
        <ErrorBanner className="mt-8" title="Couldn’t load insights" onRetry={() => setReloadKey((k) => k + 1)}>
          {result.error?.message}
        </ErrorBanner>
      ) : !data || result.status === 'loading' ? (
        <LoadingCards />
      ) : (
        <>
          <p className="mt-6 flex items-center gap-2 text-caption text-fg-muted">
            <Icon name="chart" className="size-4" />
            {data.matchesAnalysed} analysed match{data.matchesAnalysed === 1 ? '' : 'es'}
            {data.source === 'client' ? ' · computed in your browser from your per-match stats' : data.source === 'sample' ? ' · sample data' : ''}
            {` · groups with fewer than ${MIN_SAMPLE} matches aren’t ranked`}
          </p>
          <div className="mt-4 grid grid-cols-1 gap-6 lg:grid-cols-2">
            <div className="lg:col-span-2">
              <ByCondition data={data} metric={metric} tagKey={activeKey} scopeLabel={scopeLabel} availability={availability} />
            </div>
            <NextMatchCard key={`${activeKey}-${scope}`} data={data} tagKey={activeKey} scopeLabel={scopeLabel} />
            <ResultsCard data={data} tagKey={activeKey} />
          </div>
        </>
      )}
    </div>
  );
}
