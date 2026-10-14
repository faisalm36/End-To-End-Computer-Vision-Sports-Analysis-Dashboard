import { screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { onUnauthorized } from '../lib/api';
import Login from '../pages/Login';
import Signup from '../pages/Signup';
import { ME, mockFetch, signIn } from '../test/mockApi';
import { renderRoutes } from '../test/render';

const where = () => screen.getByTestId('location').textContent;

function renderLogin(at = '/login') {
  return renderRoutes({ at, routes: { '/login': <Login />, '/signup': <Signup /> }, stubs: ['/profile', '/upload', '/insights'] });
}

describe('Login', () => {
  it('validates email and password on blur, before any request', async () => {
    const api = mockFetch();
    const { user } = renderLogin();
    const email = screen.getByLabelText('Email');
    await user.click(email);
    await user.tab(); // blur empty email
    expect(await screen.findByText('Enter your email address.')).toBeInTheDocument();
    expect(email).toHaveAttribute('aria-invalid', 'true');

    await user.type(email, 'not-an-email');
    expect(screen.getByText('Enter a valid email, like name@example.com.')).toBeInTheDocument(); // re-validates while fixing

    await user.click(screen.getByLabelText('Password'));
    await user.tab(); // blur empty password
    expect(screen.getByText('Enter your password.')).toBeInTheDocument();

    await user.clear(email);
    await user.type(email, 'coach@example.com');
    expect(screen.queryByText(/valid email/)).not.toBeInTheDocument();
    expect(api.calls).toHaveLength(0);
  });

  it('shows a 401 inline, keeps the form, stores nothing and does not trigger a logout', async () => {
    const api = mockFetch({ 'POST /api/auth/login': [401, { detail: 'Invalid credentials' }] });
    const unauthorized = vi.fn();
    const off = onUnauthorized(unauthorized);
    const { user } = renderLogin();
    await user.type(screen.getByLabelText('Email'), 'faisal@example.com');
    await user.type(screen.getByLabelText('Password'), 'wrongpass1');
    await user.click(screen.getByRole('button', { name: 'Log in' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Could not log you in');
    expect(alert).toHaveTextContent('Incorrect email or password.');
    expect(alert).not.toHaveTextContent(/session has expired/i);
    expect(where()).toBe('/login');
    expect(screen.getByLabelText('Email')).toHaveValue('faisal@example.com');
    expect(localStorage.getItem('sca.token')).toBeNull();
    expect(unauthorized).not.toHaveBeenCalled();
    expect(api.find('GET', '/api/auth/me')).toHaveLength(0);
    expect(api.find('POST', '/api/auth/login')[0].body).toEqual({ email: 'faisal@example.com', password: 'wrongpass1' });
    off();
  });

  it('stores the token on success and redirects to /profile', async () => {
    mockFetch({
      'POST /api/auth/login': { access_token: 'jwt-123', token_type: 'bearer', expires_in: 3600, user: ME },
      'GET /api/auth/me': ME,
    });
    const { user } = renderLogin();
    await user.type(screen.getByLabelText('Email'), 'faisal@example.com');
    await user.type(screen.getByLabelText('Password'), 'capstone123');
    await user.click(screen.getByRole('button', { name: 'Log in' }));

    expect(await screen.findByRole('heading', { name: '/profile page' })).toBeInTheDocument();
    expect(where()).toBe('/profile');
    expect(localStorage.getItem('sca.token')).toBe('jwt-123');
    expect(Number(localStorage.getItem('sca.token_expires_at'))).toBeGreaterThan(Date.now());
  });

  it('offers sample data when the backend is unreachable', async () => {
    mockFetch({ 'POST /api/auth/login': 'network-error' });
    const { user } = renderLogin();
    await user.type(screen.getByLabelText('Email'), 'faisal@example.com');
    await user.type(screen.getByLabelText('Password'), 'capstone123');
    await user.click(screen.getByRole('button', { name: 'Log in' }));
    expect(await screen.findByText('Backend not reachable')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Explore with sample data' })).toBeInTheDocument();
  });
});

describe('Protected routes', () => {
  it('redirects to /login and returns to the requested page after logging in', async () => {
    mockFetch({
      'POST /api/auth/login': { access_token: 'jwt-abc', expires_in: 3600, user: ME },
      'GET /api/auth/me': ME,
    });
    const { user } = renderLogin('/insights');
    expect(where()).toBe('/login');
    expect(screen.getByRole('heading', { name: 'Welcome back' })).toBeInTheDocument();

    await user.type(screen.getByLabelText('Email'), 'faisal@example.com');
    await user.type(screen.getByLabelText('Password'), 'capstone123');
    await user.click(screen.getByRole('button', { name: 'Log in' }));
    expect(await screen.findByRole('heading', { name: '/insights page' })).toBeInTheDocument();
  });

  it('lets a signed-in user straight through', async () => {
    signIn();
    mockFetch({ 'GET /api/auth/me': ME });
    renderLogin('/upload');
    expect(await screen.findByRole('heading', { name: '/upload page' })).toBeInTheDocument();
  });

  it('ends the session when an authenticated request gets a 401', async () => {
    signIn('expired-token');
    mockFetch({ 'GET /api/auth/me': [401, { detail: 'Could not validate credentials' }] });
    renderLogin('/upload');
    await waitFor(() => expect(where()).toBe('/login'));
    expect(localStorage.getItem('sca.token')).toBeNull();
  });
});

describe('Signup', () => {
  it('validates on blur: short password and mismatched confirmation', async () => {
    const api = mockFetch();
    const { user } = renderLogin('/signup');
    await user.type(screen.getByLabelText('Password'), 'short');
    await user.tab();
    expect(screen.getByText('Use at least 8 characters.')).toBeInTheDocument();
    await user.type(screen.getByLabelText('Confirm password'), 'different1');
    await user.tab();
    expect(screen.getByText('Passwords don’t match.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Create account' }));
    expect(screen.getByText('Enter your email address.')).toBeInTheDocument();
    expect(api.calls).toHaveLength(0);
  });

  it('registers, stores the token and goes to /upload', async () => {
    const api = mockFetch({
      'POST /api/auth/register': [201, { ...ME, access_token: 'jwt-new', token_type: 'bearer', expires_in: 3600, user: ME }],
      'GET /api/auth/me': ME,
    });
    const { user } = renderLogin('/signup');
    await user.type(screen.getByLabelText(/^Name/), 'Faisal Musa');
    await user.type(screen.getByLabelText('Email'), 'new@example.com');
    await user.type(screen.getByLabelText('Password'), 'longenough1');
    await user.type(screen.getByLabelText('Confirm password'), 'longenough1');
    await user.click(screen.getByRole('button', { name: 'Create account' }));

    expect(await screen.findByRole('heading', { name: '/upload page' })).toBeInTheDocument();
    expect(localStorage.getItem('sca.token')).toBe('jwt-new');
    expect(api.find('POST', '/api/auth/register')[0].body).toEqual({ name: 'Faisal Musa', email: 'new@example.com', password: 'longenough1' });
  });

  it('explains a 409 (email already registered)', async () => {
    mockFetch({ 'POST /api/auth/register': [409, { detail: 'Email already registered' }] });
    const { user } = renderLogin('/signup');
    await user.type(screen.getByLabelText('Email'), 'faisal@example.com');
    await user.type(screen.getByLabelText('Password'), 'longenough1');
    await user.type(screen.getByLabelText('Confirm password'), 'longenough1');
    await user.click(screen.getByRole('button', { name: 'Create account' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('An account with that email already exists. Try logging in.');
    expect(where()).toBe('/signup');
    expect(localStorage.getItem('sca.token')).toBeNull();
  });
});
