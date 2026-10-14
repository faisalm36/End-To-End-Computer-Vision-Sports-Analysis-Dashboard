// Athlete-log CSV upload (backend v0.7.0 provisional contract: POST /api/uploads/csv).
// Flow: pick file → dry-run preview (stores nothing) → confirm → stored results.
import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router';
import { useAuth } from '../auth/useAuth';
import { btn, card, container, focusRing, input, label } from '../components/classes';
import { DataQualityBadge, RiskLevelBadge, ScoreNote, WorkloadDisclaimer } from '../components/Risk';
import { ErrorBanner, Icon, Modal, NoticeBanner, Spinner } from '../components/ui';
import { deleteCsvUpload, listCsvUploads, listPlayers, uploadAthleteCsv } from '../lib/api';
import { formatBytes, formatDate } from '../lib/format';
import { WORKLOAD_DISCLAIMER } from '../lib/metrics';
import { CSV_OPTIONAL_HINTS, CSV_REQUIRED_HINT, csvErrorMessage, isScored, missingColumnsFrom } from '../lib/risk';

const isCsv = (f) => /\.csv$/i.test(f?.name || '') || f?.type === 'text/csv';

// Wide tables scroll sideways on small screens, with a visible hint.
function ScrollTable({ caption, children, minWidth = 'min-w-[34rem]' }) {
  return (
    <div>
      <p className="mb-1 flex items-center gap-1 text-caption text-fg-muted sm:hidden" aria-hidden="true">
        Scroll sideways for all columns <span>→</span>
      </p>
      <div className="overflow-x-auto rounded-lg border border-line" tabIndex={0} role="region" aria-label={caption}>
        <table className={`w-full ${minWidth} text-left text-caption`}>
          <caption className="sr-only">{caption}</caption>
          {children}
        </table>
      </div>
    </div>
  );
}

const th = 'whitespace-nowrap bg-surface-overlay/60 px-3 py-2 text-label uppercase tracking-label text-fg-muted';
const td = 'px-3 py-2 align-top text-fg-secondary';

