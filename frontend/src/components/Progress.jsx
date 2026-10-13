import { btn, focusRing } from './classes';
import { STEPS, stepLabel, stepState } from '../lib/progressSteps';
import { Icon } from './ui';

// Report-issue target (placeholder mailbox; change when there is a real one).
export const REPORT_ISSUE_EMAIL = 'support@example.com';

export function ProgressBar({ value, labelText, tone = 'accent', thin = false }) {
  const indeterminate = value == null || !Number.isFinite(value);
  const v = indeterminate ? 0 : Math.max(0, Math.min(100, value));
  return (
    <div
      role="progressbar"
      aria-label={labelText}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={indeterminate ? undefined : Math.round(v)}
      className={`relative ${thin ? 'h-1' : 'h-2'} overflow-hidden rounded-full bg-surface-sunken ring-1 ring-inset ring-line`}
    >
      {indeterminate ? (
        <div className="skeleton absolute inset-0 rounded-full" />
      ) : (
        <div
          className={`h-full rounded-full transition-[width] duration-300 ${tone === 'danger' ? 'bg-risk-high' : tone === 'neutral' ? 'bg-slate-400' : 'bg-accent'}`}
          style={{ width: `${v}%` }}
        />
      )}
    </div>
  );
}

function Stepper({ progress }) {
  const { current, failedAt, waiting } = stepState(progress);
  return (
    <ol className="flex flex-wrap items-start gap-x-1 gap-y-3 sm:flex-nowrap">
      {STEPS.map((label, i) => {
        const failed = failedAt === i;
        const done = failedAt != null ? i < failedAt : i < current || current >= 5;
        const isCurrent = !failed && failedAt == null && i === current && current < 5;
        return (
          <li
            key={label}
            aria-current={isCurrent ? 'step' : undefined}
            className="flex min-w-[30%] flex-1 items-start gap-2 sm:min-w-0 sm:flex-col sm:items-center sm:text-center"
          >
            <span
              className={`relative flex size-6 shrink-0 items-center justify-center rounded-full ${
                failed
                  ? 'bg-risk-high-bg text-risk-high ring-2 ring-risk-high'
                  : done
                    ? 'bg-slate-800 text-slate-100 ring-1 ring-slate-600'
                    : isCurrent
                      ? 'bg-accent/10 ring-2 ring-accent'
                      : 'ring-1 ring-slate-600'
              }`}
            >
              {failed ? (
                <Icon name="x" className="size-3.5" />
              ) : done ? (
                <Icon name="check" className="size-3.5" />
              ) : isCurrent ? (
                <span className={`size-2 rounded-full bg-accent ${waiting ? '' : 'animate-pulse'}`} />
              ) : null}
            </span>
            <span
              className={`text-caption ${failed ? 'font-medium text-risk-high' : done ? 'text-slate-100' : isCurrent ? 'font-medium text-fg' : 'text-slate-400'}`}
            >
              {label}
              {isCurrent && waiting ? ' (queued)' : ''}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

const fmtInt = (n) => Math.round(n).toLocaleString();

function formatEta(sec) {
  if (!Number.isFinite(sec) || sec <= 0) return null;
  if (sec < 60) return 'under a minute left';
  const m = Math.round(sec / 60);
  return m < 60 ? `~${m} min left` : `~${Math.floor(m / 60)} h ${m % 60} min left`;
}

// Full processing panel: stepper, bar, mono detail line and failure actions.
export function ProcessingStatus({ progress, error, onRetry, retryLabel = 'Retry', videoRef, eta = null }) {
  const { phase, percent, message, frames } = progress;
  const active = phase === 'processing' || phase === 'queued';
  const failed = phase === 'failed';
  const bits = [];
  if (frames) bits.push(`Frame ${fmtInt(frames.done)} / ${fmtInt(frames.total)}`);
  if (percent != null && !frames) bits.push(`${Math.round(percent)}%`);
  const etaText = active ? formatEta(eta) : null;
  if (etaText) bits.push(etaText);

  return (
    <div>
      <Stepper progress={progress} />
      <div className="mt-5">
        <ProgressBar value={failed ? percent ?? 0 : percent} labelText="Processing progress" tone={failed ? 'danger' : 'accent'} />
      </div>
      <div className="mt-2 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <p className="text-body font-medium text-fg" aria-live="polite">
          {stepLabel(progress)}
          {active ? '…' : ''}
        </p>
        {bits.length > 0 && <p className="font-mono text-caption tabular-nums text-fg-secondary">{bits.join(' · ')}</p>}
      </div>
      {message && <p className="mt-1 text-caption text-fg-muted">{message}</p>}
      {active && <p className="mt-3 text-caption text-fg-muted">You can leave this page; processing continues.</p>}
      {failed && (
        <div className="mt-4 rounded-xl bg-status-danger-bg p-4 ring-1 ring-inset ring-risk-high-ring">
          <p className="text-body font-medium text-status-danger">Processing failed</p>
          <p className="mt-1 text-body text-fg-secondary">{error || 'The server could not analyze this video.'}</p>
          <div className="mt-3 flex flex-wrap gap-2">
            {/* The backend has no retry-from-step yet, so only a plain retry is offered. */}
            {onRetry && (
              <button type="button" onClick={onRetry} className={`${btn.secondary} h-9`}>
                {retryLabel}
              </button>
            )}
            <a
              href={`mailto:${REPORT_ISSUE_EMAIL}?subject=${encodeURIComponent(`Processing failed${videoRef ? ` (video ${videoRef})` : ''}`)}&body=${encodeURIComponent(`Error: ${error || 'unknown'}`)}`}
              className={`${btn.ghost} h-9 ${focusRing}`}
            >
              Report issue
            </a>
          </div>
        </div>
      )}
    </div>
  );
}

// Compact cell for the history table: stage name + thin bar.
export function CompactProgress({ progress }) {
  const failed = progress.phase === 'failed';
  return (
    <div className="w-36">
      <p className={`text-caption ${failed ? 'text-status-danger' : 'text-fg-secondary'}`}>{stepLabel(progress)}</p>
      <div className="mt-1">
        <ProgressBar thin value={progress.percent} labelText="Processing progress" tone={failed ? 'danger' : 'accent'} />
      </div>
    </div>
  );
}
