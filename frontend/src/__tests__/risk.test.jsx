import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import CsvUpload from '../pages/CsvUpload';
import RosterRisk from '../pages/RosterRisk';
import { csvErrorMessage, levelFor, missingColumnsFrom, mostlyUnscored, normalizeCsvUpload, normalizeFactors, normalizeRiskHistory, normalizeRosterRisk, sortByRisk } from '../lib/risk';
import { ME, mockFetch, signIn } from '../test/mockApi';
import { renderRoutes } from '../test/render';

const CFC = { team_id: 1, team_name: 'Capstone FC' };
const RIVAL = { team_id: 2, team_name: 'Rival United' };
const player = (o) => ({
  player_id: 1, name: 'P', first_name: 'P', last_name: '', jersey_number: null, position: 'MF', team: CFC, risk_percent: null, level: 'unknown',
  score_status: 'scored', score_note: null, data_quality: 'calibrated', source: 'match', match_id: 3, match_date: '2026-10-04', video_id: 3,
  model_version: 'lr-0.7', computed_at: '2026-10-05T09:00:00Z', features: { distance_km: 9.1, sprint_count: 20 }, factors: [], ...o,
});
// Thresholds deliberately not 70/40, to prove they come from the response.
const ROSTER = {
  team_id: null, match_id: null, sort: 'desc', model_version: 'lr-0.7', thresholds: { red: 60, yellow: 30 }, generated_at: '2026-10-08T12:00:00Z', latency_ms: 12,
  players: [
    player({ player_id: 1, name: 'Ana Low', jersey_number: 4, risk_percent: 20, level: 'green', data_quality: 'csv', source: 'csv' }),
    player({
      player_id: 2, name: 'Ben High', jersey_number: 9, risk_percent: 65, level: 'red',
      factors: [
        { feature: 'distance_km', label: 'Distance', value: 9.1, contribution: 0.3, direction: 'up' },
        { feature: 'sprint_count', label: 'Sprints', value: 20, contribution: 0.9, direction: 'up' },
        { feature: 'minutes_played', label: 'Minutes played', value: 45, contribution: -0.45, direction: 'down' },
      ],
    }),
    player({ player_id: 3, name: 'Cal Gated', risk_percent: null, level: 'unknown', score_status: 'uncalibrated', score_note: 'needs a custom pitch calibration', data_quality: null }),
    player({ player_id: 4, name: 'Dee Mid', team: RIVAL, risk_percent: 45, level: 'yellow', data_quality: 'demo' }),
  ],
};

