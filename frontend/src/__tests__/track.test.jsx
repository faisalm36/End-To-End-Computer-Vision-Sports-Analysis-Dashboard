import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import TrackPlayer from '../pages/TrackPlayer';
import { ME, mockFetch, seq, signIn } from '../test/mockApi';
import { renderRoutes } from '../test/render';
import DETS from '../test/fixtures/detections-f40.json';
import FRAMES from '../test/fixtures/track-frames.json';

// jsdom has no media playback, canvas or rAF timing: minimal stand-ins.
beforeEach(() => {
  const t = new WeakMap();
  const paused = new WeakMap();
  Object.defineProperty(HTMLMediaElement.prototype, 'currentTime', {
    configurable: true,
    get() {
      return t.get(this) ?? 0;
    },
    set(v) {
      t.set(this, v);
      queueMicrotask(() => this.dispatchEvent(new Event('seeked')));
    },
  });
  Object.defineProperty(HTMLMediaElement.prototype, 'paused', { configurable: true, get: () => true });
  Object.defineProperty(HTMLMediaElement.prototype, 'paused', {
    configurable: true,
    get() {
      return paused.get(this) ?? true;
    },
  });
  HTMLMediaElement.prototype.play = function play() {
    paused.set(this, false);
    this.dispatchEvent(new Event('play'));
    return Promise.resolve();
  };
  HTMLMediaElement.prototype.pause = function pause() {
    paused.set(this, true);
    this.dispatchEvent(new Event('pause'));
  };
  HTMLMediaElement.prototype.load = () => {};
  HTMLCanvasElement.prototype.getContext = () => null;
  vi.stubGlobal('requestAnimationFrame', (cb) => setTimeout(() => cb(performance.now()), 16));
  vi.stubGlobal('cancelAnimationFrame', (id) => clearTimeout(id));
});

const VIDEO = {
  id: 1,
  title: 'Derby',
  status: 'done',
  fps: 25,
  duration_seconds: 10,
  pipeline_meta: { frame_count: 250, resolution: [640, 360] },
  source_url: '/api/videos/1/source?token=t',
};
const STATS = [
  { player_id: 24, name: 'Unknown #1', jersey_number: 10, top_speed_mph: 21.2, distance_km: 0.05 },
  { player_id: 25, name: 'Unknown #2', jersey_number: 7, top_speed_mph: 19, distance_km: 0.04 },
];
const track = (over = {}) => ({
  track_id: 100,
  video_id: 1,
  status: 'queued',
  stage: 'queued',
  progress: 0,
  error_message: null,
  target: { player_id: 24, jersey_number: 10, team: 'A', frame: 40, bbox: [0.18, 0.43, 0.034, 0.144] },
  fps: 25,
  frame_count: 250,
  width: 640,
  height: 360,
  annotated_url: null,
  frames_url: null,
  created_at: '2026-10-02T21:00:00Z',
  ...over,
});
const DONE = track({ status: 'done', stage: 'done', progress: 100, annotated_url: '/api/tracks/100/annotated.mp4?token=t', frames_url: '/api/tracks/100/frames?token=t' });

function setup({ at = '/videos/1/track', routes = {}, video = VIDEO, userOptions } = {}) {
  signIn();
  const api = mockFetch({
    'GET /api/auth/me': ME,
    'GET /api/videos/1': video,
    'GET /api/videos/1/stats': [200, STATS],
    'GET /api/videos/1/tracks': [200, []],
    'GET /api/videos/1/detections': (req) => ({ ...DETS, frame: Number(req.params.get('frame')) }),
    'GET /api/tracks/100/frames': FRAMES,
    ...routes,
  });
  const page = <TrackPlayer />;
  const utils = renderRoutes({ at, protectedRoutes: { '/videos/:id/track': page, '/videos/:id/track/:trackId': page }, userOptions });
  return { api, ...utils };
}
const where = () => screen.getByTestId('location').textContent;

