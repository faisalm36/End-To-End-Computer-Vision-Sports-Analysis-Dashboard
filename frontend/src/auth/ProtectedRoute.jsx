import { Navigate, Outlet, useLocation } from 'react-router';
import { useAuth } from './useAuth';

// Redirects to /login, remembering where the user was headed.
export default function ProtectedRoute() {
  const { isAuthenticated } = useAuth();
  const location = useLocation();
  if (!isAuthenticated) {
    const from = `${location.pathname}${location.search}${location.hash}`;
    return <Navigate to="/login" replace state={{ from }} />;
  }
  return <Outlet />;
}