describe('risk helpers', () => {
  it('derives level from response thresholds, server level wins, null is unknown', () => {
    const t = { red: 60, yellow: 30 };
    expect(levelFor(65, t)).toBe('red');
    expect(levelFor(60, t)).toBe('red');
    expect(levelFor(45, t)).toBe('yellow');
    expect(levelFor(10, t)).toBe('green');
    expect(levelFor(65, { red: 80, yellow: 50 })).toBe('yellow');
    expect(levelFor(10, t, 'red')).toBe('red');
    expect(levelFor(null, t, 'red')).toBe('unknown');
    expect(levelFor(50, null)).toBe('unknown');
    const r = normalizeRosterRisk({ thresholds: { red: 60, yellow: 30 }, players: [{ player_id: 1, risk_percent: 62 }] });
    expect(r.players[0].level).toBe('red');
  });

  it('gates non-scored players: no number, unknown level, note kept, sorted last', () => {
    const r = normalizeRosterRisk({
      thresholds: { red: 60, yellow: 30 },
      players: [
        { player_id: 1, name: 'A', risk_percent: 80, level: 'red', score_status: 'uncalibrated', score_note: 'needs a custom pitch calibration', data_quality: 'calibrated' },
        { player_id: 2, name: 'B', risk_percent: 10, level: 'green', score_status: 'scored', data_quality: 'demo' },
        { player_id: 3, name: 'C', risk_percent: null, score_status: 'insufficient_data', score_note: null, data_quality: 'bogus' },
      ],
    });
    const [a, b, c] = r.players;
    expect(a).toMatchObject({ risk_percent: null, level: 'unknown', score_status: 'uncalibrated', score_note: 'needs a custom pitch calibration' });
    expect(b).toMatchObject({ risk_percent: 10, level: 'green', score_status: 'scored', data_quality: 'demo' });
    expect(c).toMatchObject({ level: 'unknown', score_note: 'Not enough data to score', data_quality: null });
    expect(sortByRisk(r.players, 'desc').map((p) => p.name)).toEqual(['B', 'A', 'C']);
    expect(mostlyUnscored(r.players)).toBe(true);
    expect(mostlyUnscored([b])).toBe(false);
    expect(mostlyUnscored([])).toBe(true);
    const h = normalizeRiskHistory({ history: [{ risk_percent: 55, level: 'yellow', score_status: 'uncalibrated', score_note: 'x', data_quality: 'calibrated', match_date: '2026-10-01' }] });
    expect(h[0]).toMatchObject({ risk_percent: null, level: 'unknown', score_status: 'uncalibrated', data_quality: 'calibrated' });
  });

  it('sorts factors by |contribution| with relative bar widths (never percentages)', () => {
    const f = normalizeFactors([
      { feature: 'a', contribution: 0.2, direction: 'up' },
      { feature: 'b', contribution: -0.8 },
      { feature: 'c', contribution: 0.4, direction: 'down' },
    ]);
    expect(f.map((x) => x.feature)).toEqual(['b', 'c', 'a']);
    expect(f.map((x) => x.width)).toEqual([100, 50, 25]);
    expect(f[0].direction).toBe('down'); // from the sign when direction is missing
    expect(f[1].direction).toBe('down');
  });

  it('sorts by risk asc/desc with unknown always last', () => {
    const list = [{ name: 'U', risk_percent: null }, { name: 'L', risk_percent: 5 }, { name: 'H', risk_percent: 90 }];
    expect(sortByRisk(list, 'desc').map((p) => p.name)).toEqual(['H', 'L', 'U']);
    expect(sortByRisk(list, 'asc').map((p) => p.name)).toEqual(['L', 'H', 'U']);
  });

  it('parses CSV upload results and errors', () => {
    const r = normalizeCsvUpload({
      upload_id: null, dry_run: true, rows_total: 3, rows_valid: 1, rows_invalid: 1, rows_unmatched: 1, columns_detected: { date: 'Date', player: 'Player' },
      errors: [{ row: 2, column: 'date', value: 'yesterday', message: 'Invalid date' }], unmatched: [{ row: 3, player: 'Zed' }],
      results: [
        { row: 1, player_id: 21, name: 'Faisal Musa', date: '2026-10-06', risk_percent: 48, level: 'yellow', score_status: 'scored', factors: [] },
        { row: 4, player_id: 7, name: 'Luka', date: '2026-10-06', risk_percent: 90, level: 'red', score_status: 'insufficient_data', score_note: 'only 10 minutes logged' },
      ],
    });
    expect(r.dry_run).toBe(true);
    expect(r.errors[0]).toEqual({ row: 2, column: 'date', value: 'yesterday', message: 'Invalid date' });
    expect(r.results[0]).toMatchObject({ level: 'yellow', risk_percent: 48 });
    expect(r.results[1]).toMatchObject({ level: 'unknown', risk_percent: null, score_note: 'only 10 minutes logged' });
    const err422 = { status: 422, data: { detail: 'Missing required columns', missing_columns: ['date'] } };
    expect(missingColumnsFrom(err422)).toEqual(['date']);
    expect(r.columns_detected).toEqual(['date ← Date', 'player ← Player']);
    expect(csvErrorMessage({ status: 415, data: null })).toMatch(/UTF-8/);
    expect(csvErrorMessage({ status: 413, data: null })).toMatch(/5000 rows/);
    expect(csvErrorMessage({ status: 413, data: { detail: 'File exceeds 5000 rows' } })).toBe('File exceeds 5000 rows');
    expect(csvErrorMessage({ status: 415, data: { detail: 'File is not UTF-8' } })).toBe('File is not UTF-8');
    expect(csvErrorMessage({ status: 404, data: { detail: 'Not Found' } })).toMatch(/isn’t available on this server/);
    expect(csvErrorMessage({ status: 404, data: { detail: 'Team 9 not found' } })).toBe('Team 9 not found');
    expect(csvErrorMessage({ status: 503, data: { detail: 'Risk model unavailable: weights missing' } })).toMatch(/weights missing/);
    expect(csvErrorMessage({ status: 422, data: { detail: [{ msg: 'field required' }, { msg: 'type error' }] } })).toBe('field required; type error');
  });
});

function setupRoster(routes = {}, at = '/roster') {
  signIn();
  const api = mockFetch({ 'GET /api/auth/me': ME, 'GET /api/roster/risk': ROSTER, ...routes });
  const utils = renderRoutes({ at, protectedRoutes: { '/roster': <RosterRisk /> }, stubs: ['/roster/upload'] });
  return { api, ...utils };
}
const order = (c) => [...c.querySelectorAll('[data-risk-player]')].map((r) => r.getAttribute('data-risk-player'));

