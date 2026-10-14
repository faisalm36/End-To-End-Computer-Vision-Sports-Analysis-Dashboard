// Render helpers: real AuthProvider + routes inside a MemoryRouter (test-only file).
/* oxlint-disable react/only-export-components */
import { render } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router';
import AuthProvider from '../auth/AuthProvider';
import ProtectedRoute from '../auth/ProtectedRoute';

// Shows where the router ended up, so tests can assert redirects.
export function LocationProbe() {
  const loc = useLocation();
  return <output data-testid="location">{loc.pathname}</output>;
}

const Stub = ({ name }) => <h1>{name} page</h1>;

// routes: { '/login': <Login />, ... } public; protected: { '/upload': <Upload /> }.
// Unlisted protected targets render a "<path> page" heading.
export function renderRoutes({ at = '/', routes = {}, protectedRoutes = {}, stubs = [], userOptions = {} } = {}) {
  const user = userEvent.setup(userOptions);
  const utils = render(
    <MemoryRouter initialEntries={[at]}>
      <AuthProvider>
        <Routes>
          {Object.entries(routes).map(([path, el]) => (
            <Route key={path} path={path} element={el} />
          ))}
          <Route element={<ProtectedRoute />}>
            {Object.entries(protectedRoutes).map(([path, el]) => (
              <Route key={path} path={path} element={el} />
            ))}
            {stubs.map((path) => (
              <Route key={path} path={path} element={<Stub name={path} />} />
            ))}
          </Route>
        </Routes>
        <LocationProbe />
      </AuthProvider>
    </MemoryRouter>,
  );
  return { user, ...utils };
}
