import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { saveJerseyCorrection } from '../../lib/api';
import {
  ISSUE_LABEL,
  SHORTCUTS,
  SPEEDS,
  bboxToRect,
  buildIssues,
  formatTime,
  frameToTime,
  frameView,
  nextIssue,
  prevIssue,
  seekTimeForFrame,
  stepFrame,
  summarize,
  trailPoints,
} from '../../lib/tracking';
import { btn, card, focusRing, label } from '../classes';
import { useContentRect, usePrefersReducedMotion, useVideoFrame, isTypingTarget } from './hooks';
import { ConfidenceTimeline, CropThumb, SegmentedToggle } from './parts';

const num = (v) => (v === null || v === undefined || v === '' || !Number.isFinite(Number(v)) ? null : Number(v));

const ACCENT_FALLBACK = '#bef264';
const ctrl = `inline-flex min-h-9 min-w-9 items-center justify-center rounded-lg text-fg-secondary hover:bg-surface-overlay hover:text-fg ${focusRing}`;

function accentColor(el) {
  const v = el && getComputedStyle(el).getPropertyValue('--color-accent').trim();
  return v || ACCENT_FALLBACK;
}

// Draws ONLY the tracked player's box (+ label chip and optional trail) on the canvas.
function drawOverlay(canvas, rect, view, frames, frame, fps, { trail, labelText }) {
  const dpr = window.devicePixelRatio || 1;
  const W = Math.max(1, Math.round(rect.cw * dpr));
  const H = Math.max(1, Math.round(rect.ch * dpr));
  if (canvas.width !== W || canvas.height !== H) {
    canvas.width = W;
    canvas.height = H;
  }
  const ctx = canvas.getContext?.('2d');
  if (!ctx) return;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, rect.cw, rect.ch);
  if (!view.bbox) return;
  const accent = accentColor(canvas);
  if (trail) {
    const pts = trailPoints(frames, frame, fps, 1.5);
    for (let i = 1; i < pts.length; i++) {
      ctx.strokeStyle = accent;
      ctx.globalAlpha = (i / pts.length) * 0.8;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(rect.x + pts[i - 1].x * rect.w, rect.y + pts[i - 1].y * rect.h);
      ctx.lineTo(rect.x + pts[i].x * rect.w, rect.y + pts[i].y * rect.h);
      ctx.stroke();
    }
    ctx.globalAlpha = 1;
  }
  // 3px breathing room so the outline sits around the player, not on their edge.
  const b0 = bboxToRect(view.bbox, rect);
  const r = { x: b0.x - 3, y: b0.y - 3, w: b0.w + 6, h: b0.h + 6 };
  ctx.strokeStyle = accent;
  ctx.lineWidth = 2;
  ctx.setLineDash(view.low || view.estimate ? [6, 4] : []);
  ctx.beginPath();
  if (ctx.roundRect) ctx.roundRect(r.x, r.y, r.w, r.h, 2);
  else ctx.rect(r.x, r.y, r.w, r.h);
  ctx.stroke();
  ctx.setLineDash([]);
  // Label chip pinned top-left of the box; drops below the box near the top edge.
  ctx.font = '600 11px "JetBrains Mono", ui-monospace, monospace';
  const tw = ctx.measureText(labelText).width + 10;
  const th = 17;
  const above = r.y - th - 3 >= rect.y;
  const cx = Math.min(Math.max(r.x, rect.x), rect.x + rect.w - tw);
  const cy = above ? r.y - th - 3 : r.y + r.h + 3;
  ctx.fillStyle = accent;
  ctx.fillRect(cx, cy, tw, th);
  ctx.fillStyle = '#020617';
  ctx.fillText(labelText, cx + 5, cy + 12);
}

