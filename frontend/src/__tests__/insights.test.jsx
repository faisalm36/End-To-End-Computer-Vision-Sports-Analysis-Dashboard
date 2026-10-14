import { screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { computeInsights, normalizeInsights } from '../lib/insights';
import Insights from '../pages/Insights';
import LIVE from '../test/fixtures/insights-weather.json';
import { ME, mockFetch, signIn } from '../test/mockApi';
import { renderRoutes } from '../test/render';

// The live backend's /api/insights?tag_key=Weather payload (seed data), plus a third
// group "Snow" with ONE match and the highest distance: it must not be ranked first.
const payload = () => {
  const p = structuredClone(LIVE);
  p.groups.push({
    value: 'Snow',
    matches: 1,
    matches_with_data: 1,
    low_sample: true,
    avg_distance_km: 9.9,
    avg_top_speed_mph: 25,
    avg_sprints: 30,
    avg_hsr_distance_km: 1.2,
    avg_workload: 3,
    workload: { low: 0, medium: 0, high: 4 },
    wdl: { w: 0, d: 0, l: 0, unknown: 1 },
  });
  return p;
};

const tagged = (id, weather) => ({ id, title: `M${id}`, status: 'done', stage: 'done', progress: 100, tags: [{ key: 'Weather', value: weather }] });

function open(routes = {}) {
  signIn();
  const api = mockFetch({
    'GET /api/auth/me': ME,
    'GET /api/metrics': [200, []],
    'GET /api/videos': [200, [tagged(1, 'Sunny'), tagged(2, 'Rainy'), tagged(3, 'Snow')]],
    'GET /api/videos/1/stats': [200, []],
    'GET /api/videos/2/stats': [200, []],
    'GET /api/videos/3/stats': [200, []],
    'GET /api/insights': (req) => (req.params.get('tag_key') === 'Weather' ? payload() : [422, { detail: 'bad key' }]),
    ...routes,
  });
  const utils = renderRoutes({ at: '/insights', protectedRoutes: { '/insights': <Insights /> }, stubs: ['/profile'] });
  return { api, ...utils };
}

const groupRows = () => {
  const section = screen.getByRole('heading', { name: 'By condition' }).closest('section');
  return within(section).getAllByRole('listitem');
};

describe('Insights: by condition', () => {
  it('ranks groups with enough matches by value and puts low_sample groups last, unranked', async () => {
    const { api } = open();
    await screen.findByRole('heading', { name: 'By condition' });
    const rows = groupRows();
    expect(rows.map((li) => li.querySelector('span').textContent)).toEqual(['Sunny', 'Rainy', 'Snow']);
    expect(rows[2]).toHaveTextContent('n = 1 match · Low sample (need 3), not ranked');
    expect(rows[2]).toHaveClass('opacity-50');
    expect(rows[0]).not.toHaveTextContent('Low sample');
    expect(api.find('GET', '/api/insights')[0].params.get('tag_key')).toBe('Weather');
    expect(screen.getByText(/6 analysed matches/)).toBeInTheDocument(); // baseline.matches_with_data
  });

  it('table view lists the same order and flags the low sample', async () => {
    const { user } = open();
    await screen.findByRole('heading', { name: 'By condition' });
    const section = screen.getByRole('heading', { name: 'By condition' }).closest('section');
    await user.click(within(section).getByRole('button', { name: /View as table/ }));
    const cells = within(section).getAllByRole('row').slice(1).map((r) => r.firstChild.textContent);
    expect(cells).toEqual(['Sunny', 'Rainy', 'Snow (low sample)']);
  });
});

describe('Insights: next-match effect', () => {
  it('hides changes for low-sample values and shows the table once n >= 3', async () => {
    const { user } = open();
    const section = (await screen.findByRole('heading', { name: 'Next-match effect' })).closest('section');
    // Rainy is first and only has n = 2 pairs: no numbers, no headline.
    const rainy = within(section).getByRole('button', { name: /Rainy/ });
    expect(rainy).toHaveAttribute('aria-pressed', 'true');
    expect(within(section).getAllByText('Not enough matches yet (need 3)')).toHaveLength(5);
    expect(within(section).queryByText(/After rainy games/)).not.toBeInTheDocument();

    await user.click(within(section).getByRole('button', { name: /Sunny/ }));
    expect(within(section).getByText(/After sunny games, next-match distance is/)).toHaveTextContent(
      'After sunny games, next-match distance is 4.7% lower than your squad’s average (n = 3).',
    );
    const rows = within(section).getAllByRole('row');
    expect(rows[0]).toHaveTextContent(/Metric.*Baseline.*Next match.*Δ.*n/);
    const distance = rows.find((r) => r.firstChild.textContent === 'Distance');
    expect([...distance.children].map((c) => c.textContent)).toEqual(['Distance', '3.50 km', '3.34 km', '▼ 4.7%', '3']);
    const workload = rows.find((r) => r.firstChild.textContent === 'Workload');
    expect(workload).toHaveTextContent('▲ 11.1%');
    expect(within(section).queryByText('Not enough matches yet (need 3)')).not.toBeInTheDocument();
  });
});

describe('Insights: results and fallbacks', () => {
  it('W/D/L shows unknown counts and marks small groups', async () => {
    open();
    const section = (await screen.findByRole('heading', { name: 'Results (W / D / L)' })).closest('section');
    const items = within(section).getAllByRole('listitem');
    const snow = items.find((li) => li.textContent.startsWith('Snow'));
    expect(snow).toHaveTextContent('0W 0D 0L');
    expect(snow).toHaveTextContent('n = 0 with a result · 1 unknown · Low sample (need 3)');
  });

  it('computes in the browser when /api/insights does not exist (404)', async () => {
    open({ 'GET /api/insights': [404, { detail: 'Not Found' }] });
    expect(await screen.findByText(/computed in your browser/)).toBeInTheDocument();
  });

  it('client and server shapes agree on low_sample (< 3 matches)', () => {
    const m = (id, w) => ({ video: tagged(id, w), stats: [{ player_id: 1, name: 'A', top_speed_mph: 20, distance_km: 5, injury_risk: 'Low' }] });
    const res = computeInsights([m(1, 'Sunny'), m(2, 'Sunny'), m(3, 'Sunny'), m(4, 'Rainy')], 'Weather');
    expect(Object.fromEntries(res.groups.map((g) => [g.value, g.low_sample]))).toEqual({ Sunny: false, Rainy: true });
    const norm = normalizeInsights(payload());
    expect(norm.groups.find((g) => g.value === 'Snow').low_sample).toBe(true);
    expect(norm.next_match_effect.filter((e) => e.value === 'Rainy').every((e) => e.low_sample)).toBe(true);
  });
});

it('shows an empty state with no tagged matches', async () => {
  open({ 'GET /api/videos': [200, [{ id: 1, status: 'done', tags: [] }]] });
  await waitFor(() => expect(screen.getByText('Tag your matches to unlock insights')).toBeInTheDocument());
});
