import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import Dashboard from '../Dashboard';
import Upload from '../pages/Upload';
import { FALLBACK_EXTENSIONS, getJerseyCorrections, saveJerseyCorrection } from '../lib/api';
import { normalizePlayerRow, normalizePlayers, videoThresholds } from '../lib/playerStats';
import { CONFIG, ME, mockFetch, signIn } from '../test/mockApi';
import { renderRoutes } from '../test/render';

const PATCH = '/api/videos/6/players/24';

describe('jersey corrections: PATCH /api/videos/{id}/players/{player_id} (v0.4.1)', () => {
  it('saves on the server and returns the stats row', async () => {
    signIn();
    const api = mockFetch({ [`PATCH ${PATCH}`]: { player_id: 24, jersey_number: 10 } });
    const res = await saveJerseyCorrection({ videoId: 6, playerId: 24, jersey: 10 });
    expect(res).toMatchObject({ mode: 'server', row: { jersey_number: 10 } });
    expect(api.find('PATCH', PATCH)[0].body).toEqual({ jersey_number: 10 });
    expect(getJerseyCorrections(6)).toEqual({});
  });

  it('null clears the number (sent as jersey_number: null)', async () => {
    signIn();
    const api = mockFetch({ [`PATCH ${PATCH}`]: { player_id: 24, jersey_number: null } });
    await saveJerseyCorrection({ videoId: 6, playerId: 24, jersey: null });
    expect(api.find('PATCH', PATCH)[0].body).toEqual({ jersey_number: null });
  });

  it.each([
    [404, /can’t store shirt-number corrections yet/],
    [405, /can’t store shirt-number corrections yet/],
    [503, /database update pending/],
  ])('%s falls back to a local-only override with a note', async (status, note) => {
    signIn();
    mockFetch({ [`PATCH ${PATCH}`]: [status, { detail: 'x' }] });
    const res = await saveJerseyCorrection({ videoId: 6, playerId: 24, jersey: 9 });
    expect(res.mode).toBe('local');
    expect(res.note).toMatch(note);
    expect(getJerseyCorrections(6)).toEqual({ 24: 9 });
  });

  it('a network error falls back locally too', async () => {
    signIn();
    mockFetch({ [`PATCH ${PATCH}`]: 'network-error' });
    const res = await saveJerseyCorrection({ videoId: 6, playerId: 24, jersey: 9 });
    expect(res).toMatchObject({ mode: 'local', note: expect.stringMatching(/Couldn’t reach the server/) });
  });

  it.each([409, 422])('%s rejects with the server message (shown inline)', async (status) => {
    signIn();
    mockFetch({ [`PATCH ${PATCH}`]: [status, { detail: '#10 is already used by a teammate in this video' }] });
    await expect(saveJerseyCorrection({ videoId: 6, playerId: 24, jersey: 10 })).rejects.toThrow('#10 is already used by a teammate in this video');
    expect(getJerseyCorrections(6)).toEqual({});
  });

  it('Dashboard: 409 shows inline in the form; success updates the number and says where it was saved', async () => {
    signIn();
    const user = userEvent.setup();
    mockFetch({
      'GET /api/metrics': [200, []],
      'PATCH /api/videos/6/players/1': (req) => (req.body.jersey_number === 7 ? [409, { detail: 'Shirt #7 is already used by another player in this video' }] : [200, { player_id: 1, jersey_number: req.body.jersey_number }]),
    });
    render(
      <Dashboard
        videoId={6}
        players={[
          { player_id: 1, name: 'Ivan Horvat', jersey_number: 4, top_speed_mph: 20, distance_km: 5 },
          { player_id: 2, name: 'Unknown #7', jersey_number: 7, top_speed_mph: 19, distance_km: 4 },
        ]}
      />,
    );
    await user.click(within(screen.getByRole('table')).getByText('Ivan Horvat'));
    await user.click(screen.getByRole('button', { name: 'Change' }));
    await user.clear(screen.getByLabelText('Shirt number'));
    await user.type(screen.getByLabelText('Shirt number'), '7');
    await user.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Shirt #7 is already used by another player in this video');
    expect(screen.getByLabelText('Shirt number')).toBeInTheDocument();
    await user.clear(screen.getByLabelText('Shirt number'));
    await user.type(screen.getByLabelText('Shirt number'), '11');
    await user.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByText('Saved for this video.')).toBeInTheDocument();
    expect(screen.getByText('Played as').parentElement).toHaveTextContent('Played as #11');
  });
});

