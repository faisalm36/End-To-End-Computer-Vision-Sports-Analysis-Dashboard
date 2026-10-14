import { screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import VideoResults from '../pages/VideoResults';
import { ME, mockFetch, signIn } from '../test/mockApi';
import { renderRoutes } from '../test/render';

const VIDEO = {
  id: 5,
  match_id: 3,
  title: 'Cup final',
  status: 'done',
  stage: 'done',
  progress: 100,
  home_team: 'Capstone FC',
  away_team: 'Rival United',
  match_date: '2026-09-27',
  result: null,
  tags: [{ key: 'Weather', value: 'Rainy' }],
  match: { match_id: 3, home_score: null, away_score: null, result: null },
};
const MATCH = { match_id: 3, home_team: 'Capstone FC', away_team: 'Rival United', home_score: null, away_score: null, our_side: 'home', result: null };
const STATS = [{ player_id: 1, name: 'Ivan Horvat', top_speed_mph: 20.1, distance_km: 5.2, injury_risk: 'Low', jersey_number: 1 }];

function open(routes) {
  signIn();
  const api = mockFetch({ 'GET /api/auth/me': ME, 'GET /api/metrics': [200, []], 'GET /api/tags': [200, []], ...routes });
  const utils = renderRoutes({ at: '/videos/5', protectedRoutes: { '/videos/:id': <VideoResults /> }, stubs: ['/profile', '/upload'] });
  return { api, ...utils };
}

describe('Video results', () => {
  it('a deleted / unknown video gets a clear not-found page without a pointless Retry', async () => {
    open({ 'GET /api/videos/5': [404, { detail: 'Video not found' }], 'GET /api/videos/5/stats': [404, { detail: 'Video not found' }] });
    expect(await screen.findByRole('heading', { name: 'Video not found' })).toBeInTheDocument();
    expect(screen.getByText(/doesn’t exist or has been deleted/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Go to your uploads' })).toHaveAttribute('href', '/profile');
  });

  it('a 409 while processing shows the stepper, not an error', async () => {
    open({
      'GET /api/videos/5': { ...VIDEO, status: 'processing', stage: 'track', progress: 72 },
      'GET /api/videos/5/stats': [409, { detail: 'Video is still processing', status: 'processing', stage: 'track', progress: 72 }],
      'GET /api/matches/3': MATCH,
    });
    expect(await screen.findByText('Results aren’t ready yet')).toBeInTheDocument();
    expect(document.querySelector('li[aria-current=step]')).toHaveTextContent('Tracking');
  });

  it('adds a score: PATCHes the match and shows the derived result', async () => {
    const { api, user } = open({
      'GET /api/videos/5': VIDEO,
      'GET /api/videos/5/stats': [200, STATS],
      'GET /api/matches/3': MATCH,
      'PATCH /api/matches/3': (req) => ({ ...MATCH, ...req.body, result: 'L' }),
    });
    await user.click(await screen.findByRole('button', { name: 'Add score' }));
    const form = screen.getByRole('form', { name: 'Edit final score' });
    await user.type(within(form).getByLabelText(/Capstone FC/), '1');
    await user.click(within(form).getByRole('button', { name: 'Save score' }));
    expect(within(form).getByText('Enter both scores, or leave both blank.')).toBeInTheDocument();
    await user.type(within(form).getByLabelText(/Rival United/), '2');
    await user.click(within(form).getByRole('button', { name: 'Save score' }));
    await waitFor(() => expect(screen.getByText('1–2')).toBeInTheDocument());
    expect(api.find('PATCH', '/api/matches/3')[0].body).toEqual({ home_score: 1, away_score: 2 });
    expect(screen.getByTitle('Loss')).toBeInTheDocument();
  });

  it('edits tags with a full PUT replace', async () => {
    const { api, user } = open({
      'GET /api/videos/5': VIDEO,
      'GET /api/videos/5/stats': [200, STATS],
      'GET /api/matches/3': MATCH,
      'PUT /api/videos/5/tags': (req) => ({ ...VIDEO, tags: req.body.tags }),
    });
    await user.click(await screen.findByRole('button', { name: 'Edit tags' }));
    await user.type(screen.getByLabelText('Tag'), 'Pitch');
    await user.type(screen.getByLabelText('Value'), 'Turf{Enter}');
    await user.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(api.find('PUT', '/api/videos/5/tags')).toHaveLength(1));
    expect(api.find('PUT', '/api/videos/5/tags')[0].body).toEqual({
      tags: [
        { key: 'Weather', value: 'Rainy' },
        { key: 'Pitch', value: 'Turf' },
      ],
    });
    expect(await screen.findByRole('button', { name: 'Edit tags' })).toBeInTheDocument();
    expect(screen.getByText('Turf')).toBeInTheDocument();
  });
});