describe('Track a player: pick', () => {
  it('shows the frame’s detections as boxes; click selects, confirm starts a track with frame + bbox', async () => {
    const { api, user, container } = setup({ routes: { 'POST /api/videos/1/tracks': [202, track()], 'GET /api/tracks/100': track() } });
    await waitFor(() => expect(container.querySelectorAll('[data-det]')).toHaveLength(6));
    expect(screen.getAllByText('Player ?').length).toBeGreaterThan(0); // no jersey number
    const box = container.querySelector('[data-det^="24-"]');
    expect(box).toHaveAccessibleName(/^#10, Team A, detection \d+%/);
    await user.click(box);
    const bar = container.querySelector('[data-confirm]');
    expect(within(bar).getByText('#10')).toBeInTheDocument();
    expect(box).toHaveAttribute('aria-pressed', 'true');
    await user.click(within(bar).getByRole('button', { name: 'Track this player' }));
    await waitFor(() => expect(where()).toBe('/videos/1/track/100'));
    expect(api.find('POST', '/api/videos/1/tracks')[0].body).toEqual({ frame: 0, bbox: DETS.players[0].bbox, player_id: 24, jersey_number: 10, team: 'A' });
  });

  it('picks by shirt number from the stats rows', async () => {
    const { api, user, container } = setup({
      routes: { 'POST /api/videos/1/tracks': [202, track({ target: { player_id: 25, jersey_number: 7 } })], 'GET /api/tracks/100': track() },
    });
    await screen.findByLabelText('Shirt number');
    await user.selectOptions(screen.getByLabelText('Shirt number'), '25');
    expect(container.querySelector('[data-confirm]')).toHaveTextContent('Selected by shirt number');
    await user.click(screen.getByRole('button', { name: 'Track this player' }));
    await waitFor(() => expect(api.find('POST', '/api/videos/1/tracks')).toHaveLength(1));
    expect(api.find('POST', '/api/videos/1/tracks')[0].body).toEqual({ player_id: 25, jersey_number: 7 });
  });

  it('Esc cancels the selection; referees can be hidden', async () => {
    const { user, container } = setup();
    await waitFor(() => expect(container.querySelectorAll('[data-det]')).toHaveLength(6));
    await user.click(container.querySelector('[data-det^="25-"]'));
    expect(container.querySelector('[data-confirm]')).toBeInTheDocument();
    await user.keyboard('{Escape}');
    expect(container.querySelector('[data-confirm]')).toBeNull();
    await user.click(screen.getByLabelText('Show referees'));
    expect(container.querySelectorAll('[data-det]')).toHaveLength(5);
  });

  it('409 (one track at a time) shows the message and links to the running track', async () => {
    const running = track({ track_id: 7, status: 'processing', stage: 'tracking', progress: 30 });
    const { user, container } = setup({
      routes: { 'POST /api/videos/1/tracks': [409, { detail: 'A track is already running for this video.' }], 'GET /api/videos/1/tracks': seq([200, []], [200, [running]]) },
    });
    await waitFor(() => expect(container.querySelectorAll('[data-det]')).toHaveLength(6));
    await user.click(container.querySelector('[data-det^="24-"]'));
    await user.click(screen.getByRole('button', { name: 'Track this player' }));
    const err = await screen.findByText(/already running for this video/);
    expect(err.closest('[data-start-error]')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'View the running track (#10)' })).toHaveAttribute('href', '/videos/1/track/7');
  });

  it('a server without tracking routes (404) says so instead of faking it', async () => {
    setup({ routes: { 'GET /api/videos/1/tracks': [404, { detail: 'Not Found' }] } });
    expect(await screen.findByRole('heading', { name: 'Player tracking isn’t available on this server yet' })).toBeInTheDocument();
    expect(document.querySelector('[data-det]')).toBeNull();
  });
});

