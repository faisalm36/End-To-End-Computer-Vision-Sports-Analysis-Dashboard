import { useEffect, useRef } from 'react';
import { btn, card, focusRing } from './classes';

export function Logo({ className = '' }) {
  return (
    <span
      aria-hidden="true"
      className={`inline-flex size-8 items-center justify-center rounded-lg bg-surface-overlay ring-1 ring-inset ring-line-strong ${className}`}
    >
      <svg viewBox="0 0 24 24" className="size-5 text-fg" fill="none" stroke="currentColor" strokeWidth="1.6">
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7.5l3.2 2.3-1.2 3.8H10l-1.2-3.8L12 7.5z" fill="currentColor" stroke="none" />
        <path d="M12 3v4.5M15.2 9.8l4.3-1.5M14 13.6l2.6 3.8M10 13.6l-2.6 3.8M8.8 9.8L4.5 8.3" />
      </svg>
    </span>
  );
}

export function Spinner({ className = 'size-4' }) {
  return (
    <svg className={`animate-spin ${className}`} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeOpacity="0.25" strokeWidth="3" />
      <path d="M22 12a10 10 0 0 0-10-10" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

export function Icon({ name, className = 'size-5' }) {
  const paths = {
    upload: 'M12 16V4m0 0l-4 4m4-4l4 4M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2',
    video: 'M4 6h11a1 1 0 011 1v10a1 1 0 01-1 1H4a1 1 0 01-1-1V7a1 1 0 011-1zm12 4l5-3v10l-5-3',
    user: 'M12 12a4 4 0 100-8 4 4 0 000 8zm-7 8a7 7 0 0114 0',
    check: 'M5 12.5l4.5 4.5L19 7.5',
    x: 'M6 6l12 12M18 6L6 18',
    alert: 'M12 8v5m0 3.5v.01M10.3 3.9L2.5 17.5A2 2 0 004.2 20.5h15.6a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z',
    target: 'M12 21a9 9 0 100-18 9 9 0 000 18zm0-5a4 4 0 100-8 4 4 0 000 8zm0-3.5a.5.5 0 100-1 .5.5 0 000 1z',
    hash: 'M5 9h14M5 15h14M10 3L8 21M16 3l-2 18',
    gauge: 'M12 14l4-6M4.9 18a9 9 0 1114.2 0',
    menu: 'M4 6h16M4 12h16M4 18h16',
    search: 'M11 18a7 7 0 100-14 7 7 0 000 14zm9 3l-4.3-4.3',
    trash: 'M4 7h16M10 11v6m4-6v6M6 7l1 12a2 2 0 002 2h6a2 2 0 002-2l1-12M9 7V4h6v3',
    eye: 'M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12zm10 3a3 3 0 100-6 3 3 0 000 6z',
    eyeOff: 'M3 3l18 18M10.6 10.6a3 3 0 004.2 4.2M9.9 5.2A10.4 10.4 0 0112 5c6.5 0 10 7 10 7a17 17 0 01-3.2 4.2M6.6 6.6C3.9 8.4 2 12 2 12s3.5 7 10 7c1.6 0 3-.4 4.3-1',
    film: 'M4 4h16v16H4zM8 4v16M16 4v16M4 8h4m8 0h4M4 16h4m8 0h4',
    arrowRight: 'M5 12h14m-5-5l5 5-5 5',
    cloud: 'M7 18h10a4 4 0 00.6-8A6 6 0 006.2 9.5 4.3 4.3 0 007 18z',
    grass: 'M4 20h16M6 20c0-4 1-7 3-9M12 20c0-5 0-8 0-11M18 20c0-4-1-7-3-9',
    home: 'M4 11l8-7 8 7v9H4zM10 20v-5h4v5',
    shield: 'M12 3l7 3v6c0 4-3 7.5-7 9-4-1.5-7-5-7-9V6z',
    trophy: 'M8 4h8v5a4 4 0 01-8 0zM8 6H5a3 3 0 003 4M16 6h3a3 3 0 01-3 4M12 13v4M9 20h6',
    users: 'M9 11a3.5 3.5 0 100-7 3.5 3.5 0 000 7zm-6 9a6 6 0 0112 0M16 4.5a3.5 3.5 0 010 6.5M18 14a5.5 5.5 0 013 6',
    clock: 'M12 21a9 9 0 100-18 9 9 0 000 18zm0-13v4.5l3 2',
    tag: 'M3 12V4h8l9 9-8 8zM7.5 7.5v.01',
    filter: 'M4 5h16l-6 8v5l-4 2v-7z',
    chart: 'M4 20V10m6 10V4m6 16v-7m4 7H2',
    plus: 'M12 5v14M5 12h14',
  };
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={paths[name] || paths.alert} />
    </svg>
  );
}

export function Skeleton({ className = '' }) {
  return <div aria-hidden="true" className={`skeleton rounded-md ${className}`} />;
}

// Error banner: role="alert", danger tokens, optional Retry.
export function ErrorBanner({ title = 'Something went wrong', children, onRetry, retryLabel = 'Retry', className = '' }) {
  return (
    <div role="alert" className={`flex flex-col gap-3 rounded-card border border-risk-high-ring bg-status-danger-bg p-4 sm:flex-row sm:items-start sm:justify-between ${className}`}>
      <div className="flex gap-3">
        <Icon name="alert" className="mt-0.5 size-5 shrink-0 text-status-danger" />
        <div>
          <p className="text-body font-semibold text-status-danger">{title}</p>
          {children && <div className="mt-1 text-body text-fg-secondary">{children}</div>}
        </div>
      </div>
      {onRetry && (
        <button type="button" onClick={onRetry} className={`${btn.secondary} h-9 shrink-0`}>
          {retryLabel}
        </button>
      )}
    </div>
  );
}

// Neutral informational banner (e.g. sample-data notice). Uses status-warning.
export function NoticeBanner({ children, action, className = '' }) {
  return (
    <div role="status" className={`flex flex-col gap-3 rounded-card border border-risk-medium-ring bg-risk-medium-bg px-4 py-3 sm:flex-row sm:items-center sm:justify-between ${className}`}>
      <p className="flex items-start gap-2 text-body text-fg-secondary">
        <Icon name="alert" className="mt-0.5 size-4 shrink-0 text-status-warning" />
        <span>{children}</span>
      </p>
      {action}
    </div>
  );
}

export function EmptyState({ icon = 'video', title, hint, action }) {
  return (
    <div className={`${card} flex flex-col items-center border-dashed px-6 py-14 text-center`}>
      <span className="flex size-11 items-center justify-center rounded-xl bg-surface-overlay text-fg-muted ring-1 ring-inset ring-line-strong">
        <Icon name={icon} />
      </span>
      <p className="mt-4 text-body font-medium text-fg">{title}</p>
      {hint && <p className="mt-1 max-w-sm text-caption text-fg-muted">{hint}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

// Video processing status badge. Processing = accent + pulse dot, Complete =
// neutral slate + check (never risk green), Failed = rose.
export function StatusBadge({ status }) {
  const base = 'inline-flex items-center gap-1.5 rounded-chip px-2.5 py-0.5 text-caption font-medium ring-1 ring-inset whitespace-nowrap';
  if (status === 'processing') {
    return (
      <span className={`${base} bg-accent/10 text-accent ring-accent/40`}>
        <span className="size-1.5 animate-pulse rounded-full bg-current" />
        Processing
      </span>
    );
  }
  if (status === 'complete') {
    return (
      <span className={`${base} bg-surface-overlay text-fg-secondary ring-line-strong`}>
        <Icon name="check" className="size-3.5" />
        Complete
      </span>
    );
  }
  if (status === 'failed') {
    return (
      <span className={`${base} bg-status-danger-bg text-status-danger ring-risk-high-ring`}>
        <Icon name="x" className="size-3.5" />
        Failed
      </span>
    );
  }
  return (
    <span className={`${base} border border-dashed border-risk-unknown-ring bg-risk-unknown-bg text-risk-unknown ring-0`}>
      ? Unknown
    </span>
  );
}

// Accessible modal dialog built on <dialog>. Esc closes; focus is trapped natively.
export function Modal({ open, onClose, title, children, labelledBy = 'modal-title' }) {
  const ref = useRef(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (open && !el.open) el.showModal();
    if (!open && el.open) el.close();
  }, [open]);
  return (
    <dialog
      ref={ref}
      aria-labelledby={labelledBy}
      onClose={onClose}
      onClick={(e) => {
        if (e.target === ref.current) onClose();
      }}
      className="m-auto w-[calc(100%-2rem)] max-w-md rounded-card border border-line bg-surface-raised p-0 text-fg shadow-panel backdrop:bg-surface-base/70"
    >
      {open && (
        <div className="p-6">
          <div className="flex items-start justify-between gap-4">
            <h2 id={labelledBy} className="text-title text-fg">
              {title}
            </h2>
            <button type="button" onClick={onClose} aria-label="Close" className={`rounded-md p-1 text-fg-muted hover:bg-surface-overlay hover:text-fg ${focusRing}`}>
              <Icon name="x" className="size-5" />
            </button>
          </div>
          <div className="mt-4">{children}</div>
        </div>
      )}
    </dialog>
  );
}

// Transient confirmation (bottom-right on desktop, bottom on mobile).
export function Toast({ children, action, onClose }) {
  useEffect(() => {
    const t = setTimeout(onClose, 8000);
    return () => clearTimeout(t);
  }, [onClose]);
  return (
    <div role="status" className="fixed inset-x-4 bottom-4 z-50 flex items-center gap-3 rounded-xl border border-line bg-surface-raised p-4 shadow-panel sm:inset-x-auto sm:right-6 sm:bottom-6 sm:max-w-sm">
      <Icon name="check" className="size-5 shrink-0 text-fg" />
      <p className="flex-1 text-body text-fg">{children}</p>
      {action}
      <button type="button" onClick={onClose} aria-label="Dismiss" className={`rounded p-1 text-fg-muted hover:text-fg ${focusRing}`}>
        <Icon name="x" className="size-4" />
      </button>
    </div>
  );
}
