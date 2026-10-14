import { startTransition, useEffect, useRef, useState } from 'react';
import { Link, NavLink, useNavigate } from 'react-router';
import { useAuth } from '../auth/useAuth';
import { displayName, initials } from '../lib/format';
import { APP_NAME, btn, container, focusRing } from './classes';
import { Icon, Logo } from './ui';

const LINKS = [
  { to: '/dashboard', label: 'Dashboard' },
  { to: '/players', label: 'Players' },
  { to: '/roster', label: 'Roster risk' },
  { to: '/upload', label: 'Upload' },
  { to: '/insights', label: 'Insights' },
  { to: '/profile', label: 'Profile' },
];

const navLinkClass = ({ isActive }) =>
  `rounded-control px-3 py-2 text-body font-medium transition-colors ${focusRing} ${
    isActive ? 'bg-surface-overlay text-fg shadow-[inset_0_-2px_0_var(--color-accent)]' : 'text-fg-secondary hover:bg-surface-overlay hover:text-fg'
  }`;

function AvatarMenu({ user, onLogout }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const onDoc = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    };
    const onKey = (e) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDoc);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const display = displayName(user) || 'Account';
  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Account menu for ${display}`}
        onClick={() => setOpen((o) => !o)}
        className={`flex size-9 items-center justify-center rounded-full bg-surface-overlay text-caption font-semibold text-fg ring-1 ring-line-strong hover:ring-fg-muted ${focusRing}`}
      >
        {initials(displayName(user, { fallbackToEmail: false }) || user?.email)}
      </button>
      {open && (
        <div role="menu" className="absolute right-0 mt-2 w-56 overflow-hidden rounded-xl border border-line bg-surface-raised p-1 shadow-panel">
          <p className="truncate px-3 py-2 text-caption text-fg-muted">{user?.email || display}</p>
          <Link role="menuitem" to="/profile" onClick={() => setOpen(false)} className={`block rounded-lg px-3 py-2 text-body text-fg-secondary hover:bg-surface-overlay hover:text-fg ${focusRing}`}>
            Profile
          </Link>
          <button role="menuitem" type="button" onClick={onLogout} className={`block w-full rounded-lg px-3 py-2 text-left text-body text-fg-secondary hover:bg-surface-overlay hover:text-fg ${focusRing}`}>
            Log out
          </button>
        </div>
      )}
    </div>
  );
}

export default function NavBar() {
  const { isAuthenticated, isDemo, user, logout } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);
  const navigate = useNavigate();

  // Close the mobile sheet on Escape (and when a link inside it is chosen).
  useEffect(() => {
    if (!menuOpen) return undefined;
    const onKey = (e) => e.key === 'Escape' && setMenuOpen(false);
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [menuOpen]);

  const handleLogout = () => {
    // Router navigations run as transitions; clear the session in the same
    // transition so protected pages don't bounce to /login on the way out.
    navigate('/', { replace: true });
    startTransition(() => logout());
  };

  return (
    <header className="sticky top-0 z-40 border-b border-line bg-surface-base/80 backdrop-blur">
      <nav aria-label="Main" className={`${container} flex h-16 items-center justify-between gap-4`}>
        <Link to="/" className={`flex items-center gap-2.5 rounded-lg ${focusRing}`}>
          <Logo />
          <span className="text-body font-semibold tracking-tight text-fg">{APP_NAME}</span>
          {isDemo && (
            <span className="rounded-chip bg-risk-medium-bg px-2 py-0.5 text-caption font-medium text-status-warning ring-1 ring-inset ring-risk-medium-ring">
              Demo
            </span>
          )}
        </Link>

        {isAuthenticated && (
          <div className="hidden items-center gap-1 lg:flex">
            {LINKS.map((l) => (
              <NavLink key={l.to} to={l.to} className={navLinkClass}>
                {l.label}
              </NavLink>
            ))}
          </div>
        )}

        <div className="hidden items-center gap-2 lg:flex">
          {isAuthenticated ? (
            <AvatarMenu user={user} onLogout={handleLogout} />
          ) : (
            <>
              <Link to="/login" className={btn.ghost}>
                Log in
              </Link>
              <Link to="/signup" className={btn.primary}>
                Sign up
              </Link>
            </>
          )}
        </div>

        <button
          type="button"
          className={`inline-flex size-10 items-center justify-center rounded-control text-fg-secondary hover:bg-surface-overlay hover:text-fg lg:hidden ${focusRing}`}
          aria-expanded={menuOpen}
          aria-controls="mobile-menu"
          aria-label={menuOpen ? 'Close menu' : 'Open menu'}
          onClick={() => setMenuOpen((o) => !o)}
        >
          <Icon name={menuOpen ? 'x' : 'menu'} className="size-6" />
        </button>
      </nav>

      {menuOpen && (
        <div
          id="mobile-menu"
          className="border-t border-line bg-surface-raised shadow-panel lg:hidden"
          onClick={(e) => {
            if (e.target.closest('a')) setMenuOpen(false);
          }}
        >
          <div className={`${container} flex flex-col gap-1 py-4`}>
            {isAuthenticated ? (
              <>
                <p className="px-3 pb-2 text-caption text-fg-muted">Signed in as {user?.email || user?.name || 'you'}</p>
                {LINKS.map((l) => (
                  <NavLink key={l.to} to={l.to} className={navLinkClass}>
                    {l.label}
                  </NavLink>
                ))}
                <button type="button" onClick={handleLogout} className={`${btn.secondary} mt-3 w-full`}>
                  Log out
                </button>
              </>
            ) : (
              <div className="flex flex-col gap-2">
                <Link to="/login" className={`${btn.secondary} w-full`}>
                  Log in
                </Link>
                <Link to="/signup" className={`${btn.primary} w-full`}>
                  Sign up
                </Link>
              </div>
            )}
          </div>
        </div>
      )}
    </header>
  );
}