describe('Track a player: progress', () => {
  it('polls status/stage/progress through the stepper, then opens the replay', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { api } = setup({
      at: '/videos/1/track/100',
      routes: {
        'GET /api/tracks/100': seq(
          track(),
          track({ status: 'processing', stage: 'tracking', progress: 40 }),
          track({ status: 'processing', stage: 'rendering', progress: 85 }),
          DONE,
        ),
      },
    });
    const status = await screen.findByText('Queued: waiting for the tracker');
    expect(status).toHaveAttribute('role', 'status');
    const current = () => document.querySelector('[data-track-progress] [aria-current=step]');
    expect(current()).toHaveTextContent('Queued');
    await act(() => vi.advanceTimersByTimeAsync(1600));
    expect(current()).toHaveTextContent('Following the player');
    expect(screen.getByRole('progressbar', { name: 'Tracking progress' })).toHaveAttribute('aria-valuenow', '40');
    expect(status).toHaveAttribute('aria-live', 'polite');
    await act(() => vi.advanceTimersByTimeAsync(1600));
    expect(current()).toHaveTextContent('Rendering video');
    expect(screen.getByRole('progressbar', { name: 'Tracking progress' })).toHaveAttribute('aria-valuenow', '85');
    await act(() => vi.advanceTimersByTimeAsync(1600));
    expect(await screen.findByRole('slider', { name: /Timeline/ })).toBeInTheDocument();
    expect(api.find('GET', '/api/tracks/100/frames')).toHaveLength(1);
    expect(api.find('GET', '/api/tracks/100')).toHaveLength(4);
  });

  it('a failed track offers Retry and Pick a different frame', async () => {
    const { user, api } = setup({
      at: '/videos/1/track/100',
      routes: {
        'GET /api/tracks/100': track({ status: 'failed', stage: 'tracking', error_message: 'Player left the frame' }),
        'POST /api/videos/1/tracks': [202, track({ track_id: 101 })],
        'GET /api/tracks/101': track({ track_id: 101 }),
      },
    });
    expect(await screen.findByText('Tracking failed: Player left the frame')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(where()).toBe('/videos/1/track/101'));
    expect(api.find('POST', '/api/videos/1/tracks')[0].body).toMatchObject({ frame: 40, bbox: [0.18, 0.43, 0.034, 0.144], player_id: 24, team: 'A' });
  });
});

