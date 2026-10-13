import { useId, useMemo, useRef, useState } from 'react';
import { LOW_CONF, formatTime, frameToTime, lostRuns } from '../../lib/tracking';
import { focusRing } from '../classes';

// Crop of one bbox from a frame image (CSS background crop, no canvas, no CORS).
export function CropThumb({ src, bbox, label = '', className = 'h-14 w-10' }) {
  if (!src || !bbox) {
    return (
      <span
        aria-hidden="true"
        className={`${className} flex shrink-0 items-center justify-center rounded-md bg-slate-800 font-mono text-[11px] text-slate-400 ring-1 ring-slate-700`}
      >
        {label || '?'}
      </span>
    );
  }
  // Pad the box 15% so the crop shows a little context.
  const pad = 0.15;
  const w = Math.min(1, bbox[2] * (1 + 2 * pad));
  const h = Math.min(1, bbox[3] * (1 + 2 * pad));
  const x = Math.max(0, Math.min(1 - w, bbox[0] - bbox[2] * pad));
  const y = Math.max(0, Math.min(1 - h, bbox[1] - bbox[3] * pad));
  const pos = (v, s) => (s >= 1 ? 0 : (v / (1 - s)) * 100);
  return (
    <span
      aria-hidden="true"
      data-crop
      className={`${className} block shrink-0 rounded-md bg-slate-900 bg-no-repeat ring-1 ring-slate-700`}
      style={{ backgroundImage: `url("${src}")`, backgroundSize: `${100 / w}% ${100 / h}%`, backgroundPosition: `${pos(x, w)}% ${pos(y, h)}%` }}
    />
  );
}

