// Class recipes from the design system (DESIGN_SYSTEM.md). Accent colour is
// referenced only through the `accent` token (see theme.css).

export const focusRing = 'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent';

const btnBase = `inline-flex items-center justify-center gap-2 rounded-control px-4 text-body font-semibold transition-colors duration-150 ${focusRing} disabled:cursor-not-allowed disabled:bg-surface-overlay disabled:text-fg-disabled disabled:shadow-none disabled:ring-0`;

export const btn = {
  primary: `${btnBase} h-10 bg-accent text-on-accent hover:bg-accent-hover`,
  secondary: `${btnBase} h-10 bg-surface-overlay text-fg ring-1 ring-inset ring-line-strong hover:bg-line-strong`,
  ghost: `${btnBase} h-10 text-fg-secondary hover:bg-surface-overlay hover:text-fg`,
  danger: `${btnBase} h-10 bg-status-danger-bg text-status-danger ring-1 ring-inset ring-risk-high-ring hover:bg-risk-high-ring/40`,
};

export const card = 'rounded-card border border-line bg-surface-raised/70 shadow-card';

export const label = 'text-label uppercase tracking-label text-fg-muted';

export const input =
  'h-11 w-full rounded-lg border border-line-input bg-surface-base px-3 text-body text-fg placeholder:text-fg-muted outline-none transition-colors focus-visible:border-accent focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent aria-invalid:border-risk-high disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:text-fg-muted';

export const container = 'mx-auto w-full max-w-7xl px-4 sm:px-6 lg:px-8';

export const APP_NAME = 'Soccer Analytics';