describe('Track a player: replay', () => {
  it('mode toggle: annotated disabled (with the reason) when the server made no annotated video', async () => {
    setup({ at: '/videos/1/track/100', routes: { 'GET /api/tracks/100': { ...DONE, annotated_url: null } } });
    const annotated = await screen.findByRole('radio', { name: 'Annotated video' });
    expect(annotated).toBeDisabled();
    expect(screen.getByRole('radio', { name: 'Live overlay' })).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByText(/Annotated video unavailable: The server didn’t produce an annotated video/)).toBeInTheDocument();
  });

  it('mode toggle: live overlay disabled when the original video isn’t served; annotated plays', async () => {
    const { container } = setup({ at: '/videos/1/track/100', video: { ...VIDEO, source_url: null }, routes: { 'GET /api/tracks/100': DONE } });
    const overlay = await screen.findByRole('radio', { name: 'Live overlay' });
    expect(overlay).toBeDisabled();
    expect(screen.getByRole('radio', { name: 'Annotated video' })).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByText(/Live overlay unavailable: The original video isn’t available/)).toBeInTheDocument();
    expect(container.querySelector('[data-media-box] video').getAttribute('src')).toContain('/api/tracks/100/annotated.mp4');
  });

  it('switching modes swaps the source and keeps the frame', async () => {
    const { user, container } = setup({ at: '/videos/1/track/100', routes: { 'GET /api/tracks/100': DONE } });
    await screen.findByRole('slider', { name: /Timeline/ });
    expect(container.querySelector('video').getAttribute('src')).toContain('/api/videos/1/source');
    await user.click(screen.getByRole('radio', { name: 'Annotated video' }));
    expect(container.querySelector('video').getAttribute('src')).toContain('annotated.mp4');
    expect(container.querySelector('canvas')).toHaveAttribute('data-overlay', 'off');
  });

  it('summary stats, issues list and the timeline built from the frames', async () => {
    const { container } = setup({ at: '/videos/1/track/100', routes: { 'GET /api/tracks/100': DONE } });
    await screen.findByRole('slider', { name: /Timeline/ });
    expect(container.querySelector('[data-summary]').textContent).toMatch(/^Tracked 80% of frames · 1 lost segment · longest gap 1\.2 s · 1 re-acquisition · avg conf 0\.\d\d$/);
    const rows = within(container.querySelector('[data-issues]')).getAllByRole('button');
    expect(rows.map((r) => r.textContent)).toEqual(['1Occluded0:03.20–0:04.000.8 s', '2Lost0:06.00–0:07.201.2 s', '3Low conf0:08.00–0:08.480.5 s']);
    const lost = container.querySelectorAll('[data-timeline] rect[data-seg=lost]');
    expect(lost).toHaveLength(1);
    expect(lost[0]).toHaveAttribute('x', '150');
    expect(lost[0]).toHaveAttribute('width', '30');
  });

  it('keyboard: , . step frames, ←/→ 1 s, Shift 5 s, N/P issues, ? sheet; badges follow the frame', async () => {
    const { user, container } = setup({ at: '/videos/1/track/100', routes: { 'GET /api/tracks/100': DONE } });
    await screen.findByRole('slider', { name: /Timeline/ });
    const readout = () => container.querySelector('[data-readout]').textContent;
    await user.keyboard('.');
    expect(readout()).toMatch(/^Frame 1 · conf/);
    await user.keyboard('>');
    expect(readout()).toMatch(/^Frame 2 /);
    await user.keyboard(',');
    expect(readout()).toMatch(/^Frame 1 /);
    await user.keyboard('{ArrowRight}');
    expect(readout()).toMatch(/^Frame 26 /);
    await user.keyboard('{Shift>}{ArrowRight}{/Shift}');
    expect(readout()).toMatch(/^Frame 151 · Lost/);
    expect(screen.getByText('Player lost')).toBeInTheDocument();
    await user.keyboard('{ArrowLeft}');
    expect(readout()).toMatch(/^Frame 126 /);
    await user.keyboard('n');
    expect(readout()).toMatch(/^Frame 150 · Lost · issue 2 of 3/);
    await user.keyboard('p');
    expect(readout()).toMatch(/^Frame 80 · Occluded/);
    expect(container.querySelector('[data-badge=occluded]')).toHaveTextContent('Occluded · estimated position');
    expect(screen.queryByText('Player lost')).toBeNull();
    await user.keyboard('n');
    await user.keyboard('n');
    expect(readout()).toMatch(/^Frame 200 · Low conf/);
    expect(container.querySelector('[data-badge=low]')).toBeInTheDocument();
    await user.keyboard('?');
    expect(screen.getByRole('dialog', { name: 'Keyboard shortcuts' })).toHaveTextContent('Shift + ← / →');
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog', { name: 'Keyboard shortcuts' })).toBeNull();
    // Typing in a form field never triggers shortcuts.
    const speed = screen.getByLabelText('Playback speed');
    expect([...speed.options].map((o) => o.textContent)).toEqual(['0.25×', '0.5×', '1×', '1.5×', '2×']);
    fireEvent.keyDown(speed, { key: '.' });
    expect(readout()).toMatch(/^Frame 200 /);
  });

  it('timeline is an accessible slider: arrows step, click seeks', async () => {
    const { user, container } = setup({ at: '/videos/1/track/100', routes: { 'GET /api/tracks/100': DONE } });
    const slider = await screen.findByRole('slider', { name: /Timeline/ });
    slider.focus();
    await user.keyboard('{End}');
    expect(slider).toHaveAttribute('aria-valuenow', '249');
    await user.keyboard('{Home}{ArrowRight}');
    expect(slider).toHaveAttribute('aria-valuenow', '1');
    slider.getBoundingClientRect = () => ({ left: 0, width: 500, top: 0, height: 40, right: 500, bottom: 40 });
    fireEvent.pointerDown(slider, { clientX: 300, pointerId: 1 });
    expect(slider).toHaveAttribute('aria-valuenow', '150');
    expect(slider).toHaveAttribute('aria-valuetext', '0:06.00, player lost');
    expect(container.querySelector('[data-badge=lost]')).toBeInTheDocument();
  });

  it('issue row click seeks and turns on loop', async () => {
    const { user, container } = setup({ at: '/videos/1/track/100', routes: { 'GET /api/tracks/100': DONE } });
    await screen.findByRole('slider', { name: /Timeline/ });
    await user.click(within(container.querySelector('[data-issues]')).getAllByRole('button')[2]);
    expect(container.querySelector('[data-readout]').textContent).toMatch(/^Frame 200 /);
    expect(screen.getByRole('button', { name: 'Loop issue' })).toHaveAttribute('aria-pressed', 'true');
  });
});

