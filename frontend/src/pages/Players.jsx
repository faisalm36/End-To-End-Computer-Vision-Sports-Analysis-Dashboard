import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router';
import { useAuth } from '../auth/useAuth';
import { btn, card, container, focusRing, input, label } from '../components/classes';
import { Field } from '../components/FormField';
import { ErrorBanner, NoticeBanner, Skeleton, Toast } from '../components/ui';
import { DOMINANT_FEET, listPlayers, patchPlayer } from '../lib/api';
import { SAMPLE_ROSTER } from '../lib/sampleData';

function displayName(p) {
  return `${p.first_name || ''} ${p.last_name || ''}`.trim() || `Player ${p.player_id}`;
}

function groupByTeam(players) {
  const map = new Map();
  for (const p of players) {
    const tid = p.team_id ?? p.team?.team_id ?? 'unknown';
    const name = p.team?.team_name || (tid === 'unknown' ? 'No team' : `Team ${tid}`);
    if (!map.has(tid)) map.set(tid, { team_id: tid, team_name: name, league: p.team?.league ?? null, players: [] });
    map.get(tid).players.push(p);
  }
  // Contract order is player_id ascending; within a team also sort jersey nulls last, then last_name.
  for (const g of map.values()) {
    g.players.sort((a, b) => {
      const ja = a.jersey_number;
      const jb = b.jersey_number;
      if (ja == null && jb != null) return 1;
      if (ja != null && jb == null) return -1;
      if (ja != null && jb != null && ja !== jb) return ja - jb;
      const ln = String(a.last_name || '').localeCompare(String(b.last_name || ''));
      if (ln) return ln;
      return String(a.first_name || '').localeCompare(String(b.first_name || ''));
    });
  }
  return [...map.values()].sort((a, b) => String(a.team_name).localeCompare(String(b.team_name)));
}