function JerseyEdit({ videoId, playerId, value, onSaved }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const [msg, setMsg] = useState(null);
  const [err, setErr] = useState(null);
  if (playerId == null) return null;
  const submit = async (e) => {
    e.preventDefault();
    const v = draft.trim();
    if (v !== '' && !/^\d{1,2}$/.test(v)) return setErr('Enter 0–99, or leave empty for no number.');
    try {
      const res = await saveJerseyCorrection({ videoId, playerId, jersey: v === '' ? null : Number(v) });
      onSaved(v === '' ? null : Number(v));
      setMsg(res.mode === 'server' ? 'Saved for this video.' : res.note);
      setErr(null);
      setEditing(false);
    } catch (e2) {
      setErr(e2?.message || 'Couldn’t save the shirt number.');
    }
  };
  if (!editing)
    return (
      <div className="mt-1">
        <button
          type="button"
          onClick={() => (setDraft(value != null ? String(value) : ''), setEditing(true), setErr(null))}
          className={`rounded text-caption text-fg-secondary underline decoration-slate-600 underline-offset-4 hover:text-fg ${focusRing}`}
        >
          {value != null ? 'Wrong number? Edit' : 'Set shirt number'}
        </button>
        {msg && (
          <p role="status" className="mt-1 text-caption text-fg-muted">
            {msg}
          </p>
        )}
      </div>
    );
  return (
    <form onSubmit={submit} className="mt-2 flex flex-wrap items-center gap-2" onKeyDown={(e) => e.key === 'Escape' && setEditing(false)}>
      <label htmlFor="track-jersey" className="sr-only">
        Shirt number
      </label>
      <input
        id="track-jersey"
        autoFocus
        inputMode="numeric"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        aria-invalid={Boolean(err)}
        aria-describedby={err ? 'track-jersey-err' : undefined}
        className="h-9 w-16 rounded-lg border border-line-input bg-surface-base px-2 font-mono text-body text-fg outline-none focus-visible:border-accent focus-visible:outline-2 focus-visible:outline-accent"
      />
      <button type="submit" className={`${btn.primary} h-9 px-3`}>
        Save
      </button>
      <button type="button" onClick={() => setEditing(false)} className={`${btn.ghost} h-9 px-3`}>
        Cancel
      </button>
      {err && (
        <p id="track-jersey-err" role="alert" className="w-full text-caption text-risk-high">
          {err}
        </p>
      )}
    </form>
  );
}