describe('Roster risk page', () => {
  it('lists players highest first with icon+text levels, thresholds from the response, unscored last', async () => {
    const { container } = setupRoster();
    await screen.findByText('Ben High');
    expect(order(container)).toEqual(['2', '4', '1', '3']);
    expect(container.querySelector('[data-risk-player="2"] [data-level="red"]')).toHaveTextContent('High65%');
    expect(container.querySelector('[data-risk-player="1"] [data-level="green"]')).toHaveTextContent('Low20%');
    // Gated player: neutral "Not scored" + the note, no number
    const gated = container.querySelector('[data-risk-player="3"]');
    expect(within(gated).getByText('Not scored')).toBeInTheDocument();
    expect(gated.querySelector('[data-level="unknown"]').textContent).not.toMatch(/%/);
    expect(gated.querySelector('[data-score-note="uncalibrated"]')).toHaveTextContent('needs a custom pitch calibration');
    expect(container.querySelector('[data-thresholds]')).toHaveTextContent('High ≥ 60%');
    expect(screen.getAllByText(/Workload indicator, not medical advice/).length).toBeGreaterThan(0);
    // data quality badges; demo data is marked and warned about
    expect(container.querySelector('[data-risk-player="1"] [data-quality="csv"]')).toHaveTextContent('Athlete log');
    expect(container.querySelector('[data-risk-player="2"] [data-quality="calibrated"]')).toHaveTextContent('Video (calibrated)');
    expect(container.querySelector('[data-risk-player="4"] [data-quality="demo"]')).toHaveTextContent('Demo data');
    expect(container.querySelector('[data-demo-warning]')).toBeInTheDocument();
    // 3 of 4 scored → no CSV call to action
    expect(container.querySelector('[data-csv-cta]')).toBeNull();
  });

  it('expands factors sorted by size with relative bars and direction labels', async () => {
    const { user, container } = setupRoster({ 'GET /api/players/2/risk': [200, []] });
    await screen.findByText('Ben High');
    await user.click(screen.getByRole('button', { name: 'Show factors for Ben High' }));
    const panel = container.querySelector('[data-risk-panel]');
    const bars = [...panel.querySelectorAll('[data-factor]')];
    expect(bars.map((b) => b.getAttribute('data-factor'))).toEqual(['sprint_count', 'minutes_played', 'distance_km']);
    expect(bars.map((b) => b.getAttribute('data-width'))).toEqual(['100', '50', '33']);
    expect(within(bars[1]).getByText('Lowers risk')).toBeInTheDocument();
    expect(within(bars[0]).getByText('Raises risk')).toBeInTheDocument();
    expect(panel.textContent).not.toMatch(/0\.9|90%/);
    expect(await within(panel).findByText('No earlier scores on this server.')).toBeInTheDocument();
  });

  it('shows the gated note instead of factors and history entries with status', async () => {
    const hist = { history: [{ risk_percent: null, level: 'unknown', score_status: 'uncalibrated', score_note: 'broadcast, no calibration', data_quality: null, match_date: '2026-10-01' }, { risk_percent: 33, level: 'yellow', score_status: 'scored', data_quality: 'csv', match_date: '2026-09-28' }] };
    const { user, container } = setupRoster({ 'GET /api/players/3/risk': hist });
    await screen.findByText('Cal Gated');
    await user.click(screen.getByRole('button', { name: 'Show factors for Cal Gated' }));
    const panel = container.querySelector('[data-risk-panel]');
    expect(within(panel).getAllByText('needs a custom pitch calibration').length).toBeGreaterThan(0);
    expect(within(panel).getByRole('link', { name: 'Upload a CSV' })).toHaveAttribute('href', '/roster/upload');
    const history = await within(panel).findByText('broadcast, no calibration');
    const list = history.closest('[data-history]');
    expect(list.querySelector('[data-quality="csv"]')).toBeInTheDocument();
    expect(list.querySelector('[data-level="yellow"]')).toHaveTextContent('Moderate33%');
  });

  it('sorts lowest first on toggle (unknown still last) and filters by team on the server', async () => {
    const rival = { ...ROSTER, team_id: 2, players: [ROSTER.players[3]] };
    const { user, container, api } = setupRoster({ 'GET /api/roster/risk': (req) => (req.params.get('team_id') === '2' ? rival : ROSTER) });
    await screen.findByText('Ben High');
    await user.click(screen.getByRole('button', { name: 'Lowest first' }));
    expect(order(container)).toEqual(['1', '4', '2', '3']);
    await user.selectOptions(screen.getByLabelText('Team'), '2');
    await waitFor(() => expect(order(container)).toEqual(['4']));
    expect(api.find('GET', '/api/roster/risk').at(-1).params.get('team_id')).toBe('2');
    // team list survives the filtered response
    expect(within(screen.getByLabelText('Team')).getByRole('option', { name: 'Capstone FC' })).toBeInTheDocument();
  });

  it('points the coach to the CSV upload when most of the roster is unscored', async () => {
    const mostly = {
      ...ROSTER,
      players: [
        player({ player_id: 5, name: 'Eve', risk_percent: null, score_status: 'no_data', score_note: null }),
        player({ player_id: 6, name: 'Fin', risk_percent: null, score_status: 'insufficient_data', score_note: 'only 1 match' }),
        player({ player_id: 7, name: 'Gus', risk_percent: 50, level: 'yellow' }),
      ],
    };
    const { container } = setupRoster({ 'GET /api/roster/risk': mostly });
    await screen.findByText('Eve');
    const cta = container.querySelector('[data-csv-cta]');
    expect(cta).toHaveTextContent('2 of 3 players have no workload score yet');
    expect(within(cta).getByRole('link', { name: /Upload athlete log/ })).toHaveAttribute('href', '/roster/upload');
    expect(container.querySelector('[data-risk-player="5"] [data-score-note]')).toHaveTextContent('No workload data yet');
  });

  it('empty roster also shows the CSV call to action', async () => {
    const { container } = setupRoster({ 'GET /api/roster/risk': { ...ROSTER, players: [] } });
    await waitFor(() => expect(container.querySelector('[data-csv-cta]')).toHaveTextContent('No workload scores yet'));
  });

  it('shows "not available on this server yet" on route-missing 404', async () => {
    const { container } = setupRoster({ 'GET /api/roster/risk': [404, { detail: 'Not Found' }] });
    await waitFor(() => expect(container.querySelector('[data-unavailable]')).toBeInTheDocument());
    expect(screen.getByText('Roster risk isn’t available on this server yet')).toBeInTheDocument();
  });

  it('shows the server reason on 503 (key/model unavailable)', async () => {
    setupRoster({ 'GET /api/roster/risk': [503, { detail: 'Risk model unavailable: weights missing' }] });
    expect(await screen.findByText('Risk scoring is unavailable')).toBeInTheDocument();
    expect(screen.getByText(/weights missing/)).toBeInTheDocument();
    expect(document.querySelector('[data-unavailable]')).toBeNull();
  });

  it('shows a 422 as an error with a way to clear filters', async () => {
    setupRoster({ 'GET /api/roster/risk': [422, { detail: [{ msg: 'sort must be asc or desc' }] }] }, '/roster?team_id=abc');
    expect(await screen.findByText('The server rejected these filters')).toBeInTheDocument();
    expect(screen.getByText(/sort must be asc or desc/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Clear filters' })).toBeInTheDocument();
  });
});

const PREVIEW = {
  upload_id: null, dry_run: true, filename: 'week40.csv', rows_total: 4, rows_valid: 2, rows_invalid: 1, rows_unmatched: 1, columns_detected: { date: 'Date', player: 'Player Name', gps_distance: 'GPS_Distance' },
  errors: [{ row: 3, column: 'gps_distance', value: '-4', message: 'must be ≥ 0' }],
  unmatched: [{ row: 4, player: 'Zed Nobody' }],
  results: [
    { row: 1, player_id: 21, name: 'Faisal Musa', date: '2026-10-06', risk_percent: 48, level: 'yellow', score_status: 'scored', data_quality: 'csv', factors: [{ feature: 'heart_rate_max', label: 'Max heart rate', value: 188, contribution: 0.4, direction: 'up' }] },
    { row: 2, player_id: 7, name: 'Luka Petrovic', date: '2026-10-06', risk_percent: null, level: 'unknown', score_status: 'insufficient_data', score_note: 'only 10 minutes logged', data_quality: 'csv', factors: [] },
  ],
  latency_ms: 30,
};
const STORED = { ...PREVIEW, upload_id: 12, dry_run: false };
const csvFile = () => new File(['date,player\n2026-10-06,Faisal Musa\n'], 'week40.csv', { type: 'text/csv' });

function setupCsv(routes = {}) {
  signIn();
  const api = mockFetch({ 'GET /api/auth/me': ME, 'GET /api/players': [200, []], 'GET /api/uploads/csv': [200, []], ...routes });
  const utils = renderRoutes({ at: '/roster/upload', protectedRoutes: { '/roster/upload': <CsvUpload /> }, stubs: ['/roster'] });
  const pick = (file = csvFile()) => fireEvent.change(utils.container.querySelector('input[type=file]'), { target: { files: [file] } });
  return { api, pick, ...utils };
}

describe('CSV athlete-log upload', () => {
  it('previews with dry_run (nothing stored), shows errors/unmatched/results, then stores on confirm', async () => {
    const { api, pick, user, container } = setupCsv({ 'POST /api/uploads/csv': (req) => (req.body.get('dry_run') === 'true' ? [200, PREVIEW] : [201, STORED]) });
    await screen.findByText('Upload athlete log');
    pick();
    await screen.findByText('2. Check the preview');
    const first = api.find('POST', '/api/uploads/csv')[0];
    expect(first.body.get('dry_run')).toBe('true');
    expect(first.params.get('dry_run')).toBe('true');
    expect(first.body.get('file').name).toBe('week40.csv');
    const preview = container.querySelector('[data-csv-preview]');
    expect(preview.querySelector('[data-count="invalid"]')).toHaveTextContent('1');
    expect(preview.querySelector('[data-error-row="3"]')).toHaveTextContent('must be ≥ 0');
    expect(preview.querySelector('[data-csv-unmatched]')).toHaveTextContent('Zed Nobody');
    expect(preview.querySelector('[data-result-row="1"] [data-level="yellow"]')).toHaveTextContent('Moderate48%');
    // non-scored CSV row: neutral not-scored badge + note, no number
    const row2 = preview.querySelector('[data-result-row="2"]');
    expect(row2.querySelector('[data-level="unknown"]')).toHaveTextContent('Not scored');
    expect(row2.querySelector('[data-score-note]')).toHaveTextContent('only 10 minutes logged');
    expect(row2.querySelector('[data-quality="csv"]')).toHaveTextContent('Athlete log');
    expect(within(preview).getByText(/Nothing has been stored/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /Save 2 valid rows/ }));
    await screen.findByText('Athlete log saved');
    const second = api.find('POST', '/api/uploads/csv')[1];
    expect(second.body.get('dry_run')).toBe('false');
    expect(container.querySelector('[data-csv-saved]')).toHaveTextContent('upload #12');
  });

  it('lists missing columns on 422', async () => {
    const { pick, container } = setupCsv({ 'POST /api/uploads/csv': [422, { detail: 'Missing required columns', missing_columns: ['date', 'player'] }] });
    await screen.findByText('Upload athlete log');
    pick();
    expect(await screen.findByText('Missing required columns', { selector: 'p.font-semibold' })).toBeInTheDocument();
    expect([...container.querySelectorAll('[data-missing-columns] li')].map((l) => l.textContent)).toEqual(['date', 'player']);
  });

  it.each([
    [413, /too large/],
    [415, /isn’t a CSV/],
  ])('explains HTTP %i', async (status, re) => {
    const { pick } = setupCsv({ 'POST /api/uploads/csv': [status, null] });
    await screen.findByText('Upload athlete log');
    pick();
    expect(await screen.findByRole('alert')).toHaveTextContent(re);
  });

  it('rejects a non-CSV file without calling the server', async () => {
    const { pick, api } = setupCsv();
    await screen.findByText('Upload athlete log');
    pick(new File(['x'], 'clip.mp4', { type: 'video/mp4' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/isn’t a CSV/);
    expect(api.find('POST', '/api/uploads/csv')).toHaveLength(0);
  });

  it('deletes a recent upload only after confirming', async () => {
    const { api, user } = setupCsv({
      'GET /api/uploads/csv': [200, [{ upload_id: 5, filename: 'week39.csv', created_at: '2026-10-01T10:00:00Z', rows_valid: 20, rows_total: 22 }]],
      'DELETE /api/uploads/csv/5': [204, null],
    });
    await user.click(await screen.findByRole('button', { name: 'Delete week39.csv' }));
    expect(api.find('DELETE', '/api/uploads/csv/5')).toHaveLength(0);
    const dialog = screen.getByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(api.find('DELETE', '/api/uploads/csv/5')).toHaveLength(1));
    await waitFor(() => expect(screen.queryByText('week39.csv')).toBeNull());
  });
});