// Backend v0.5.0 extras: 409 track_id, stub banner + warnings, stats (nullable), summary, error_code, stages.
describe('Track a player: v0.5.0 fields', () => {
  const SUMMARY = {
    tracked_frames: 180,
    occluded_frames: 20,
    lost_frames: 50,
    coverage_pct: 87,
    avg_conf: 0.81,
    reacquisition_count: 2,
    lost_segments: [
      [150, 179],
      [240, 245],
    ],
  };

  it('409 {detail, track_id} links to that running track', async () => {
    const { user, container } = setup({
      routes: {
        'POST /api/videos/1/tracks': [409, { detail: 'A track is already running for this video', track_id: 12, status: 'processing', progress: 40 }],
        'GET /api/videos/1/tracks': seq([200, []], [200, []]),
      },
    });
    await waitFor(() => expect(container.querySelectorAll('[data-det]')).toHaveLength(6));
    await user.click(container.querySelector('[data-det^="24-"]'));
    await user.click(screen.getByRole('button', { name: 'Track this player' }));
    expect(await screen.findByText(/already running for this video/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /View the running track/ })).toHaveAttribute('href', '/videos/1/track/12');
  });

  it('stub banner + other warnings; server summary; stats shown when present', async () => {
    const { container } = setup({
      at: '/videos/1/track/100',
      routes: {
        'GET /api/tracks/100': {
          ...DONE,
          source: 'stub',
          warnings: ['STUB: fake demo track', 'Clip shorter than 10 s'],
          summary: SUMMARY,
          stats: { top_speed_mph: 17.2, distance_km: 0.42 },
        },
      },
    });
    await screen.findByRole('slider', { name: /Timeline/ });
    expect(screen.getByText(/Stub track: generated by the server’s stub tracker/)).toBeInTheDocument();
    expect(
      within(container.querySelector('[data-track-warnings]'))
        .getAllByRole('listitem')
        .map((li) => li.textContent),
    ).toEqual(['Clip shorter than 10 s']);
    const summary = container.querySelector('[data-summary]');
    expect(summary).toHaveAttribute('data-summary', 'server');
    expect(summary).toHaveTextContent('Tracked 87% of frames · 2 lost segments');
    expect(summary).toHaveTextContent('2 re-acquisitions · avg conf 0.81');
    expect(container.querySelector('[data-track-stats]')).toHaveTextContent('17.2 mph');
    expect(container.querySelector('[data-track-stats]')).toHaveTextContent('0.42 km');
    // lost_segments [240, 245] (not lost in the frames) still shows as a stripe and an Issue
    expect(container.querySelector('[data-seg="lost"][x="240"]')).toBeInTheDocument();
    expect(screen.getAllByText('Lost').length).toBeGreaterThanOrEqual(2);
  });

  it('stats null → the stats block is hidden; no banner for a real track without warnings', async () => {
    const { container } = setup({ at: '/videos/1/track/100', routes: { 'GET /api/tracks/100': { ...DONE, source: 'real', warnings: [], stats: null, summary: SUMMARY } } });
    await screen.findByRole('slider', { name: /Timeline/ });
    expect(container.querySelector('[data-track-stats]')).toBeNull();
    expect(container.querySelector('[data-track-notice]')).toBeNull();
  });

  it('failed with error_code explains it', async () => {
    setup({ at: '/videos/1/track/100', routes: { 'GET /api/tracks/100': track({ status: 'failed', stage: 'failed', error_message: null, error_code: 'target_not_found' }) } });
    expect(await screen.findByText('Tracking failed: The tracker couldn’t find that player on the chosen frame.')).toBeInTheDocument();
  });

  it('the stepper shows the detect stage', async () => {
    setup({ at: '/videos/1/track/100', routes: { 'GET /api/tracks/100': track({ status: 'processing', stage: 'detect', progress: 10 }) } });
    await screen.findByText(/Finding players · 10%/);
    expect(document.querySelector('[data-track-progress] [aria-current=step]')).toHaveTextContent('Finding players');
  });

  it('503 (not migrated) shows the unavailable state with the server’s reason', async () => {
    setup({ routes: { 'GET /api/videos/1/tracks': [503, { detail: 'Player tracking needs migrations/008_player_tracks.sql' }] } });
    expect(await screen.findByRole('heading', { name: 'Player tracking isn’t available on this server yet' })).toBeInTheDocument();
    expect(screen.getByText(/migrations\/008/)).toBeInTheDocument();
  });
});