describe('speed_thresholds.source and v0.4.1 numbers', () => {
  const th = (source) => ({ preset: 'gps_standard', hsr_kmh: 19.8, sprint_kmh: 25.3, zone_edges_kmh: { walk: 7, jog: 15, run: 19.8, hsr: 25.3 }, source });
  const dash = (players) => {
    mockFetch({ 'GET /api/metrics': [200, []] });
    return render(<Dashboard players={players} videoId="v" />);
  };
  it.each([
    ['pipeline', /^Speed thresholds used: GPS standard · HSR > 19\.8 km\/h · Sprint > 25\.3 km\/h · from the pipeline/],
    ['default', /^Default speed thresholds \(the pipeline didn’t report its own\): GPS standard/],
  ])('labels source=%s', (source, re) => {
    const { container } = dash([{ player_id: 1, name: 'A', speed_thresholds: th(source) }]);
    const el = container.querySelector('[data-thresholds]');
    expect(el).toHaveAttribute('data-thresholds', source);
    expect(el.querySelector('p').textContent).toMatch(re);
  });
  it('rows that disagree read as mixed', () => {
    const players = normalizePlayers([
      { player_id: 1, speed_thresholds: th('pipeline') },
      { player_id: 2, speed_thresholds: th('default') },
    ]);
    expect(videoThresholds(players).source).toBe('mixed');
    const { container } = dash([
      { player_id: 1, name: 'A', speed_thresholds: th('pipeline') },
      { player_id: 2, name: 'B', speed_thresholds: th('default') },
    ]);
    expect(container.querySelector('[data-thresholds]').textContent).toMatch(/^Speed thresholds \(mixed: pipeline values for some players, defaults for others\)/);
  });
  it('an explicit null distance_per_min is respected (not re-derived); minutes keep 2 decimals', () => {
    const r = normalizePlayerRow({ player_id: 1, distance_km: 0.5, minutes_played: 0.25, visible_minutes: 0.2, distance_per_min: null });
    expect(r.distance_per_min).toBeNull();
    expect(r.per_min_note).toBe('Clip too short for a per-minute rate');
    expect(r.minutes_played).toBe(0.25);
    const long = normalizePlayerRow({ player_id: 1, distance_km: 9, minutes_played: 90, distance_per_min: null });
    expect(long.distance_per_min).toBeNull();
    expect(long.per_min_note).toBe('Per-minute rate not available for this player');
    // Field absent (older servers): still derived.
    expect(normalizePlayerRow({ player_id: 1, distance_km: 9, minutes_played: 90 }).distance_per_min).toBe(100);
  });
  it('coverage badge shows short-clip minutes with 2 decimals', async () => {
    const user = userEvent.setup();
    dash([{ player_id: 1, name: 'Ivan', coverage_pct: 80, visible_minutes: 0.13, minutes_played: 0.17 }]);
    await user.click(within(screen.getByRole('table')).getByText('Ivan'));
    expect(screen.getByText('Tracked 80% of match · 0.13 of 0.17 min')).toBeInTheDocument();
  });
});

describe('upload: avi and mkv', () => {
  it('fallback extensions include avi and mkv when /api/config is unreachable', async () => {
    expect(FALLBACK_EXTENSIONS).toEqual(['mp4', 'mov', 'avi', 'mkv']);
    signIn();
    mockFetch({ 'GET /api/auth/me': ME, 'GET /api/matches': [200, []], 'GET /api/tags': [200, []] }); // /api/config -> 404
    const { container } = renderRoutes({ at: '/upload', protectedRoutes: { '/upload': <Upload /> } });
    expect(await screen.findByText(/\.mp4 · \.mov · \.avi · \.mkv/)).toBeInTheDocument();
    const f = new File(['x'], 'match.mkv', { type: 'video/x-matroska' });
    await act(async () => fireEvent.change(container.querySelector('input[type=file]'), { target: { files: [f] } }));
    await waitFor(() => expect(screen.getByLabelText('Match title')).toHaveValue('match'));
  });
  it('v0.4.1 config (avi + mkv) accepts an .avi', async () => {
    signIn();
    mockFetch({ 'GET /api/auth/me': ME, 'GET /api/config': CONFIG, 'GET /api/matches': [200, []], 'GET /api/tags': [200, []] });
    const { container } = renderRoutes({ at: '/upload', protectedRoutes: { '/upload': <Upload /> } });
    await screen.findByText(/^MP4, MOV, AVI or MKV, up to 500 MB\./);
    const f = new File(['x'], 'derby.avi', { type: 'video/x-msvideo' });
    await act(async () => fireEvent.change(container.querySelector('input[type=file]'), { target: { files: [f] } }));
    expect(screen.queryByRole('alert')).toBeNull();
  });
});