export default function Replay({ track, data, sourceUrl, annotatedUrl, player = null, thumb = null, videoId, onPickAgain, demo = false }) {
  const fps = data.fps || track.fps || 25;
  const frames = data.frames;
  const n = frames.length;
  const width = data.width || track.width || 16;
  const height = data.height || track.height || 9;
  const overlayOk = Boolean(sourceUrl) && n > 0;
  const annotatedOk = Boolean(annotatedUrl);
  const [mode, setMode] = useState(overlayOk ? 'overlay' : 'annotated');
  const [playing, setPlaying] = useState(false);
  const [rate, setRate] = useState(1);
  const [loop, setLoop] = useState(false);
  const [activeIssue, setActiveIssue] = useState(null);
  const [trail, setTrail] = useState(false);
  const [help, setHelp] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const [jersey, setJersey] = useState(track.target.jersey_number ?? player?.jersey_number ?? null);
  const reduced = usePrefersReducedMotion();

  const videoRef = useRef(null);
  const boxRef = useRef(null);
  const canvasRef = useRef(null);
  const wrapRef = useRef(null);
  const resume = useRef(null);
  const src = mode === 'overlay' ? sourceUrl : annotatedUrl;
  const rect = useContentRect(boxRef, width, height);
  const [frame, setFrame] = useVideoFrame(videoRef, fps, n, [src]);

  const serverSummary = track.summary ?? null;
  const issues = useMemo(() => buildIssues(frames, fps, { lostSegments: serverSummary?.lost_segments }), [frames, fps, serverSummary]);
  const stats = useMemo(() => summarize(frames, fps, serverSummary), [frames, fps, serverSummary]);
  const view = frameView(frames, frame);
  const teamTag = track.target.team ? ` · Team ${track.target.team}` : '';
  const idText = jersey != null ? `#${jersey}${player?.name ? ` ${player.name}` : ''}` : `Unknown player${teamTag}`;
  const labelText = `${idText}${view.conf != null ? ` · ${Math.round(view.conf * 100)}%` : ''}`;

  // ---- media control -------------------------------------------------------
  const seek = useCallback(
    (f) => {
      const v = videoRef.current;
      const target = Math.max(0, Math.min(n - 1, f));
      if (v) v.currentTime = seekTimeForFrame(target, fps);
      setFrame(target);
    },
    [fps, n, setFrame],
  );
  const toggle = useCallback(() => {
    const v = videoRef.current;
    if (!v) return;
    if (v.paused) v.play?.()?.catch?.(() => {});
    else v.pause();
  }, []);
  const step = useCallback(
    (d) => {
      videoRef.current?.pause();
      seek(stepFrame(frame, d, n));
    },
    [frame, n, seek],
  );
  const jump = useCallback((sec) => seek(frame + Math.round(sec * fps)), [frame, fps, seek]);
  const goIssue = useCallback(
    (dir) => {
      const it = dir > 0 ? nextIssue(issues, frame) : prevIssue(issues, frame);
      if (it) {
        setActiveIssue(it);
        seek(it.start);
      }
    },
    [issues, frame, seek],
  );
  const toggleFullscreen = useCallback(() => {
    const el = wrapRef.current;
    if (!el) return;
    if (document.fullscreenElement) document.exitFullscreen?.();
    else el.requestFullscreen?.();
  }, []);

  useEffect(() => {
    const on = () => setFullscreen(Boolean(document.fullscreenElement));
    document.addEventListener('fullscreenchange', on);
    return () => document.removeEventListener('fullscreenchange', on);
  }, []);

  // Keep rate + position across a mode switch (the <video> source changes).
  const switchMode = (m) => {
    const v = videoRef.current;
    resume.current = { frame, playing: v ? !v.paused : false };
    setMode(m);
  };
  const onLoaded = () => {
    const v = videoRef.current;
    if (!v) return;
    v.playbackRate = rate;
    if (resume.current) {
      v.currentTime = seekTimeForFrame(resume.current.frame, fps);
      if (resume.current.playing) v.play?.()?.catch?.(() => {});
      resume.current = null;
    }
  };
  useEffect(() => {
    if (videoRef.current) videoRef.current.playbackRate = rate;
  }, [rate]);

  // Loop the active issue.
  useEffect(() => {
    if (loop && activeIssue && playing && frame > activeIssue.end) seek(activeIssue.start);
  }, [loop, activeIssue, playing, frame, seek]);

  // ---- overlay drawing -----------------------------------------------------
  useEffect(() => {
    const c = canvasRef.current;
    if (!c) return;
    if (mode !== 'overlay') {
      c.getContext?.('2d')?.clearRect(0, 0, c.width, c.height);
      return;
    }
    drawOverlay(c, rect, view, frames, frame, fps, { trail: trail && !reduced, labelText });
  });

  // ---- keyboard ------------------------------------------------------------
  useEffect(() => {
    const onKey = (e) => {
      if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.altKey || isTypingTarget(e.target)) return;
      const k = e.key;
      const map = {
        ' ': toggle,
        ArrowLeft: () => jump(e.shiftKey ? -5 : -1),
        ArrowRight: () => jump(e.shiftKey ? 5 : 1),
        ',': () => step(-1),
        '<': () => step(-1),
        '.': () => step(1),
        '>': () => step(1),
        n: () => goIssue(1),
        N: () => goIssue(1),
        p: () => goIssue(-1),
        P: () => goIssue(-1),
        f: toggleFullscreen,
        F: toggleFullscreen,
        '?': () => setHelp((h) => !h),
        Escape: () => setHelp(false),
      };
      // Space on a focused button already activates it.
      if (k === ' ' && e.target?.tagName === 'BUTTON') return;
      const fn = map[k];
      if (!fn) return;
      e.preventDefault();
      fn();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [toggle, jump, step, goIssue, toggleFullscreen]);

  const t = frameToTime(frame, fps);
  const dur = frameToTime(n, fps);
  const currentIssue = issues.find((s) => frame >= s.start && frame <= s.end) ?? null;
  const modeOptions = [
    {
      value: 'overlay',
      label: 'Live overlay',
      disabled: !overlayOk,
      reason: !sourceUrl ? 'The original video isn’t available from this server.' : 'No per-frame track data.',
      reasonId: 'mode-reason-overlay',
    },
    {
      value: 'annotated',
      label: 'Annotated video',
      disabled: !annotatedOk,
      reason: 'The server didn’t produce an annotated video for this track.',
      reasonId: 'mode-reason-annotated',
    },
  ];
  const disabledReasons = modeOptions.filter((o) => o.disabled);

  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <div className="min-w-0 lg:col-span-2">
        <div ref={wrapRef} className={`${fullscreen ? 'flex h-full flex-col justify-center bg-slate-950 p-4' : ''}`}>
          <div className="mb-3 flex flex-wrap items-center gap-3">
            <SegmentedToggle label="Replay mode" value={mode} options={modeOptions} onChange={switchMode} />
            {disabledReasons.map((o) => (
              <p key={o.value} id={o.reasonId} className="text-caption text-fg-muted" data-disabled-reason={o.value}>
                {o.label} unavailable: {o.reason}
              </p>
            ))}
          </div>
          <div
            ref={boxRef}
            className={`relative w-full overflow-hidden rounded-2xl bg-slate-950 ring-1 ring-line ${fullscreen ? 'h-[70vh]' : 'aspect-video max-h-[70vh]'}`}
            data-media-box
          >
            {src ? (
              <video
                key={src}
                ref={videoRef}
                src={src}
                playsInline
                muted
                preload="auto"
                crossOrigin={undefined}
                onLoadedMetadata={onLoaded}
                onPlay={() => setPlaying(true)}
                onPause={() => setPlaying(false)}
                onEnded={() => setPlaying(false)}
                className="absolute inset-0 size-full object-contain"
                aria-label={mode === 'overlay' ? 'Original video with live tracking overlay' : 'Annotated tracking video from the server'}
              />
            ) : null}
            <canvas ref={canvasRef} aria-hidden="true" className="pointer-events-none absolute inset-0 size-full" data-overlay={mode === 'overlay' ? 'on' : 'off'} />
            {view.state === 'lost' && (
              <div className="pointer-events-none absolute inset-x-0 top-3 flex justify-center">
                <span role="status" className="rounded-full bg-slate-800 px-3 py-1 text-caption font-medium text-slate-100 border border-dashed border-slate-400" data-badge="lost">
                  Player lost
                </span>
              </div>
            )}
            {view.state === 'occluded' && (
              <div className="pointer-events-none absolute left-3 top-3">
                <span className="rounded-full bg-slate-800/90 px-3 py-1 text-caption font-medium text-slate-100 ring-1 ring-slate-600" data-badge="occluded">
                  Occluded · estimated position
                </span>
              </div>
            )}
            {view.low && (
              <div className="pointer-events-none absolute left-3 top-3">
                <span className="rounded-full bg-slate-800/90 px-3 py-1 text-caption font-medium text-slate-100 ring-1 ring-slate-600" data-badge="low">
                  Low confidence
                </span>
              </div>
            )}
          </div>

          <ConfidenceTimeline className="mt-8" frames={frames} fps={fps} frame={frame} onSeek={(f) => seek(f)} lostSegments={serverSummary?.lost_segments} />
          <p className="mt-2 font-mono text-caption text-fg-secondary" data-summary={stats.fromServer ? 'server' : 'derived'}>
            {stats.trackedPct != null
              ? `Tracked ${Math.round(stats.trackedPct)}% of frames · ${stats.lostSegments} lost segment${stats.lostSegments === 1 ? '' : 's'} · longest gap ${
                  stats.longestLostSec != null ? `${stats.longestLostSec.toFixed(1)} s` : `${stats.longestLostFrames} frames`
                } · ${stats.reacquisitions} re-acquisition${stats.reacquisitions === 1 ? '' : 's'}${stats.avgConf != null ? ` · avg conf ${stats.avgConf.toFixed(2)}` : ''}`
              : 'No per-frame track data.'}
          </p>

          {/* Playback controls (spec §4); wraps to two rows below md. */}
          <div className="mt-3 flex flex-wrap items-center gap-x-1 gap-y-2" role="group" aria-label="Playback controls">
            <button type="button" className={ctrl} onClick={() => step(-1)} aria-label="Previous frame" title="Previous frame (, or <)">
              <span aria-hidden="true" className="font-mono text-body">
                |◀
              </span>
            </button>
            <button type="button" className={`${btn.primary} h-9 min-w-20 px-3`} onClick={toggle} aria-label={playing ? 'Pause' : 'Play'} disabled={!src}>
              {playing ? 'Pause' : 'Play'}
            </button>
            <button type="button" className={ctrl} onClick={() => step(1)} aria-label="Next frame" title="Next frame (. or >)">
              <span aria-hidden="true" className="font-mono text-body">
                ▶|
              </span>
            </button>
            <span className="mx-2 font-mono text-caption text-fg-secondary" aria-live="off" data-time>
              {formatTime(t, true)} / {formatTime(dur, true)}
            </span>
            <label className="flex items-center gap-1.5 text-caption text-fg-muted">
              Speed
              <select
                value={rate}
                onChange={(e) => setRate(Number(e.target.value))}
                className={`h-9 rounded-lg border border-line-input bg-surface-base px-2 font-mono text-caption text-fg ${focusRing}`}
                aria-label="Playback speed"
              >
                {SPEEDS.map((s) => (
                  <option key={s} value={s}>
                    {s}×
                  </option>
                ))}
              </select>
            </label>
            <button type="button" className={`${ctrl} px-2 text-caption`} aria-pressed={loop} onClick={() => setLoop((l) => !l)} title="Loop the current issue">
              <span className={loop ? 'text-fg' : ''}>Loop issue</span>
              {loop && <span className="ml-1 size-1.5 rounded-full bg-accent" aria-hidden="true" />}
            </button>
            {mode === 'overlay' && (
              <button
                type="button"
                className={`${ctrl} px-2 text-caption`}
                aria-pressed={trail && !reduced}
                disabled={reduced}
                title={reduced ? 'Off because reduced motion is on' : 'Show the last 1.5 s of movement'}
                onClick={() => setTrail((x) => !x)}
              >
                Show trail
              </button>
            )}
            <span className="ml-auto flex items-center gap-1">
              <span className="relative">
                <button
                  type="button"
                  className={`${ctrl} font-mono`}
                  aria-label="Keyboard shortcuts"
                  aria-expanded={help}
                  aria-controls="track-shortcuts"
                  onClick={() => setHelp((h) => !h)}
                >
                  ?
                </button>
                {help && (
                  <div
                    id="track-shortcuts"
                    role="dialog"
                    aria-label="Keyboard shortcuts"
                    className="absolute bottom-11 right-0 z-20 w-64 rounded-xl bg-surface-overlay p-3 shadow-card ring-1 ring-line-strong"
                  >
                    <p className={label}>Keyboard shortcuts</p>
                    <dl className="mt-2 space-y-1.5">
                      {SHORTCUTS.map(([k, d]) => (
                        <div key={k} className="flex justify-between gap-3 text-caption">
                          <dt className="font-mono text-fg">{k}</dt>
                          <dd className="text-fg-secondary">{d}</dd>
                        </div>
                      ))}
                    </dl>
                  </div>
                )}
              </span>
              <button type="button" className={ctrl} onClick={toggleFullscreen} aria-label={fullscreen ? 'Exit fullscreen' : 'Fullscreen'} aria-pressed={fullscreen}>
                <span aria-hidden="true">⛶</span>
              </button>
            </span>
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <button type="button" className={`${btn.secondary} h-9`} onClick={() => goIssue(-1)} disabled={!issues.length}>
              Previous issue
            </button>
            <button type="button" className={`${btn.secondary} h-9`} onClick={() => goIssue(1)} disabled={!issues.length}>
              Next issue
            </button>
            <p className="font-mono text-caption text-fg-muted" aria-live="polite" data-readout>
              Frame {frame} ·{' '}
              {view.state === 'lost'
                ? 'Lost'
                : `${view.state === 'occluded' ? 'Occluded · ' : view.low ? 'Low conf · ' : ''}conf ${view.conf != null ? view.conf.toFixed(2) : '—'}`}
              {currentIssue ? ` · issue ${issues.indexOf(currentIssue) + 1} of ${issues.length}` : ''}
            </p>
          </div>
        </div>
      </div>

      {/* Side panel (spec §5) */}
      <aside className="space-y-4" aria-label="Tracked player and issues">
        <section className={`${card} p-4`}>
          <h2 className={label}>Tracked player</h2>
          <div className="mt-3 flex items-start gap-3">
            <CropThumb src={thumb?.src} bbox={thumb?.bbox} label={jersey != null ? `#${jersey}` : 'Unknown player'} className="h-16 w-12" />
            <div className="min-w-0">
              <p className="text-title text-fg">
                <span className="font-mono">{jersey != null ? `#${jersey}` : 'Unknown player'}</span>
                {player?.name ? <span className="ml-2 text-body font-normal text-fg-secondary">{player.name}</span> : null}
              </p>
              {track.target.team && <p className="text-caption text-fg-muted">Team {track.target.team}</p>}
              {!demo && <JerseyEdit videoId={videoId} playerId={track.target.player_id ?? player?.player_id ?? null} value={jersey} onSaved={setJersey} />}
            </div>
          </div>
          {/* The track's own stats (target_stats.json); hidden when the server sent none. */}
          {track.stats && (track.stats.top_speed_mph != null || track.stats.distance_km != null) && (
            <dl className="mt-4 grid grid-cols-2 gap-3" data-track-stats>
              <div>
                <dt className="text-caption text-fg-muted">Top speed</dt>
                <dd className="font-mono text-title text-metric-speed">{num(track.stats.top_speed_mph) != null ? `${num(track.stats.top_speed_mph).toFixed(1)} mph` : '—'}</dd>
              </div>
              <div>
                <dt className="text-caption text-fg-muted">Distance</dt>
                <dd className="font-mono text-title text-metric-distance">{num(track.stats.distance_km) != null ? `${num(track.stats.distance_km).toFixed(2)} km` : '—'}</dd>
              </div>
            </dl>
          )}
          <button type="button" className={`${btn.ghost} mt-3 h-9 px-0`} onClick={onPickAgain}>
            Track someone else
          </button>
        </section>

        <section className={`${card} p-4`} aria-labelledby="issues-title">
          <h2 id="issues-title" className={label}>
            Issues <span className="font-mono normal-case tracking-normal">({issues.length})</span>
          </h2>
          {issues.length ? (
            <ul className="mt-3 max-h-80 space-y-1 overflow-y-auto pr-1" data-issues>
              {issues.map((s, i) => {
                const on = activeIssue?.id === s.id;
                return (
                  <li key={s.id}>
                    <button
                      type="button"
                      onClick={() => (setActiveIssue(s), setLoop(true), seek(s.start))}
                      aria-current={on || undefined}
                      className={`flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-caption hover:bg-surface-overlay ${focusRing} ${on ? 'bg-surface-selected ring-1 ring-inset ring-accent/40' : ''}`}
                    >
                      <span className="w-5 font-mono text-fg-muted">{i + 1}</span>
                      <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[11px] font-medium text-slate-200 ring-1 ring-slate-600">{ISSUE_LABEL[s.kind]}</span>
                      <span className="font-mono text-fg-secondary">
                        {formatTime(s.startT, true)}–{formatTime(s.endT, true)}
                      </span>
                      <span className="ml-auto font-mono text-fg-muted">{s.duration.toFixed(1)} s</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="mt-3 text-caption text-fg-muted">No lost or low-confidence frames.</p>
          )}
        </section>
      </aside>
    </div>
  );
}
