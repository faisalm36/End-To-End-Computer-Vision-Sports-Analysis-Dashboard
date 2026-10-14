import { Link } from 'react-router';
import { APP_NAME, focusRing } from './classes';
import { Logo } from './ui';

export default function AuthCard({ title, subtitle, children, footer }) {
  return (
    <div className="relative flex min-h-[calc(100vh-4rem)] items-center justify-center overflow-hidden px-4 py-16">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(40%_35%_at_50%_30%,rgb(148_163_184/0.12),transparent)]"
      />
      <div className="relative w-full max-w-sm rounded-card border border-line bg-surface-raised/80 p-8 shadow-panel backdrop-blur">
        <Link to="/" className={`inline-flex items-center gap-2 rounded-lg ${focusRing}`} aria-label={`${APP_NAME} home`}>
          <Logo />
        </Link>
        <h1 className="mt-6 text-headline text-fg">{title}</h1>
        {subtitle && <p className="mt-1 text-body text-fg-muted">{subtitle}</p>}
        <div className="mt-6">{children}</div>
        {footer && <div className="mt-6 border-t border-line pt-5 text-center text-body text-fg-muted">{footer}</div>}
      </div>
    </div>
  );
}
