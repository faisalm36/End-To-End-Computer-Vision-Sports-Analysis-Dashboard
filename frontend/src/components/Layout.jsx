import { Link, Outlet } from 'react-router';
import { APP_NAME, container, focusRing } from './classes';
import { useAuth } from '../auth/useAuth';
import NavBar from './NavBar';

const YEAR = new Date().getFullYear();

export function Footer() {
  const year = YEAR;
  const { isAuthenticated } = useAuth();
  const link = `rounded text-body text-fg-muted hover:text-fg ${focusRing}`;
  return (
    <footer className="border-t border-line">
      <div className={`${container} flex flex-col gap-4 py-8 sm:flex-row sm:items-center sm:justify-between`}>
        <p className="text-caption text-fg-muted">
          © {year} {APP_NAME}. Built by Faisal Musa.
        </p>
        <nav aria-label="Footer" className="flex flex-wrap gap-x-6 gap-y-2">
          <Link to="/" className={link}>Home</Link>
          <Link to="/upload" className={link}>Upload</Link>
          <Link to="/dashboard" className={link}>Dashboard</Link>
          <Link to="/players" className={link}>Players</Link>
          {isAuthenticated ? <Link to="/profile" className={link}>Profile</Link> : <Link to="/signup" className={link}>Sign up</Link>}
        </nav>
      </div>
    </footer>
  );
}

export default function Layout() {
  return (
    <div className="flex min-h-screen flex-col bg-surface-base font-sans text-fg antialiased">
      <a href="#main" className={`sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-control focus:bg-accent focus:px-4 focus:py-2 focus:text-on-accent`}>
        Skip to content
      </a>
      <NavBar />
      <main id="main" className="flex-1">
        <Outlet />
      </main>
      <Footer />
    </div>
  );
}
