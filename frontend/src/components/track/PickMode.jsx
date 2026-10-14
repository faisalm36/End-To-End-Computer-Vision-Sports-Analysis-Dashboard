import { useCallback, useEffect, useRef, useState } from 'react';
import { frameSrc } from '../../lib/api';
import { formatTime, frameToTime, seekTimeForFrame, timeToFrame } from '../../lib/tracking';
import { btn, card, focusRing, label } from '../classes';
import { Spinner } from '../ui';
import { useContentRect } from './hooks';
import { CropThumb } from './parts';

// No confident shirt number -> 'Unknown player' (plus team if known), never a guessed number.
const nameOf = (p) => (p.jersey_number != null ? `#${p.jersey_number}` : `Unknown player${p.team ? ` (Team ${p.team})` : ''}`);
const classNote = (p) => (p.cls === 'referee' ? 'Referee' : p.cls === 'goalkeeper' ? 'Goalkeeper' : p.team ? `Team ${p.team}` : null);

// Pick mode (UI/UX spec §1): scrub to a frame, see that frame's detections as boxes,
// click (or Tab/arrows + Enter) to select, confirm with "Track this player".
// Or pick by shirt number from the stats rows.
export default function PickMode({ fps, frameCount, width, height, sourceUrl, loadDetections, roster = [], initialFrame = null, onStart, starting = false, startError = null }) {
  const [frame, setFrame] = useState(initialFrame ?? 0);
  // Detections result for `det.frame`; while it differs from `frame` we're loading.
  const [detState, setDet] = useState({ frame: null, status: 'loading', data: null, error: null });
  const [selected, setSelected] = useState(null); // {kind:'box', det} | {kind:'jersey', row}
  const [showRefs, setShowRefs] = useState(true);
  const [team, setTeam] = useState('');
  const [playing, setPlaying] = useState(false);
  const [mediaSize, setMediaSize] = useState({ w: width, h: height });
  const boxRef = useRef(null);
  const videoRef = useRef(null);
  const listRef = useRef(null);
  const probed = useRef(initialFrame != null);
  const rect = useContentRect(boxRef, mediaSize.w || 16, mediaSize.h || 9);
  const n = Math.max(1, frameCount || 1);

  // Load detections for the paused frame (debounced while scrubbing). The first time,
  // probe forward for the first frame that has detections (spec: default frame).
  useEffect(() => {
    if (playing) return undefined;
    const ac = new AbortController();
    const timer = setTimeout(async () => {
      try {
        let f = frame;
        let data = await loadDetections(f, { signal: ac.signal });
        if (!probed.current) {
          probed.current = true;
          const stepF = Math.max(1, Math.round(n / 10));
          for (let i = 1; !data.players.length && i < 10 && f + stepF < n; i++) {
            f += stepF;
            data = await loadDetections(f, { signal: ac.signal });
          }
          if (f !== frame) {
            if (videoRef.current) videoRef.current.currentTime = seekTimeForFrame(f, fps);
            setFrame(f);
          }
        }
        if (ac.signal.aborted) return;
        if (data.width && data.height) setMediaSize({ w: data.width, h: data.height });
        setDet({ frame: f, status: 'ready', data, error: null });
      } catch (err) {
        if (ac.signal.aborted || err?.name === 'AbortError') return;
        setDet({ frame, status: 'error', data: null, error: err });
      }
    }, 150);
    return () => {
      clearTimeout(timer);
      ac.abort();
    };
  }, [frame, playing, loadDetections, n, fps]);

  const det = detState.frame === frame ? detState : { frame, status: 'loading', data: null, error: null };

  const seek = (f) => {
    const v = videoRef.current;
    const target = Math.max(0, Math.min(n - 1, f));
    if (v) {
      v.pause();
      v.currentTime = seekTimeForFrame(target, fps);
    }
    setFrame(target);
    setSelected((s) => (s?.kind === 'box' ? null : s));
  };
  const togglePlay = () => {
    const v = videoRef.current;
    if (!v) return;
    if (v.paused) {
      setSelected((s) => (s?.kind === 'box' ? null : s));
      v.play?.()?.catch?.(() => {});
    } else v.pause();
  };

  const players = (det.data?.players || []).filter((p) => showRefs || p.cls !== 'referee');
  const stillSrc = det.status === 'ready' && !playing && det.data?.frame_url ? frameSrc(det.data.frame_url, det.data.frame ?? frame) : null;
  const cancel = useCallback(() => setSelected(null), []);

  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && selected && cancel();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [selected, cancel]);

  // Arrow keys cycle through the boxes (Tab works too: each box is a button).
  const onBoxesKey = (e) => {
    if (!['ArrowRight', 'ArrowDown', 'ArrowLeft', 'ArrowUp'].includes(e.key)) return;
    const items = [...(listRef.current?.querySelectorAll('[data-det]') || [])];
    if (!items.length) return;
    e.preventDefault();
    const i = items.indexOf(document.activeElement);
    const d = e.key === 'ArrowRight' || e.key === 'ArrowDown' ? 1 : -1;
    items[(i + d + items.length) % items.length].focus();
  };

  const start = () => {
    if (!selected) return;
    if (selected.kind === 'box') {
      const p = selected.det;
      onStart({ frame: det.data?.frame ?? frame, bbox: p.bbox, player_id: p.player_id ?? undefined, jersey_number: p.jersey_number ?? undefined, team: p.team ?? undefined });
    } else {
      const r = selected.row;
      onStart({ player_id: r.player_id ?? undefined, jersey_number: r.jersey_number ?? undefined, team: team || undefined });
    }
  };

  const selDet = selected?.kind === 'box' ? selected.det : null;
  const selLabel = selected ? (selected.kind === 'box' ? nameOf(selected.det) : selected.row.jersey_number != null ? `#${selected.row.jersey_number}` : selected.row.name) : '';
  const t = frameToTime(frame, fps);

  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <div className="min-w-0 lg:col-span-2">
        <div className={`${card} overflow-hidden p-0`}>
          <div ref={boxRef} className="relative aspect-video max-h-[70vh] w-full overflow-hidden bg-slate-950" data-media-box>
            {sourceUrl && (
              <video
                ref={videoRef}
                src={sourceUrl}
                muted
                playsInline
                preload="auto"
                onLoadedMetadata={(e) => {
                  const v = e.currentTarget;
                  if (v.videoWidth && v.videoHeight && !(det.data?.width > 0)) setMediaSize({ w: v.videoWidth, h: v.videoHeight });
                  v.currentTime = seekTimeForFrame(frame, fps);
                }}
                onPlay={() => setPlaying(true)}
                onPause={(e) => {
                  setPlaying(false);
                  setFrame(timeToFrame(e.currentTarget.currentTime, fps, n));
                }}
                onTimeUpdate={(e) => playing && setFrame(timeToFrame(e.currentTarget.currentTime, fps, n))}
                className="absolute inset-0 size-full object-contain"
                aria-label="Original video"
              />
            )}
            {stillSrc && <img src={stillSrc} alt={`Frame ${frame}`} className="absolute inset-0 size-full object-contain" data-still />}
            {!playing && det.status === 'ready' && (
              <div
                ref={listRef}
                className="absolute overflow-hidden"
                style={{ left: rect.x, top: rect.y, width: rect.w, height: rect.h }}
                onKeyDown={onBoxesKey}
                role="group"
                aria-label={`Players detected in frame ${frame}`}
              >
                {players.map((p) => {
                  const on = selDet === p;
                  const ref = p.cls === 'referee';
                  return (
                    <button
                      key={p.key}
                      type="button"
                      data-det={p.key}
                      aria-pressed={on}
                      aria-label={`${nameOf(p)}${classNote(p) ? `, ${classNote(p)}` : ''}${p.conf != null ? `, detection ${Math.round(p.conf * 100)}%` : ''}`}
                      onClick={() => setSelected(on ? null : { kind: 'box', det: p })}
                      className={`group absolute rounded-sm outline-none ${
                        on
                          ? 'z-10 ring-2 ring-accent shadow-[0_0_0_9999px_rgba(0,0,0,0.5)]'
                          : `ring-1 ring-slate-300/60 hover:ring-2 hover:ring-accent focus-visible:ring-2 focus-visible:ring-accent ${ref ? 'opacity-50' : ''}`
                      }`}
                      style={{ left: `${p.bbox[0] * 100}%`, top: `${p.bbox[1] * 100}%`, width: `${p.bbox[2] * 100}%`, height: `${p.bbox[3] * 100}%` }}
                    >
                      <span
                        className={`pointer-events-none absolute left-0 whitespace-nowrap rounded bg-slate-900/90 px-1 py-px font-mono text-[10px] text-white ring-1 ring-accent ${
                          on ? '' : 'hidden group-hover:block group-focus-visible:block'
                        } ${p.bbox[1] < 0.06 ? 'top-full mt-0.5' : 'bottom-full mb-0.5'}`}
                      >
                        {nameOf(p)}
                        {ref ? ' · Ref' : ''}
                        {p.conf != null ? ` · ${Math.round(p.conf * 100)}%` : ''}
                      </span>
                    </button>
                  );
                })}
              </div>
            )}
            {!playing && det.status === 'loading' && (
              <span className="absolute right-3 top-3 inline-flex items-center gap-2 rounded-full bg-slate-900/80 px-2.5 py-1 text-caption text-slate-200">
                <Spinner className="size-3.5" /> Finding players…
              </span>
            )}
            {!playing && det.status === 'ready' && !players.length && (
              <div className="absolute inset-x-0 top-3 flex justify-center">
                <span role="status" className="rounded-full bg-slate-800 px-3 py-1 text-caption text-slate-100 ring-1 ring-slate-600">
                  No players detected here, try another frame
                </span>
              </div>
            )}
            {playing && <span className="absolute right-3 top-3 rounded-full bg-slate-900/80 px-2.5 py-1 text-caption text-slate-200">Pause to pick a player</span>}
            {selected && (
              <div
                className="absolute inset-x-0 bottom-0 z-20 flex flex-wrap items-center gap-3 border-t border-line bg-surface-raised/95 px-4 py-3 motion-safe:animate-[slideup_160ms_ease-out]"
                data-confirm
              >
                {selected.kind === 'box' && <CropThumb src={stillSrc} bbox={selDet.bbox} label={selLabel} className="h-12 w-9" />}
                <div className="min-w-0">
                  <p className="font-mono text-body font-semibold text-fg">{selLabel}</p>
                  <p className="text-caption text-fg-muted">
                    {selected.kind === 'box' ? `Selected at ${formatTime(t, true)} (frame ${det.data?.frame ?? frame})` : 'Selected by shirt number'}
                  </p>
                </div>
                <div className="ml-auto flex gap-2">
                  <button type="button" className={`${btn.ghost} h-9`} onClick={cancel}>
                    Cancel
                  </button>
                  <button type="button" className={`${btn.primary} h-9`} onClick={start} disabled={starting} autoFocus>
                    {starting ? 'Starting…' : 'Track this player'}
                  </button>
                </div>
              </div>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2 px-4 py-3">
            <button type="button" onClick={togglePlay} disabled={!sourceUrl} className={`${btn.secondary} h-9 min-w-16 px-3`} aria-label={playing ? 'Pause' : 'Play'}>
              {playing ? 'Pause' : 'Play'}
            </button>
            <button type="button" onClick={() => seek(frame - 1)} className={`${btn.ghost} h-9 px-2 font-mono`} aria-label="Previous frame">
              |◀
            </button>
            <button type="button" onClick={() => seek(frame + 1)} className={`${btn.ghost} h-9 px-2 font-mono`} aria-label="Next frame">
              ▶|
            </button>
            <input
              type="range"
              min={0}
              max={n - 1}
              value={frame}
              onChange={(e) => seek(Number(e.target.value))}
              aria-label="Scrub to a frame"
              aria-valuetext={`${formatTime(t, true)}, frame ${frame}`}
              className="h-9 min-w-40 flex-1 accent-[var(--color-accent)]"
            />
            <span className="font-mono text-caption text-fg-secondary">
              {formatTime(t, true)} · f{frame}
            </span>
          </div>
        </div>
        {det.status === 'error' && (
          <p role="alert" className="mt-3 text-caption text-risk-high">
            Couldn’t load the players in this frame: {det.error?.message}
          </p>
        )}
        {startError && (
          <div role="alert" className="mt-3 rounded-xl border border-risk-high-ring bg-status-danger-bg px-4 py-3 text-body text-status-danger" data-start-error>
            {startError}
          </div>
        )}
      </div>

      <aside className="space-y-4" aria-label="Pick a player">
        <section className={`${card} p-4`}>
          <div className="flex items-center justify-between gap-2">
            <h2 className={label}>Detected in this frame</h2>
            <label className="flex items-center gap-1.5 text-caption text-fg-muted">
              <input type="checkbox" checked={showRefs} onChange={(e) => setShowRefs(e.target.checked)} className="accent-[var(--color-accent)]" />
              Show referees
            </label>
          </div>
          {det.status === 'ready' && players.length ? (
            <ul className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-2" data-det-list>
              {players.map((p) => {
                const on = selDet === p;
                return (
                  <li key={p.key}>
                    <button
                      type="button"
                      aria-pressed={on}
                      onClick={() => setSelected(on ? null : { kind: 'box', det: p })}
                      className={`flex w-full items-center gap-2 rounded-lg p-1.5 text-left hover:bg-surface-overlay ${focusRing} ${on ? 'bg-surface-selected ring-1 ring-inset ring-accent' : ''} ${p.cls === 'referee' ? 'opacity-60' : ''}`}
                    >
                      <CropThumb src={stillSrc} bbox={p.bbox} label={nameOf(p)} className="h-12 w-9" />
                      <span className="min-w-0">
                        <span className="block font-mono text-body text-fg">{nameOf(p)}</span>
                        <span className="block truncate text-[11px] text-fg-muted">
                          {[classNote(p), p.conf != null ? `${Math.round(p.conf * 100)}%` : null].filter(Boolean).join(' · ')}
                        </span>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="mt-3 text-caption text-fg-muted">
              {det.status === 'loading' ? 'Loading…' : playing ? 'Pause the video to see detections.' : 'No players detected here, try another frame.'}
            </p>
          )}
        </section>
        {roster.length > 0 && (
          <section className={`${card} p-4`}>
            <h2 className={label}>Or pick by shirt number</h2>
            <label htmlFor="pick-jersey" className="sr-only">
              Shirt number
            </label>
            <select
              id="pick-jersey"
              value={selected?.kind === 'jersey' ? String(selected.row.player_id) : ''}
              onChange={(e) => {
                const r = roster.find((x) => String(x.player_id) === e.target.value);
                setSelected(r ? { kind: 'jersey', row: r } : null);
              }}
              className={`mt-2 h-10 w-full rounded-lg border border-line-input bg-surface-base px-2 text-body text-fg ${focusRing}`}
            >
              <option value="">Choose a player…</option>
              {roster.map((r) => (
                <option key={r.player_id} value={String(r.player_id)}>
                  {r.jersey_number != null ? `#${r.jersey_number}` : 'No number'} · {r.name}
                </option>
              ))}
            </select>
            <label htmlFor="pick-team" className="mt-3 block text-caption text-fg-muted">
              Team (optional)
            </label>
            <select
              id="pick-team"
              value={team}
              onChange={(e) => setTeam(e.target.value)}
              className={`mt-1 h-10 w-full rounded-lg border border-line-input bg-surface-base px-2 text-body text-fg ${focusRing}`}
            >
              <option value="">Not sure</option>
              <option value="A">Team A</option>
              <option value="B">Team B</option>
            </select>
          </section>
        )}
      </aside>
    </div>
  );
}