function Summary({ r }) {
  const items = [
    ['Rows', r.rows_total, 'total'],
    ['Valid', r.rows_valid, 'valid'],
    ['With errors', r.rows_invalid, 'invalid'],
    ['Unmatched', r.rows_unmatched, 'unmatched'],
  ];
  return (
    <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4" data-csv-summary>
      {items.map(([t, v, k]) => (
        <div key={k} className="rounded-lg bg-surface-overlay/60 px-3 py-2 ring-1 ring-inset ring-line">
          <dt className="text-caption text-fg-muted">{t}</dt>
          <dd className="font-mono text-title tabular-nums text-fg" data-count={k}>
            {v}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function ResultsTable({ results, caption }) {
  if (!results.length) return <p className="text-caption text-fg-muted">No scored rows.</p>;
  return (
    <ScrollTable caption={caption}>
      <thead>
        <tr>
          <th className={th}>Row</th>
          <th className={th}>Player</th>
          <th className={th}>Date</th>
          <th className={th}>Risk</th>
          <th className={th}>Top factors / note</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-line">
        {results.map((r, i) => (
          <tr key={`${r.row}-${i}`} data-result-row={r.row}>
            <td className={`${td} font-mono`}>{r.row ?? '—'}</td>
            <td className={`${td} text-fg`}>{r.name}</td>
            <td className={`${td} whitespace-nowrap`}>{formatDate(r.date)}</td>
            <td className={td}>
              <span className="flex flex-wrap items-center gap-1.5">
                <RiskLevelBadge level={r.level} riskPercent={r.risk_percent} />
                <DataQualityBadge quality={r.data_quality} />
              </span>
            </td>
            <td className={td}>
              {!isScored(r) ? (
                <ScoreNote item={r} />
              ) : r.factors.length ? (
                r.factors.slice(0, 2).map((f, j) => (
                  <span key={j} className="mr-3 inline-block whitespace-nowrap">
                    {f.label} <span className={f.direction === 'up' ? 'text-risk-high' : 'text-risk-low'}>{f.direction === 'up' ? '▲' : '▼'}</span>
                  </span>
                ))
              ) : (
                '—'
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </ScrollTable>
  );
}

function ProblemTables({ r }) {
  return (
    <>
      {r.errors.length > 0 && (
        <section className="mt-6" data-csv-errors>
          <h3 className="text-body font-semibold text-status-danger">
            <Icon name="alert" className="mr-1.5 inline size-4 align-[-2px]" />
            {r.errors.length} validation {r.errors.length === 1 ? 'error' : 'errors'}
          </h3>
          <div className="mt-2">
            <ScrollTable caption="Validation errors">
              <thead>
                <tr>
                  <th className={th}>Row</th>
                  <th className={th}>Column</th>
                  <th className={th}>Value</th>
                  <th className={th}>Problem</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {r.errors.map((e, i) => (
                  <tr key={i} data-error-row={e.row}>
                    <td className={`${td} font-mono`}>{e.row ?? '—'}</td>
                    <td className={`${td} font-mono`}>{e.column ?? '—'}</td>
                    <td className={`${td} font-mono`}>{e.value == null || e.value === '' ? '(empty)' : String(e.value)}</td>
                    <td className={`${td} text-fg`}>{e.message}</td>
                  </tr>
                ))}
              </tbody>
            </ScrollTable>
          </div>
        </section>
      )}
      {r.unmatched.length > 0 && (
        <section className="mt-6" data-csv-unmatched>
          <h3 className="text-body font-semibold text-status-warning">
            <Icon name="users" className="mr-1.5 inline size-4 align-[-2px]" />
            {r.unmatched.length} {r.unmatched.length === 1 ? 'row doesn’t' : 'rows don’t'} match a player on your roster
          </h3>
          <ul className="mt-2 flex flex-wrap gap-2">
            {r.unmatched.map((u, i) => (
              <li key={i} className="rounded-chip bg-surface-overlay px-2.5 py-1 text-caption text-fg-secondary ring-1 ring-inset ring-line-strong">
                Row {u.row ?? '?'}: <span className="text-fg">{u.player == null || u.player === '' ? '(blank)' : String(u.player)}</span>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-caption text-fg-muted">
            Check names or jersey numbers on the{' '}
            <Link to="/players" className={`rounded underline hover:text-fg ${focusRing}`}>
              Players
            </Link>{' '}
            page.
          </p>
        </section>
      )}
    </>
  );
}

function RecentUploads({ refreshKey, disabled }) {
  const [state, setState] = useState({ kind: 'loading', items: [] });
  const [confirm, setConfirm] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (disabled) return undefined;
    const ctrl = new AbortController();
    (async () => {
      try {
        const items = await listCsvUploads({ signal: ctrl.signal });
        setState({ kind: 'ready', items });
      } catch (err) {
        if (err?.kind === 'abort') return;
        setState({ kind: 'hidden', items: [] });
      }
    })();
    return () => ctrl.abort();
  }, [refreshKey, disabled]);

  if (disabled || state.kind !== 'ready') return null;

  const doDelete = async () => {
    setBusy(true);
    setError(null);
    try {
      await deleteCsvUpload(confirm.upload_id);
      setState((s) => ({ ...s, items: s.items.filter((u) => u.upload_id !== confirm.upload_id) }));
      setConfirm(null);
    } catch (err) {
      setError(err?.status === 404 ? 'That upload no longer exists.' : err?.message || 'Couldn’t delete.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className={`${card} mt-8 p-5 sm:p-6`} aria-labelledby="recent-uploads" data-recent-uploads>
      <h2 id="recent-uploads" className="text-title text-fg">
        Recent athlete logs
      </h2>
      {!state.items.length ? (
        <p className="mt-2 text-caption text-fg-muted">No CSV uploads yet.</p>
      ) : (
        <ul className="mt-3 divide-y divide-line">
          {state.items.map((u) => (
            <li key={u.upload_id} className="flex flex-wrap items-center justify-between gap-3 py-2.5" data-upload={u.upload_id}>
              <div className="min-w-0">
                <p className="truncate text-body text-fg">{u.filename}</p>
                <p className="text-caption text-fg-muted">
                  {[u.created_at ? formatDate(u.created_at, { withTime: true }) : null, u.rows_valid != null ? `${u.rows_valid}${u.rows_total != null ? ` of ${u.rows_total}` : ''} rows stored` : null]
                    .filter(Boolean)
                    .join(' · ') || `Upload #${u.upload_id}`}
                </p>
              </div>
              <button type="button" className={`${btn.ghost} h-9 px-3 text-caption`} onClick={() => setConfirm(u)} aria-label={`Delete ${u.filename}`}>
                <Icon name="trash" className="size-4" />
                Delete
              </button>
            </li>
          ))}
        </ul>
      )}
      <Modal open={Boolean(confirm)} onClose={() => !busy && setConfirm(null)} title="Delete this athlete log?" labelledBy="delete-csv-title">
        <p className="text-body text-fg-secondary">
          This removes <span className="font-medium text-fg">{confirm?.filename}</span> and the risk scores it produced. This can’t be undone.
        </p>
        {error && (
          <p role="alert" className="mt-3 text-body text-status-danger">
            {error}
          </p>
        )}
        <div className="mt-5 flex flex-wrap justify-end gap-3">
          <button type="button" className={btn.secondary} onClick={() => setConfirm(null)} disabled={busy}>
            Cancel
          </button>
          <button type="button" className={btn.danger} onClick={doDelete} disabled={busy}>
            {busy ? 'Deleting…' : 'Delete'}
          </button>
        </div>
      </Modal>
    </section>
  );
}

export default function CsvUpload() {
  const { isDemo } = useAuth();
  const fileRef = useRef(null);
  const [teams, setTeams] = useState([]);
  const [teamId, setTeamId] = useState('');
  const [file, setFile] = useState(null);
  const [phase, setPhase] = useState('idle'); // idle | previewing | preview | saving | saved
  const [preview, setPreview] = useState(null);
  const [saved, setSaved] = useState(null);
  const [error, setError] = useState(null); // { message, missing: [] }
  const [ignoredDryRun, setIgnoredDryRun] = useState(false);
  const [listKey, setListKey] = useState(0);
  const runId = useRef(0);

  useEffect(() => {
    if (isDemo) return undefined;
    const ctrl = new AbortController();
    (async () => {
      try {
        const players = await listPlayers({ signal: ctrl.signal });
        const map = new Map();
        for (const p of players) if (p.team?.team_id != null) map.set(String(p.team.team_id), p.team.team_name || `Team ${p.team.team_id}`);
        setTeams([...map.entries()].map(([id, name]) => ({ id, name })).sort((a, b) => a.name.localeCompare(b.name)));
      } catch {
        /* team list is optional */
      }
    })();
    return () => ctrl.abort();
  }, [isDemo]);

  const runPreview = useCallback(async (f, team) => {
    const id = ++runId.current;
    setPhase('previewing');
    setError(null);
    setPreview(null);
    setSaved(null);
    setIgnoredDryRun(false);
    try {
      const r = await uploadAthleteCsv({ file: f, team_id: team || undefined, dry_run: true });
      if (id !== runId.current) return;
      if (!r.dry_run && r.upload_id != null) {
        // Server ignored the preview flag and stored the file: say so plainly.
        setIgnoredDryRun(true);
        setSaved(r);
        setPhase('saved');
        setListKey((k) => k + 1);
        return;
      }
      setPreview(r);
      setPhase('preview');
    } catch (err) {
      if (id !== runId.current) return;
      setError({ message: csvErrorMessage(err), missing: missingColumnsFrom(err), status: err?.status });
      setPhase('idle');
    }
  }, []);

  const onPick = (e) => {
    const f = e.target.files?.[0] || null;
    setFile(f);
    setPreview(null);
    setSaved(null);
    if (!f) return;
    if (!isCsv(f)) {
      setError({ message: 'That file isn’t a CSV. Export the athlete log as .csv and try again.', missing: [] });
      setPhase('idle');
      return;
    }
    if (f.size === 0) {
      setError({ message: 'That file is empty.', missing: [] });
      setPhase('idle');
      return;
    }
    runPreview(f, teamId);
  };

  const onTeam = (e) => {
    setTeamId(e.target.value);
    if (file && isCsv(file) && file.size > 0) runPreview(file, e.target.value);
  };

  const confirmSave = async () => {
    const id = ++runId.current;
    setPhase('saving');
    setError(null);
    try {
      const r = await uploadAthleteCsv({ file, team_id: teamId || undefined, dry_run: false });
      if (id !== runId.current) return;
      setSaved(r);
      setPhase('saved');
      setListKey((k) => k + 1);
    } catch (err) {
      if (id !== runId.current) return;
      setError({ message: csvErrorMessage(err), missing: missingColumnsFrom(err), status: err?.status });
      setPhase('preview');
    }
  };

  const reset = () => {
    runId.current++;
    setFile(null);
    setPreview(null);
    setSaved(null);
    setError(null);
    setIgnoredDryRun(false);
    setPhase('idle');
    if (fileRef.current) fileRef.current.value = '';
  };

  const busy = phase === 'previewing' || phase === 'saving';

  return (
    <div className={`${container} py-8 sm:py-10`}>
      <Link to="/roster" className={`rounded text-body text-fg-muted hover:text-fg ${focusRing}`}>
        ← Roster risk
      </Link>
      <p className={`${label} mt-4`}>Workload</p>
      <h1 className="mt-1 text-3xl font-bold tracking-tight text-fg">Upload athlete log</h1>
      <p className="mt-1 max-w-2xl text-body text-fg-muted">
        Add GPS and heart-rate logs as a CSV. You’ll see a preview first; nothing is stored until you confirm. <strong className="font-semibold text-fg-secondary">{WORKLOAD_DISCLAIMER}.</strong>
      </p>

      {isDemo && <NoticeBanner className="mt-6">Demo mode: CSV upload needs a running server. Log in to upload athlete logs.</NoticeBanner>}

      <section className={`${card} mt-6 p-5 sm:p-6`} aria-labelledby="csv-pick">
        <h2 id="csv-pick" className="text-title text-fg">
          1. Choose a CSV file
        </h2>
        <div className="mt-2 text-caption text-fg-muted" data-columns-hint>
          <p>
            <span className="font-medium text-fg-secondary">Required columns:</span> {CSV_REQUIRED_HINT}.
          </p>
          <ul className="mt-1.5 space-y-0.5" data-optional-columns>
            {CSV_OPTIONAL_HINTS.map((c) => (
              <li key={c.name} className="text-caption text-fg-muted">
                <span className="font-mono text-fg-secondary">{c.name}</span> — {c.hint}
              </li>
            ))}
          </ul>
          <p className="mt-1.5 text-caption text-fg-muted">Headers are matched ignoring case and punctuation (spaces, underscores, etc.).</p>
        </div>
        <div className="mt-4 grid gap-4 sm:grid-cols-[minmax(0,1fr)_14rem] sm:items-end">
          <div>
            <label htmlFor="csv-file" className="mb-1.5 block text-body font-medium text-fg-secondary">
              Athlete log (.csv)
            </label>
            <input
              ref={fileRef}
              id="csv-file"
              type="file"
              accept=".csv,text/csv"
              disabled={isDemo || busy}
              onChange={onPick}
              className={`block w-full min-w-0 text-body text-fg-secondary file:mr-3 file:h-10 file:rounded-control file:border-0 file:bg-surface-overlay file:px-4 file:font-semibold file:text-fg file:ring-1 file:ring-inset file:ring-line-strong hover:file:bg-line-strong disabled:opacity-60 ${focusRing}`}
            />
            {file && (
              <p className="mt-1.5 truncate text-caption text-fg-muted">
                {file.name} · {formatBytes(file.size)}
              </p>
            )}
          </div>
          {teams.length > 0 && (
            <div>
              <label htmlFor="csv-team" className="mb-1.5 block text-body font-medium text-fg-secondary">
                Team (optional)
              </label>
              <select id="csv-team" className={input} value={teamId} onChange={onTeam} disabled={busy}>
                <option value="">Match any team</option>
                {teams.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>
      </section>

      {phase === 'previewing' && (
        <p className="mt-6 flex items-center gap-2 text-body text-fg-secondary" role="status">
          <Spinner /> Checking the file (nothing is stored yet)…
        </p>
      )}

      {error && (
        <ErrorBanner className="mt-6" title={error.missing.length ? 'Missing required columns' : 'Couldn’t use this file'}>
          <p>{error.message}</p>
          {error.missing.length > 0 && (
            <ul className="mt-2 flex flex-wrap gap-2" data-missing-columns>
              {error.missing.map((c) => (
                <li key={c} className="rounded-chip bg-surface-overlay px-2.5 py-0.5 font-mono text-caption text-fg ring-1 ring-inset ring-risk-high-ring">
                  {c}
                </li>
              ))}
            </ul>
          )}
        </ErrorBanner>
      )}

      {preview && phase !== 'saved' && (
        <section className={`${card} mt-6 p-5 sm:p-6`} aria-labelledby="csv-preview" data-csv-preview>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 id="csv-preview" className="text-title text-fg">
                2. Check the preview
              </h2>
              <p className="mt-0.5 text-caption text-fg-muted">Preview only. Nothing has been stored.</p>
            </div>
            {preview.columns_detected.length > 0 && (
              <p className="max-w-full text-caption text-fg-muted">
                Columns found: <span className="font-mono text-fg-secondary">{preview.columns_detected.join(', ')}</span>
              </p>
            )}
          </div>
          <div className="mt-4">
            <Summary r={preview} />
          </div>
          <ProblemTables r={preview} />
          <section className="mt-6">
            <h3 className="text-body font-semibold text-fg">Scores this file would produce</h3>
            <div className="mt-2">
              <ResultsTable results={preview.results} caption="Preview of scored rows" />
            </div>
          </section>
          <div className="mt-6 flex flex-col gap-3 border-t border-line pt-5 sm:flex-row sm:items-center">
            <button type="button" className={btn.primary} onClick={confirmSave} disabled={busy || preview.rows_valid === 0}>
              {phase === 'saving' ? (
                <>
                  <Spinner /> Saving…
                </>
              ) : (
                `3. Save ${preview.rows_valid} valid ${preview.rows_valid === 1 ? 'row' : 'rows'}`
              )}
            </button>
            <button type="button" className={btn.secondary} onClick={reset} disabled={phase === 'saving'}>
              Choose a different file
            </button>
            {preview.rows_valid === 0 && <p className="text-caption text-status-danger">No valid rows to save. Fix the file and try again.</p>}
            {preview.rows_valid > 0 && preview.rows_invalid + preview.rows_unmatched > 0 && (
              <p className="text-caption text-fg-muted">
                {preview.rows_invalid + preview.rows_unmatched} {preview.rows_invalid + preview.rows_unmatched === 1 ? 'row has' : 'rows have'} problems listed above.
              </p>
            )}
          </div>
          <WorkloadDisclaimer className="mt-4" />
        </section>
      )}

      {saved && phase === 'saved' && (
        <section className={`${card} mt-6 p-5 sm:p-6`} aria-labelledby="csv-saved" data-csv-saved>
          {ignoredDryRun && <NoticeBanner className="mb-4">The server stored this file straight away instead of showing a preview first.</NoticeBanner>}
          <h2 id="csv-saved" className="flex items-center gap-2 text-title text-fg">
            <Icon name="check" className="size-5 text-status-success" />
            Athlete log saved
          </h2>
          <p className="mt-1 text-caption text-fg-muted">
            {saved.filename || file?.name}
            {saved.upload_id != null && ` · upload #${saved.upload_id}`}
          </p>
          <div className="mt-4">
            <Summary r={saved} />
          </div>
          <ProblemTables r={saved} />
          <section className="mt-6">
            <h3 className="text-body font-semibold text-fg">Stored scores</h3>
            <div className="mt-2">
              <ResultsTable results={saved.results} caption="Stored scores" />
            </div>
          </section>
          <div className="mt-6 flex flex-col gap-3 sm:flex-row">
            <Link to="/roster" className={btn.primary}>
              View roster risk
            </Link>
            <button type="button" className={btn.secondary} onClick={reset}>
              Upload another file
            </button>
          </div>
          <WorkloadDisclaimer className="mt-4" />
        </section>
      )}

      <RecentUploads refreshKey={listKey} disabled={isDemo} />
    </div>
  );
}
