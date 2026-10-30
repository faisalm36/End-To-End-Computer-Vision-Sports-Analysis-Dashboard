// Player injury-risk detail (rir-1.0): score + band, trend chart, factor breakdown, injury history entry.
// Screening/education index only, not medical advice.
import { useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router';
import { btn, card, container, focusRing, input, label } from '../components/classes';
import { BandChip, Delta, FactorBreakdown, InjuryDisclaimer, InjuryForm, InjuryList, SurfaceToggle, TrendChart } from '../components/InjuryRisk';
import { ErrorBanner, Modal, Skeleton } from '../components/ui';
import { createInjury, deleteInjury, updateInjury, useInjuries, usePlayerInjuryRisk } from '../lib/injuryRisk';

export default function PlayerInjuryRisk() {
  const { id } = useParams();
  const [sp] = useSearchParams();
  const [surface, setSurface] = useState(sp.get('surface') === 'turf' ? 'turf' : 'grass');
  const [nextDate, setNextDate] = useState(sp.get('date') || '');
  const [minDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [modal, setModal] = useState(sp.get('add') ? { mode: 'add' } : null);
  const risk = usePlayerInjuryRisk(id, { next_surface: surface, next_date: nextDate || undefined });
  const injuries = useInjuries(id);
  const d = risk.data;
  const refresh = () => {
    risk.reload();
    injuries.reload();
  };
  const save = async (body) => {
    if (modal?.injury) await updateInjury(id, modal.injury.injury_id, body);
    else await createInjury(id, body);
    setModal(null);
    refresh();
  };
  const remove = async (i) => {
    if (!window.confirm(`Delete the ${i.body_part} injury from ${i.injury_date}?`)) return;
    await deleteInjury(id, i.injury_id);
    refresh();
  };

  return (
    <div className={`${container} py-8`}>
      <Link to="/roster/risk" className={`text-body text-fg-muted hover:text-fg ${focusRing} rounded`}>← Roster injury risk</Link>
      {risk.error ? (
        <ErrorBanner className="mt-4" onRetry={risk.reload} title="Couldn’t load this player’s injury risk">{risk.error.message}</ErrorBanner>
      ) : !d ? (
        <Skeleton className="mt-4 h-40" />
      ) : (
        <>
          <header className="mt-3 flex flex-wrap items-end justify-between gap-4">
            <div>
              <p className={label}>Player injury risk · {d.current.model_version}</p>
              <h1 className="mt-1 text-headline font-semibold text-fg">
                {d.player.number != null && <span className="font-mono text-fg-muted">#{d.player.number} </span>}
                {d.player.name}
              </h1>
            </div>
            <button type="button" className={btn.primary} onClick={() => setModal({ mode: 'add' })}>Add injury history</button>
          </header>
          <InjuryDisclaimer className="mt-4" />

          {!d.has_injury_history && (
            <div className={`${card} mt-4 p-4 text-body text-fg-secondary`}>
              No injury history yet. Add past injuries (what, when and how long you were out) so the score reflects your real history.
            </div>
          )}

          <section className="mt-5 grid gap-4 md:grid-cols-3">
            <div className={`${card} p-5`}>
              <p className={label}>Current</p>
              <p className="mt-2 font-mono text-kpi font-semibold tabular-nums text-fg">{Math.round(d.current.score)}</p>
              <BandChip className="mt-2" band={d.current.band} status={d.current.status} />
              <p className="mt-2 text-caption capitalize text-fg-muted">Confidence: {d.confidence}</p>
            </div>
            <div className={`${card} p-5 md:col-span-2`}>
              <div className="flex flex-wrap items-end gap-4">
                <div>
                  <span className={label}>Next match surface</span>
                  <div className="mt-1"><SurfaceToggle value={surface} onChange={setSurface} idPrefix="player-surface" /></div>
                </div>
                <label className="block">
                  <span className={label}>Next match date</span>
                  <input type="date" min={minDate} value={nextDate} onChange={(e) => setNextDate(e.target.value)} className={`${input} mt-1 w-44`} />
                </label>
              </div>
              <div className="mt-4 flex flex-wrap items-center gap-3">
                <span className="text-body text-fg-secondary">Projected</span>
                <span className="font-mono text-3xl font-semibold tabular-nums text-fg">{Math.round(d.projection.score)}</span>
                <BandChip band={d.projection.band} status={d.projection.status} />
                <Delta value={Math.round((d.projection.score - d.current.score) * 10) / 10} />
              </div>
            </div>
          </section>

          <section className={`${card} mt-4 p-5`}>
            <h2 className="text-title font-semibold text-fg">Trend</h2>
            <div className="mt-3"><TrendChart previous={d.previous} projection={d.projection} /></div>
          </section>

          <section className="mt-4 grid gap-4 lg:grid-cols-2">
            <div className={`${card} p-5`}>
              <h2 className="text-title font-semibold text-fg">What drives the projected score</h2>
              <div className="mt-3"><FactorBreakdown factors={d.projection.factors} /></div>
            </div>
            <div className="space-y-3">
              <h2 className="text-title font-semibold text-fg">Injury history</h2>
              {injuries.error ? <ErrorBanner onRetry={injuries.reload}>{injuries.error.message}</ErrorBanner> : (
                <InjuryList items={injuries.data || []} onEdit={(i) => setModal({ mode: 'edit', injury: i })} onDelete={remove} />
              )}
            </div>
          </section>
        </>
      )}
      <Modal open={Boolean(modal)} onClose={() => setModal(null)} title={modal?.injury ? 'Edit injury' : 'Add injury history'}>
        {modal && <InjuryForm initial={modal.injury} onSubmit={save} onCancel={() => setModal(null)} />}
      </Modal>
    </div>
  );
}
