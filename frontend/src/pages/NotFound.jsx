import { Link } from 'react-router';
import { btn, container } from '../components/classes';

export default function NotFound() {
  return (
    <section className={`${container} flex min-h-[60vh] flex-col items-center justify-center py-20 text-center`}>
      <p className="font-mono text-kpi tabular-nums text-fg-muted">404</p>
      <h1 className="mt-3 text-headline text-fg">Page not found</h1>
      <p className="mt-2 max-w-md text-body text-fg-muted">The page you’re looking for doesn’t exist or has moved.</p>
      <div className="mt-8 flex gap-3">
        <Link to="/" className={btn.primary}>Go home</Link>
        <Link to="/dashboard" className={btn.secondary}>Open dashboard</Link>
      </div>
    </section>
  );
}
