import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import Dashboard from '../Dashboard';
import { heatmapFrom, normalizePlayerRow } from '../lib/playerStats';
import { mockFetch } from '../test/mockApi';
import METRICS_LIVE from '../test/fixtures/metrics.json';

// A 21 x 14 heat map with two hot cells: (row 2, col 20) and (row 13, col 0).
const cells21 = Array(21 * 14).fill(0);
cells21[2 * 21 + 20] = 1;
cells21[13 * 21 + 0] = 0.5;

const row = (over) => ({
  player_id: 1,
  name: 'Ivan Horvat',
  top_speed_mph: 20.1,
  distance_km: 5.25,
  injury_risk: 'Low',
  jersey_number: 1,
  ...over,
});

const PLAYERS = [
  row({
    player_id: 1,
    coverage_pct: 92,
    visible_minutes: 55,
    minutes_played: 60,
    distance_per_min: 95.4,
    hsr_distance_km: 0.41,
    sprint_count: 12,
    avg_position: { x: 30, y: 20 },
    heatmap: { cols: 21, rows: 14, cells: cells21, samples: 400, pitch_length_m: 105, pitch_width_m: 68 },
    speed_thresholds: { preset: 'gps_standard', hsr_kmh: 19.8, sprint_kmh: 25.3, zone_edges_kmh: { walk: 7, jog: 15, run: 20, hsr: 25 } },
  }),
  row({ player_id: 2, name: 'Unknown #7', jersey_number: 7, top_speed_mph: null, distance_km: null, injury_risk: 'High', coverage_pct: 41 }),
  row({ player_id: 3, name: 'Luka Novak', jersey_number: 9, top_speed_mph: 18.4, distance_km: 4.1, injury_risk: 'Medium' }),
];

// Registry: everything ready except accels/decels (soon), decimals as the backend sends them.
const defs = (soon = ['accels', 'decels']) => METRICS_LIVE.map((d) => (soon.includes(d.key) ? { ...d, availability: 'soon' } : d));

function renderDash({ metrics = defs(), players = PLAYERS } = {}) {
  mockFetch({ 'GET /api/metrics': metrics === null ? [404, { detail: 'Not Found' }] : [200, metrics] });
  return render(<Dashboard players={players} videoId="v1" title="Test match" />);
}

const intensity = () => screen.getByRole('heading', { name: 'Intensity metrics' }).closest('div.rounded-2xl');

