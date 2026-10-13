import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  DEMO_SESSION_TOKEN,
  decodeJwt,
  fetchMe,
  getToken,
  getTokenExpiry,
  isDemoToken,
  login as apiLogin,
  onUnauthorized,
  register as apiRegister,
  setToken,
} from '../lib/api';
import { AuthContext } from './authContext';

const DEMO_USER = { id: 'demo', name: 'Demo Coach', email: 'demo@example.com', created_at: null, demo: true };

// The JWT only carries sub/type/iat/exp, so user details always come from the
// login/register response and GET /api/auth/me (no JWT-claim fallback).
function initialUser(token) {
  if (!token) return null;
  return isDemoToken(token) ? DEMO_USER : {};
}

// Expiry comes from the login response's expires_in (stored), falling back to
// the JWT's exp claim.
function expiryOf(token) {
  if (!token || isDemoToken(token)) return null;
  const stored = getTokenExpiry();
  if (stored) return stored;
  const claims = decodeJwt(token);
  return claims?.exp ? claims.exp * 1000 : null;
}

function isExpired(token) {
  const at = expiryOf(token);
  return Boolean(at && at <= Date.now());
}

export default function AuthProvider({ children }) {
  const [token, setTokenState] = useState(() => {
    const t = getToken();
    if (isExpired(t)) {
      setToken(null);
      return null;
    }
    return t;
  });
  const [user, setUser] = useState(() => initialUser(token));
  const [profileError, setProfileError] = useState(null);

  const applySession = useCallback((newToken, newUser, expiresAt = null) => {
    setToken(newToken, expiresAt);
    setTokenState(newToken);
    setUser(newUser ? { ...newUser } : initialUser(newToken));
  }, []);

  const logout = useCallback(() => {
    setToken(null);
    setTokenState(null);
    setUser(null);
  }, []);

  // Any 401 from an authenticated call ends the session.
  useEffect(() => onUnauthorized(logout), [logout]);

  // Log out automatically when the token expires.
  useEffect(() => {
    const at = expiryOf(token);
    if (!at) return undefined;
    // setTimeout caps at ~24.8 days; longer sessions are re-checked on load.
    const ms = Math.min(Math.max(0, at - Date.now()), 2 ** 31 - 1);
    const t = setTimeout(logout, ms);
    return () => clearTimeout(t);
  }, [token, logout]);

  // Refresh the profile from GET /api/auth/me.
  const refreshUser = useCallback(
    async (signal) => {
      if (!token || isDemoToken(token)) return;
      try {
        const me = await fetchMe({ signal });
        if (me) setUser((prev) => ({ ...prev, ...me }));
        setProfileError(null);
      } catch (err) {
        if (err?.kind === 'abort') return;
        setProfileError(err);
      }
    },
    [token],
  );

  useEffect(() => {
    if (!token || isDemoToken(token)) return undefined;
    const controller = new AbortController();
    fetchMe({ signal: controller.signal })
      .then((me) => {
        if (me) setUser((prev) => ({ ...prev, ...me }));
        setProfileError(null);
      })
      .catch((err) => {
        if (err?.kind !== 'abort') setProfileError(err);
      });
    return () => controller.abort();
  }, [token]);

  const login = useCallback(
    async (email, password) => {
      const { token: t, user: u, expiresAt } = await apiLogin(email, password);
      applySession(t, u ?? { email }, expiresAt); // login returns user; /me refreshes it
    },
    [applySession],
  );

  const register = useCallback(
    async (fields) => {
      const { token: t, user: u, expiresAt } = await apiRegister(fields);
      applySession(t, u ?? { email: fields.email, name: fields.name || null }, expiresAt);
    },
    [applySession],
  );

  const startDemo = useCallback(() => applySession(DEMO_SESSION_TOKEN, DEMO_USER), [applySession]);

  const value = useMemo(
    () => ({
      token,
      user,
      isAuthenticated: Boolean(token),
      isDemo: isDemoToken(token),
      profileError,
      login,
      register,
      logout,
      startDemo,
      refreshUser,
      setUser,
    }),
    [token, user, profileError, login, register, logout, startDemo, refreshUser],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