function EditDrawer({ player, onClose, onSaved }) {
  const [form, setForm] = useState({
    first_name: player.first_name || '',
    last_name: player.last_name || '',
    jersey_number: player.jersey_number == null ? '' : String(player.jersey_number),
    position: player.position || '',
    dominant_foot: player.dominant_foot || '',
    contract_end_date: player.contract_end_date || '',
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const save = async (e) => {
    e.preventDefault();
    setError(null);
    const body = {};
    const first = form.first_name.trim();
    if (!first) {
      setError('First name can’t be empty.');
      return;
    }
    if (first !== (player.first_name || '')) body.first_name = first;
    const last = form.last_name.trim();
    if (last !== (player.last_name || '')) body.last_name = last;
    const jRaw = form.jersey_number.trim();
    let jersey = null;
    if (jRaw !== '') {
      jersey = Number(jRaw);
      if (!Number.isInteger(jersey) || jersey < 0 || jersey > 99) {
        setError('Jersey number must be a whole number from 0 to 99, or empty for none.');
        return;
      }
    }
    if (jersey !== player.jersey_number) body.jersey_number = jersey;
    const pos = form.position.trim() || null;
    if (pos !== (player.position || null)) body.position = pos;
    const foot = form.dominant_foot || null;
    if (foot !== (player.dominant_foot || null)) body.dominant_foot = foot;
    const end = form.contract_end_date || null;
    if (end !== (player.contract_end_date || null)) body.contract_end_date = end;
    if (!Object.keys(body).length) {
      onClose();
      return;
    }
    setBusy(true);
    try {
      const updated = await patchPlayer(player.player_id, body);
      onSaved(updated);
      onClose();
    } catch (err) {
      setError(err?.message || 'Couldn’t save.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-40 flex items-end justify-center sm:items-center" role="dialog" aria-modal="true" aria-labelledby="edit-player-title">
      <button type="button" className="absolute inset-0 bg-black/60" aria-label="Close" onClick={onClose} />
      <form onSubmit={save} className={`relative z-10 m-0 w-full max-w-lg rounded-t-2xl border border-line bg-surface-raised p-5 shadow-panel sm:m-4 sm:rounded-2xl`} data-edit-player>
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className={label}>Edit player</p>
            <h2 id="edit-player-title" className="mt-1 text-title text-fg">
              {displayName(player)}
            </h2>
            {player.team?.team_name && <p className="mt-0.5 text-caption text-fg-muted">{player.team.team_name}</p>}
          </div>
          <button type="button" className={`${btn.ghost} h-9 px-2`} onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <Field label="First name" required value={form.first_name} onChange={set('first_name')} autoComplete="off" maxLength={50} />
          <Field label="Last name" value={form.last_name} onChange={set('last_name')} autoComplete="off" maxLength={50} />
          <Field
            label="Jersey number"
            inputMode="numeric"
            placeholder="None"
            value={form.jersey_number}
            onChange={set('jersey_number')}
            hint="0–99, or leave empty for no number"
          />
          <Field label="Position" value={form.position} onChange={set('position')} placeholder="e.g. MF" maxLength={30} />
          <div>
            <label htmlFor="edit-foot" className="mb-1.5 block text-body font-medium text-fg-secondary">
              Dominant foot
            </label>
            <select id="edit-foot" value={form.dominant_foot} onChange={set('dominant_foot')} className={input}>
              <option value="">Not set</option>
              {DOMINANT_FEET.map((f) => (
                <option key={f} value={f}>
                  {f}
                </option>
              ))}
            </select>
          </div>
          <Field label="Contract end" type="date" value={form.contract_end_date} onChange={set('contract_end_date')} />
        </div>
        {error && (
          <p role="alert" className="mt-3 rounded-lg border border-risk-high-ring bg-status-danger-bg px-3 py-2 text-body text-status-danger" data-save-error>
            {error}
          </p>
        )}
        <div className="mt-5 flex flex-wrap gap-3">
          <button type="submit" className={`${btn.primary} h-10 px-5`} disabled={busy}>
            {busy ? 'Saving…' : 'Save'}
          </button>
          <button type="button" className={`${btn.secondary} h-10`} onClick={onClose} disabled={busy}>
            Cancel
          </button>
        </div>
      </form>
    </div>
  );
}

function Loading() {
  return (
    <div className={`${container} py-8`} aria-busy="true">
      <Skeleton className="h-4 w-32" />
      <Skeleton className="mt-3 h-9 w-56" />
      <div className={`${card} mt-8 space-y-3 p-5`}>
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    </div>
  );
}

export default function Players() {
  const { isDemo } = useAuth();
  const [state, setState] = useState({ kind: 'loading', list: [], error: null });
  const [editing, setEditing] = useState(null);
  const [toast, setToast] = useState(false);
  const [filter, setFilter] = useState('');
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (isDemo) {
        await Promise.resolve();
        if (!cancelled) setState({ kind: 'ready', list: SAMPLE_ROSTER, error: null, sample: true });
        return;
      }
      try {
        const list = await listPlayers();
        if (!cancelled) setState({ kind: 'ready', list, error: null, sample: false });
      } catch (err) {
        if (cancelled) return;
        if (err?.status === 404 || err?.status === 405 || err?.status === 501 || err?.status === 503) {
          setState({ kind: 'unavailable', list: [], error: err, sample: false });
        } else {
          setState({ kind: 'error', list: [], error: err, sample: false });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [isDemo, reload]);

  const groups = useMemo(() => groupByTeam(state.list), [state.list]);
  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return groups;
    return groups
      .map((g) => ({
        ...g,
        players: g.players.filter((p) => {
          const hay = `${p.first_name} ${p.last_name} ${p.jersey_number ?? ''} ${p.position ?? ''} ${g.team_name}`.toLowerCase();
          return hay.includes(q);
        }),
      }))
      .filter((g) => g.players.length);
  }, [groups, filter]);

  const onSaved = (updated) => {
    setState((s) => ({ ...s, list: s.list.map((p) => (String(p.player_id) === String(updated.player_id) ? { ...p, ...updated, team: updated.team || p.team } : p)) }));
    setToast(true);
  };

  if (state.kind === 'loading') return <Loading />;

  if (state.kind === 'unavailable') {
    return (
      <div className={`${container} py-10`} data-unavailable>
        <Link to="/dashboard" className={`rounded text-body text-fg-muted hover:text-fg ${focusRing}`}>
          ← Back to dashboard
        </Link>
        <h1 className="mt-4 text-3xl font-bold tracking-tight text-fg">Players</h1>
        <div className={`${card} mt-8 p-5 sm:p-6`}>
          <h2 className="text-title text-fg">Player roster isn’t available on this server yet</h2>
          <p className="mt-1 text-body text-fg-muted">
            {state.error?.status === 503
              ? `The server needs a database update (${state.error.message}).`
              : 'This backend doesn’t have the Players endpoints yet (needs v0.6.0). Your match results still work as before.'}
          </p>
        </div>
      </div>
    );
  }

  if (state.kind === 'error') {
    return (
      <div className={`${container} py-10`}>
        <h1 className="text-3xl font-bold tracking-tight text-fg">Players</h1>
        <ErrorBanner className="mt-8" title="Couldn’t load players" onRetry={() => setReload((k) => k + 1)}>
          {state.error?.message}
        </ErrorBanner>
      </div>
    );
  }

  return (
    <div className={`${container} py-8 sm:py-10`}>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className={label}>Squad</p>
          <h1 className="mt-1 text-3xl font-bold tracking-tight text-fg">Players</h1>
          <p className="mt-1 max-w-2xl text-body text-fg-muted">Your roster by team. Edit names, jersey numbers, position, dominant foot and contract end. Match-specific jersey overrides still live on each video’s results.</p>
        </div>
        <Field
          label="Search"
          className="w-full sm:w-64"
          placeholder="Name, number, team…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          aria-label="Search players"
        />
      </div>

      {state.sample && (
        <NoticeBanner className="mt-6">Demo mode: showing sample players. Changes aren’t saved to a server.</NoticeBanner>
      )}

      {!filtered.length ? (
        <div className={`${card} mt-8 p-6`}>
          <p className="text-body text-fg-secondary">{filter ? 'No players match that search.' : 'No players yet. Upload a match and the pipeline will create placeholders you can edit here.'}</p>
          {!filter && (
            <Link to="/upload" className={`${btn.primary} mt-4 inline-flex h-10`}>
              Upload a match
            </Link>
          )}
        </div>
      ) : (
        <div className="mt-8 space-y-8">
          {filtered.map((g) => (
            <section key={g.team_id} aria-labelledby={`team-${g.team_id}`} className={card} data-team={g.team_id}>
              <div className="border-b border-line px-4 py-3 sm:px-5">
                <h2 id={`team-${g.team_id}`} className="text-title text-fg">
                  {g.team_name}
                </h2>
                {g.league && <p className="text-caption text-fg-muted">{g.league}</p>}
              </div>
              {/* Mobile cards */}
              <ul className="divide-y divide-line sm:hidden">
                {g.players.map((p) => (
                  <li key={p.player_id} className="px-4 py-3">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="text-body font-medium text-fg">
                          <span className="font-mono text-fg-muted">{p.jersey_number != null ? `#${p.jersey_number}` : '—'}</span>{' '}
                          {displayName(p)}
                        </p>
                        <p className="mt-0.5 text-caption text-fg-muted">
                          {[p.position, p.dominant_foot, p.contract_end_date].filter(Boolean).join(' · ') || 'No extras yet'}
                        </p>
                      </div>
                      {!state.sample && (
                        <button type="button" className={`${btn.secondary} h-9 shrink-0`} onClick={() => setEditing(p)}>
                          Edit
                        </button>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
              {/* Desktop table */}
              <p className="hidden items-center gap-1 border-b border-line px-4 py-1.5 text-caption text-fg-muted sm:flex lg:hidden" aria-hidden="true">
                Scroll sideways for all columns <span>→</span>
              </p>
              <div className="hidden overflow-x-auto sm:block">
                <table className="w-full min-w-[640px] text-left text-body">
                  <thead>
                    <tr className="border-b border-line text-caption text-fg-muted">
                      <th scope="col" className="px-5 py-2.5 font-medium">
                        #
                      </th>
                      <th scope="col" className="px-3 py-2.5 font-medium">
                        Name
                      </th>
                      <th scope="col" className="px-3 py-2.5 font-medium">
                        Position
                      </th>
                      <th scope="col" className="px-3 py-2.5 font-medium">
                        Foot
                      </th>
                      <th scope="col" className="px-3 py-2.5 font-medium">
                        Contract end
                      </th>
                      <th scope="col" className="px-5 py-2.5 font-medium">
                        <span className="sr-only">Actions</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {g.players.map((p) => (
                      <tr key={p.player_id} className="border-b border-line/60 last:border-0" data-player={p.player_id}>
                        <td className="px-5 py-3 font-mono text-fg-secondary">{p.jersey_number != null ? p.jersey_number : '—'}</td>
                        <td className="px-3 py-3 font-medium text-fg">{displayName(p)}</td>
                        <td className="px-3 py-3 text-fg-secondary">{p.position || '—'}</td>
                        <td className="px-3 py-3 text-fg-secondary">{p.dominant_foot || '—'}</td>
                        <td className="px-3 py-3 font-mono text-fg-secondary">{p.contract_end_date || '—'}</td>
                        <td className="px-5 py-3 text-right">
                          {!state.sample && (
                            <button type="button" className={`${btn.ghost} h-9`} onClick={() => setEditing(p)}>
                              Edit
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          ))}
        </div>
      )}

      {editing && !state.sample && <EditDrawer player={editing} onClose={() => setEditing(null)} onSaved={onSaved} />}
      {toast && <Toast onClose={() => setToast(false)}>Player saved.</Toast>}
    </div>
  );
}