describe('Dashboard rendering', () => {
  it('renders missing numbers as "—", never NaN/undefined, and explains why', async () => {
    renderDash();
    const table = screen.getByRole('table');
    const unknown = within(table).getByText('Unknown #7').closest('tr');
    expect(within(unknown).getAllByText('\u2014').length).toBeGreaterThanOrEqual(3); // speed, distance, m/min
    expect(screen.getByText(/Speed or distance is unavailable \(shown as/)).toHaveTextContent('for 1 of 3 players');
    expect(document.body.textContent).not.toMatch(/NaN|undefined|Infinity/);
  });

  it('uses registry decimals (distance_km = 2) in the table', async () => {
    renderDash();
    await waitFor(() => expect(within(screen.getByRole('table')).getByText(/^5\.25/)).toBeInTheDocument());
  });

  it('labels workload as an indicator, not medical advice, with no injury-risk wording', () => {
    renderDash();
    expect(screen.getAllByText('Workload indicator, not medical advice').length).toBeGreaterThan(0);
    expect(screen.getByRole('columnheader', { name: /Workload/ })).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/injury/i);
  });

  it('shows "Coming soon" only for metrics the registry marks soon; ready-but-missing is "—"', async () => {
    renderDash();
    await waitFor(() => expect(within(intensity()).getAllByText('Coming soon')).toHaveLength(2)); // accels + decels
    const box = intensity();
    expect(within(box).getByText('High-speed running').parentElement).toHaveTextContent('0.41 km');
    expect(within(box).getByText('Sprint distance').parentElement).toHaveTextContent('\u2014'); // ready, no value
    expect(within(box).getByText('Sprint distance').parentElement).not.toHaveTextContent('Coming soon');
  });

  it('falls back to src/lib/metrics.js availability when /api/metrics is missing', async () => {
    renderDash({ metrics: null });
    // Local fallback: intensity metrics are 'soon', so missing ones read "Coming soon"
    // (sprint distance, high-intensity efforts, accels, decels) and present ones show values.
    await waitFor(() => expect(within(intensity()).getAllByText('Coming soon')).toHaveLength(4));
    expect(within(intensity()).getByText('Sprints').parentElement).toHaveTextContent('12');
    expect(intensity().textContent).not.toMatch(/NaN|undefined/);
  });

  it('shows the speed thresholds this video used, and coverage', async () => {
    renderDash();
    expect(within(intensity()).getByText('Speed thresholds used: GPS standard · HSR > 19.8 km/h · Sprint > 25.3 km/h')).toBeInTheDocument();
    expect(within(intensity()).getByText(/Speed zones: walk < 7 · jog 7–15/)).toBeInTheDocument();
    expect(screen.getByText(/Low tracking coverage: 1 of 3 players/)).toBeInTheDocument();
    expect(within(screen.getByRole('table')).getByText('41% tracked')).toHaveClass('text-amber-300');
  });

  it('labels default thresholds when the video did not report any', () => {
    renderDash({ players: PLAYERS.map((p) => ({ ...p, speed_thresholds: null })) });
    expect(screen.getAllByText(/^Default speed thresholds \(not reported for this video\): GPS default/).length).toBeGreaterThan(0);
  });

  it('hides the "Estimated from video" badge when the registry says is_estimate=false', async () => {
    const metrics = defs().map((d) => (d.key === 'top_speed_mph' ? { ...d, is_estimate: false } : d));
    renderDash({ metrics });
    const card = () => screen.getByText('Avg Top Speed').closest('div.relative');
    await waitFor(() => expect(within(card()).queryByText('Estimated from video')).not.toBeInTheDocument());
    expect(within(screen.getByText('Total Distance').closest('div.relative')).getByText('Estimated from video')).toBeInTheDocument();
  });

  it('player detail: heat map drawn from dynamic cols/rows (21×14), coverage badge, thresholds', async () => {
    const user = userEvent.setup();
    renderDash();
    await user.click(within(screen.getByRole('table')).getByText('Ivan Horvat'));
    const svg = screen.getByRole('img', { name: /^Heat map for Ivan Horvat/ });
    const rects = [...svg.querySelectorAll('rect[opacity]')];
    expect(rects).toHaveLength(2);
    // col 20 of 21 on a 105-wide pitch -> x = 100; row 2 of 14 on 68 -> y = 9.714
    expect(Number(rects[0].getAttribute('x'))).toBeCloseTo(100, 3);
    expect(Number(rects[0].getAttribute('y'))).toBeCloseTo((2 * 68) / 14, 3);
    expect(Number(rects[0].getAttribute('width'))).toBeCloseTo(105 / 21 + 0.05, 3);
    expect(Number(rects[1].getAttribute('y'))).toBeCloseTo((13 * 68) / 14, 3);
    expect(Number(rects[1].getAttribute('opacity'))).toBeLessThan(Number(rects[0].getAttribute('opacity')));
    const panel = svg.closest('aside');
    expect(within(panel).getByText('21×14 grid · 400 samples')).toBeInTheDocument();
    expect(within(panel).getByText('Tracked 92% of match · 55 of 60 min')).toBeInTheDocument();
    expect(within(panel).getByText('Player ID 1')).toBeInTheDocument();
  });

  it('player detail: a low-coverage warning', async () => {
    const user = userEvent.setup();
    renderDash();
    await user.click(within(screen.getByRole('table')).getByText('Unknown #7'));
    const panel = screen.getByText('Tracked 41% of match').closest('aside');
    expect(within(panel).getByText(/Low coverage: this player was out of view/)).toBeInTheDocument();
  });
});

describe('playerStats normaliser', () => {
  it('reads cols/rows from the payload (12×8 and 21×14) and rejects short cell arrays', () => {
    expect(heatmapFrom({ cols: 12, rows: 8, cells: [1, ...Array(95).fill(0)] })).toMatchObject({ cols: 12, rows: 8 });
    expect(heatmapFrom({ cols: 21, rows: 14, cells: cells21 })).toMatchObject({ cols: 21, rows: 14 });
    expect(heatmapFrom({ cols: 21, rows: 14, cells: [1, 0] })).toBeNull();
    expect(heatmapFrom({ cols: 12, rows: 8, cells: Array(96).fill(0) })).toBeNull(); // all zero
  });

  it('drops an impossible per-minute rate from a stub clip and says why', () => {
    const p = normalizePlayerRow({ player_id: 9, distance_km: 7.3, minutes_played: 0, distance_per_min: 438000, coverage_pct: 92 });
    expect(p.distance_per_min).toBeNull();
    expect(p.per_min_note).toBe('Clip too short for a per-minute rate');
    expect(p.coverage_pct).toBe(92);
  });

  it('keeps a normal per-minute rate and clamps coverage to 0–100', () => {
    const p = normalizePlayerRow({ player_id: 9, distance_km: 5, minutes_played: 60, distance_per_min: 83.3, coverage_pct: 140 });
    expect(p.distance_per_min).toBe(83.3);
    expect(p.coverage_pct).toBe(100);
  });
});