// Confidence / lost timeline (UI/UX spec §3): accent single-hue area chart of confidence,
// dashed 0.5 threshold, lost runs as slate-700 diagonal stripes, white playhead + time chip.
// It is also the scrubber: click/drag or arrow keys seek (role="slider").
export function ConfidenceTimeline({ frames, fps, frame, onSeek, lostSegments = null, className = '' }) {
  const n = frames.length;
  const ref = useRef(null);
  const [hover, setHover] = useState(null);
  const dragging = useRef(false);
  const pid = useId().replace(/:/g, '');
  const lost = useMemo(() => lostRuns(frames, lostSegments), [frames, lostSegments]);
  const H = 40;
  const { area, line } = useMemo(() => {
    let a = '';
    let l = '';
    let open = false;
    for (const r of frames) {
      const x = r.f + 0.5;
      const y = r.conf === null || r.state === 'lost' ? null : H - Math.max(0, Math.min(1, r.conf)) * (H - 2);
      if (y === null) {
        if (open) a += `L${x - 0.5},${H}Z`;
        open = false;
        continue;
      }
      if (!open) {
        a += `M${x - 0.5},${H}L${x - 0.5},${y}`;
        l += `M${x - 0.5},${y}`;
        open = true;
      }
      a += `L${x},${y}`;
      l += `L${x},${y}`;
    }
    if (open) a += `L${n},${H}Z`;
    return { area: a, line: l };
  }, [frames, n]);

  const frameAt = (clientX) => {
    const r = ref.current.getBoundingClientRect();
    return Math.max(0, Math.min(n - 1, Math.floor(((clientX - r.left) / Math.max(1, r.width)) * n)));
  };
  const onPointerDown = (e) => {
    dragging.current = true;
    e.currentTarget.setPointerCapture?.(e.pointerId);
    onSeek(frameAt(e.clientX));
  };
  const onPointerMove = (e) => {
    const f = frameAt(e.clientX);
    setHover(f);
    if (dragging.current) onSeek(f);
  };
  const onKeyDown = (e) => {
    const step = { ArrowLeft: -1, ArrowRight: 1, Home: -Infinity, End: Infinity, PageDown: -Math.round(fps * 5), PageUp: Math.round(fps * 5) }[e.key];
    if (step === undefined) return;
    e.preventDefault();
    e.stopPropagation();
    onSeek(Math.max(0, Math.min(n - 1, step === -Infinity ? 0 : step === Infinity ? n - 1 : frame + step)));
  };
  const hv = hover !== null ? frames[hover] : null;
  const pct = (f) => `${(n ? (f + 0.5) / n : 0) * 100}%`;
  const valueText = (() => {
    const r = frames[frame];
    const t = formatTime(frameToTime(frame, fps), true);
    if (!r || r.state === 'lost') return `${t}, player lost`;
    return `${t}, ${r.state === 'occluded' ? 'occluded, ' : ''}confidence ${r.conf !== null ? r.conf.toFixed(2) : 'unknown'}`;
  })();

  return (
    <div className={`relative select-none ${className}`}>
      <div
        ref={ref}
        role="slider"
        tabIndex={0}
        aria-label="Timeline: confidence and lost segments. Seek"
        aria-valuemin={0}
        aria-valuemax={Math.max(0, n - 1)}
        aria-valuenow={frame}
        aria-valuetext={valueText}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={() => (dragging.current = false)}
        onPointerCancel={() => (dragging.current = false)}
        onPointerLeave={() => setHover(null)}
        onKeyDown={onKeyDown}
        className={`relative h-10 w-full cursor-pointer touch-none overflow-hidden rounded-md bg-surface-sunken ring-1 ring-inset ring-line ${focusRing}`}
        data-timeline
      >
        <svg viewBox={`0 0 ${Math.max(1, n)} ${H}`} preserveAspectRatio="none" className="absolute inset-0 size-full" aria-hidden="true">
          <defs>
            <pattern id={`stripes-${pid}`} width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <rect width="6" height="6" fill="#1e293b" />
              <rect width="3" height="6" fill="#334155" />
            </pattern>
          </defs>
          {lost.map((s) => (
            <rect key={`l${s.start}`} data-seg="lost" x={s.start} y={0} width={s.end - s.start + 1} height={H} fill={`url(#stripes-${pid})`} />
          ))}
          <path d={area} fill="var(--color-accent)" fillOpacity="0.3" />
          <path d={line} fill="none" stroke="var(--color-accent)" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
          <line
            x1={0}
            x2={n}
            y1={H - LOW_CONF * (H - 2)}
            y2={H - LOW_CONF * (H - 2)}
            stroke="#cbd5e1"
            strokeOpacity="0.6"
            strokeDasharray="4 3"
            vectorEffect="non-scaling-stroke"
          />
        </svg>
        <span className="pointer-events-none absolute right-1 font-mono text-[10px] leading-none text-slate-300" style={{ top: `${(1 - LOW_CONF) * 100 - 14}%` }}>
          0.5
        </span>
        <span className="pointer-events-none absolute inset-y-0 w-0.5 -translate-x-1/2 bg-white" style={{ left: pct(frame) }} data-playhead />
      </div>
      <span
        className="pointer-events-none absolute -top-6 -translate-x-1/2 rounded bg-slate-800 px-1.5 py-0.5 font-mono text-[11px] text-white ring-1 ring-slate-600"
        style={{ left: `clamp(1.5rem, ${pct(frame)}, calc(100% - 1.5rem))` }}
      >
        {formatTime(frameToTime(frame, fps), true)}
      </span>
      {hv && (
        <span
          role="tooltip"
          className="pointer-events-none absolute top-12 z-10 -translate-x-1/2 whitespace-nowrap rounded bg-slate-800 px-2 py-1 font-mono text-[11px] text-slate-100 ring-1 ring-slate-600"
          style={{ left: `clamp(3rem, ${pct(hover)}, calc(100% - 3rem))` }}
        >
          {formatTime(frameToTime(hover, fps), true)} ·{' '}
          {hv.state === 'lost' ? 'Lost' : `${hv.state === 'occluded' ? 'Occluded · ' : ''}conf ${hv.conf !== null ? hv.conf.toFixed(2) : '—'}`}
        </span>
      )}
    </div>
  );
}

export function SegmentedToggle({ label, value, options, onChange }) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-lg bg-surface-sunken p-0.5 ring-1 ring-inset ring-line">
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={active}
            aria-disabled={o.disabled || undefined}
            disabled={o.disabled}
            title={o.disabled ? o.reason : undefined}
            aria-describedby={o.disabled && o.reasonId ? o.reasonId : undefined}
            onClick={() => !o.disabled && onChange(o.value)}
            className={`min-h-9 rounded-md px-3 text-caption font-medium transition-colors ${focusRing} ${
              active ? 'bg-surface-overlay text-fg ring-1 ring-inset ring-line-strong' : 'text-fg-muted hover:text-fg'
            } disabled:cursor-not-allowed disabled:text-fg-disabled disabled:hover:text-fg-disabled`}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
