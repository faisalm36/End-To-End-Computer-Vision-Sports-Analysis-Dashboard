import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { summarizeMatch } from '../lib/insights';
import { normalizePlayerRow } from '../lib/playerStats';
import Upload from '../pages/Upload';
import VideoResults from '../pages/VideoResults';
import { ME, mockFetch, mockXHR, signIn } from '../test/mockApi';
import { renderRoutes } from '../test/render';

describe('A7 stats dual naming', () => {
  it('keeps mph/km/injury_risk and surfaces metres, fatigue, minutes, sprints', () => {
    const p = normalizePlayerRow({
      player_id: 1,
      name: 'A',
      top_speed_mph: 20,
      distance_km: 1.5,
      injury_risk: 'Medium',
      distance_covered_meters: 1500,
      top_speed_kmh: 32.2,
      fatigue_risk_score: 50,
      minutes_played: 12.5,
      sprint_count: 4,
    });
    expect(p).toMatchObject({
      top_speed_mph: 20,
      distance_km: 1.5,
      injury_risk: 'Medium',
      distance_covered_meters: 1500,
      top_speed_kmh: 32.2,
      fatigue_risk_score: 50,
      minutes_played: 12.5,
      sprint_count: 4,
    });
    expect(normalizePlayerRow({ player_id: 2, name: 'B', distance_km: 2 }).distance_covered_meters).toBe(2000);
    expect(normalizePlayerRow({ player_id: 3, name: 'C', top_speed_mph: 10 }).top_speed_kmh).toBeCloseTo(16.09344);
    expect(normalizePlayerRow({ player_id: 4, name: 'D' }).fatigue_risk_score).toBeNull();
  });

  it('insights group summary carries ERD averages when present', () => {
    const s = summarizeMatch([
      {
        player_id: 1,
        name: 'A',
        top_speed_mph: 20,
        distance_km: 1,
        distance_covered_meters: 1000,
        top_speed_kmh: 32,
        sprint_count: 2,
        minutes_played: 10,
        injury_risk: 'Low',
        fatigue_risk_score: 0,
      },
      {
        player_id: 2,
        name: 'B',
        top_speed_mph: 22,
        distance_km: 3,
        distance_covered_meters: 3000,
        top_speed_kmh: 35,
        sprint_count: 4,
        minutes_played: 20,
        injury_risk: 'High',
        fatigue_risk_score: 100,
      },
    ]);
    expect(s.avg_distance_km).toBe(2);
    expect(s.avg_distance_covered_meters).toBe(2000);
    expect(s.avg_top_speed_kmh).toBe(33.5);
    expect(s.avg_sprint_count).toBe(3);
    expect(s.avg_minutes_played).toBe(15);
    expect(s.avg_fatigue_risk_score).toBe(50);
  });
});

describe('A5 upload video_type + VideoResults meta', () => {
  const video = (name = 'match.mp4', size = 1000, type = 'video/mp4') => {
    const f = new File(['x'], name, { type });
    Object.defineProperty(f, 'size', { value: size });
    return f;
  };

  it('sends video_type with the multipart upload', async () => {
    signIn();
    mockFetch({
      'GET /api/auth/me': ME,
      'GET /api/config': { max_upload_mb: 50, allowed_extensions: ['mp4', 'mov'] },
      'GET /api/matches': [200, []],
      'GET /api/tags': [200, []],
    });
    const xhr = mockXHR(() => [202, { id: 9, status: 'queued', stage: 'queued', progress: 0, match_id: 1 }]);
    const { user, container } = renderRoutes({ at: '/upload', protectedRoutes: { '/upload': <Upload /> }, stubs: ['/videos/:id'] });
    await screen.findAllByText(/up to 50 MB/);
    await act(async () => fireEvent.change(container.querySelector('input[type=file]'), { target: { files: [video()] } }));
    await user.selectOptions(screen.getByLabelText(/Camera \/ footage type/), 'broadcast');
    await user.type(screen.getByLabelText('Match date'), '2026-10-01');
    await user.type(screen.getByLabelText('Home team'), 'Reds');
    await user.type(screen.getByLabelText('Away team'), 'Blues');
    await user.click(screen.getByRole('button', { name: 'Start analysis' }));
    await waitFor(() => expect(xhr.sent).toHaveLength(1));
    expect(xhr.sent[0].form.get('video_type')).toBe('broadcast');
  });

  it('shows video_type, resolution and duration on VideoResults', async () => {
    signIn();
    mockFetch({
      'GET /api/auth/me': ME,
      'GET /api/metrics': [200, []],
      'GET /api/tags': [200, []],
      'GET /api/videos/9': {
        id: 9,
        title: 'Clip',
        status: 'done',
        stage: 'done',
        progress: 100,
        video_type: 'endzone_cam',
        resolution: '1920x1080',
        duration_seconds: 125.4,
        home_team: 'Reds',
        away_team: 'Blues',
        match_date: '2026-10-01',
      },
      'GET /api/videos/9/stats': [
        200,
        [
          {
            player_id: 1,
            name: 'Alex',
            top_speed_mph: 18,
            distance_km: 0.4,
            injury_risk: 'Low',
            fatigue_risk_score: 0,
            minutes_played: 2,
            sprint_count: 1,
            distance_covered_meters: 400,
          },
        ],
      ],
    });
    const { user } = renderRoutes({ at: '/videos/9', protectedRoutes: { '/videos/:id': <VideoResults /> }, stubs: ['/profile', '/upload'] });
    await screen.findByText('Clip');
    const meta = document.querySelector('[data-video-meta]');
    expect(meta).toHaveTextContent(/End-zone cam/);
    expect(meta).toHaveTextContent('1920x1080');
    expect(meta).toHaveTextContent('2:05');
    const row = screen.getByRole('row', { name: /Alex/ });
    await user.click(row);
    expect(await screen.findByText('Minutes played')).toBeInTheDocument();
    expect(screen.getByText('Fatigue score')).toBeInTheDocument();
    expect(document.querySelector('[data-erd-stats]')).toBeInTheDocument();
    expect(document.querySelector('[data-video-meta]')).toHaveTextContent(/End-zone cam/);
  });
});
