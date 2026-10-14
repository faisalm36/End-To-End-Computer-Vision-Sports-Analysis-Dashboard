import { screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import Players from '../pages/Players';
import { ME, mockFetch, signIn } from '../test/mockApi';
import { renderRoutes } from '../test/render';

const TEAM = { team_id: 1, team_name: 'Capstone FC', league: 'College Premier', created_at: '2026-09-01T12:00:00Z' };
const ROSTER = [
  { player_id: 21, team_id: 1, first_name: 'Faisal', last_name: 'Musa', jersey_number: 10, position: 'MF', dominant_foot: 'Right', contract_end_date: '2027-06-30', created_at: '2026-09-01T12:00:00Z', team: TEAM },
  { player_id: 7, team_id: 1, first_name: 'Luka', last_name: 'Petrovic', jersey_number: 7, position: 'FW', dominant_foot: 'Left', contract_end_date: null, created_at: '2026-09-01T12:00:00Z', team: TEAM },
  { player_id: 30, team_id: 1, first_name: 'Unknown', last_name: '', jersey_number: null, position: 'Unassigned', dominant_foot: null, contract_end_date: null, created_at: '2026-10-01T12:00:00Z', team: TEAM },
];

function setup(routes = {}) {
  signIn();
  const api = mockFetch({ 'GET /api/auth/me': ME, 'GET /api/players': [200, ROSTER], ...routes });
  const utils = renderRoutes({ at: '/players', protectedRoutes: { '/players': <Players /> } });
  return { api, ...utils };
}

describe('Players page (A4)', () => {
  it('lists players grouped by team with jersey nulls last', async () => {
    const { container } = setup();
    await screen.findByRole('heading', { name: 'Capstone FC' });
    const rows = container.querySelectorAll('[data-player]');
    expect(rows).toHaveLength(3);
    // jersey 7, 10, then null
    expect([...rows].map((r) => r.getAttribute('data-player'))).toEqual(['7', '21', '30']);
    expect(screen.getAllByText('Faisal Musa').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Unassigned').length).toBeGreaterThan(0);
  });

  it('edits a player and PATCHes only changed fields', async () => {
    const updated = { ...ROSTER[0], position: 'AM', dominant_foot: 'Both' };
    const { api, user } = setup({ 'PATCH /api/players/21': updated });
    await screen.findAllByText('Faisal Musa');
    // Desktop table: players sorted 7, 10, 30 — Edit for #10 is index 1 among visible desktop buttons.
    // jsdom doesn't apply Tailwind breakpoints, so both mobile and desktop Edits are in the DOM (6 total).
    const edits = screen.getAllByRole('button', { name: 'Edit' });
    await user.click(edits[1]);
    const drawer = screen.getByRole('dialog');
    await user.clear(within(drawer).getByLabelText('Position'));
    await user.type(within(drawer).getByLabelText('Position'), 'AM');
    await user.selectOptions(within(drawer).getByLabelText('Dominant foot'), 'Both');
    await user.click(within(drawer).getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(api.find('PATCH', '/api/players/21')).toHaveLength(1));
    expect(api.find('PATCH', '/api/players/21')[0].body).toEqual({ position: 'AM', dominant_foot: 'Both' });
    expect(await screen.findByText('Player saved.')).toBeInTheDocument();
    expect(screen.getByText('AM')).toBeInTheDocument();
  });

  it('shows a clear 409 when the jersey is already taken', async () => {
    const { user } = setup({ 'PATCH /api/players/21': [409, { detail: 'Jersey number 7 is already taken on this team' }] });
    await screen.findAllByText('Faisal Musa');
    await user.click(screen.getAllByRole('button', { name: 'Edit' })[1]);
    const drawer = screen.getByRole('dialog');
    await user.clear(within(drawer).getByLabelText('Jersey number'));
    await user.type(within(drawer).getByLabelText('Jersey number'), '7');
    await user.click(within(drawer).getByRole('button', { name: 'Save' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/already taken on this team/);
  });

  it('404 from GET /api/players shows the unavailable state (older backends)', async () => {
    setup({ 'GET /api/players': [404, { detail: 'Not Found' }] });
    expect(await screen.findByRole('heading', { name: /isn’t available on this server yet/ })).toBeInTheDocument();
    expect(document.querySelector('[data-unavailable]')).toBeInTheDocument();
  });
});
