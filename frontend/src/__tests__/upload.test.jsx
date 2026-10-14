import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import Upload from '../pages/Upload';
import { ME, mockFetch, mockXHR, seq, signIn } from '../test/mockApi';
import { renderRoutes } from '../test/render';

const MB = 1024 * 1024;
const video = (name = 'match.mp4', size = 1000, type = 'video/mp4') => {
  const f = new File(['x'], name, { type });
  Object.defineProperty(f, 'size', { value: size });
  return f;
};

// /api/config says 2 MB, mp4 + mov; no saved matches; no past tags.
function setup({ routes = {}, userOptions } = {}) {
  signIn();
  const api = mockFetch({
    'GET /api/auth/me': ME,
    'GET /api/config': { max_upload_mb: 2, allowed_extensions: ['mp4', 'mov'] },
    'GET /api/matches': [200, []],
    'GET /api/tags': [200, []],
    ...routes,
  });
  const utils = renderRoutes({ at: '/upload', protectedRoutes: { '/upload': <Upload /> }, stubs: ['/videos/:id'], userOptions });
  const fileInput = () => utils.container.querySelector('input[type=file]');
  return { api, ...utils, fileInput };
}

async function pickFile(fileInput, file) {
  // fireEvent bypasses the accept attribute, like a drag-and-drop would.
  await act(async () => fireEvent.change(fileInput(), { target: { files: [file] } }));
}

async function fillMatch(user) {
  await user.type(screen.getByLabelText('Match date'), '2026-09-27');
  await user.type(screen.getByLabelText('Home team'), 'Capstone FC');
  await user.type(screen.getByLabelText('Away team'), 'Rival United');
}

describe('Upload: file checks from /api/config', () => {
  it('uses the server limits in the copy', async () => {
    setup();
    expect(await screen.findByText(/MP4 or MOV, up to 2 MB\./)).toBeInTheDocument();
  });

  it('rejects an unsupported type', async () => {
    const { fileInput } = setup();
    await screen.findByText(/up to 2 MB\./);
    await pickFile(fileInput, video('notes.txt', 100, 'text/plain'));
    expect(screen.getByRole('alert')).toHaveTextContent('“notes.txt” isn’t a supported video. Use MP4 or MOV.');
    expect(screen.queryByLabelText('Match title')).not.toBeInTheDocument();
  });

  it('rejects an extension the server does not allow (avi not in config)', async () => {
    const { fileInput } = setup();
    await screen.findByText(/up to 2 MB\./);
    await pickFile(fileInput, video('clip.avi', 100, 'video/x-msvideo'));
    expect(screen.getByRole('alert')).toHaveTextContent('isn’t a supported video. Use MP4 or MOV.');
  });

  it('rejects a file over the configured size', async () => {
    const { fileInput } = setup();
    await screen.findByText(/up to 2 MB\./);
    await pickFile(fileInput, video('big.mp4', 3 * MB));
    expect(screen.getByRole('alert')).toHaveTextContent('“big.mp4” is 3.0 MB, over the 2 MB limit.');
  });

  it('accepts a valid file and prefills the title', async () => {
    const { fileInput } = setup();
    await screen.findByText(/up to 2 MB\./);
    await pickFile(fileInput, video('U16 final.mov', 1.5 * MB, 'video/quicktime'));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Match title')).toHaveValue('U16 final');
  });
});

describe('Upload: server errors', () => {
  it('413 shows the server detail', async () => {
    mockXHR(() => [413, { detail: 'File too large (max 2 MB)' }]);
    const { user, fileInput } = setup();
    await screen.findByText(/up to 2 MB\./);
    await pickFile(fileInput, video());
    await fillMatch(user);
    await user.click(screen.getByRole('button', { name: 'Start analysis' }));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('File too large (max 2 MB)');
    expect(screen.getByRole('button', { name: 'Retry upload' })).toBeInTheDocument();
  });

  it('415 shows the allowed types', async () => {
    mockXHR(() => [415, { detail: 'Unsupported Media Type' }]);
    const { user, fileInput } = setup();
    await screen.findByText(/up to 2 MB\./);
    await pickFile(fileInput, video());
    await fillMatch(user);
    await user.click(screen.getByRole('button', { name: 'Start analysis' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Unsupported file type (use MP4 or MOV)');
  });

  it('requires the match fields before uploading', async () => {
    const xhr = mockXHR(() => [202, { id: 1 }]);
    const { user, fileInput } = setup();
    await screen.findByText(/up to 2 MB\./);
    await pickFile(fileInput, video());
    await user.click(screen.getByRole('button', { name: 'Start analysis' }));
    expect(screen.getByText('Enter the match date.')).toBeInTheDocument();
    expect(screen.getByText('Enter the home team.')).toBeInTheDocument();
    expect(xhr.sent).toHaveLength(0);
  });
});

describe('Upload: tags, score and processing stages', () => {
  it('sends tags + our_side, PATCHes the score and follows the stages to done', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const xhr = mockXHR(() => [202, { id: 7, match_id: 3, status: 'queued', stage: 'queued', progress: 0 }]);
    const { user, api, fileInput } = setup({
      userOptions: { advanceTimers: vi.advanceTimersByTime },
      routes: {
        'PATCH /api/matches/3': (req) => ({ match_id: 3, ...req.body, result: 'W' }),
        'GET /api/videos/7': seq(
          { id: 7, status: 'processing', stage: 'detect', progress: 30 },
          { id: 7, status: 'processing', stage: 'track', progress: 72 },
          { id: 7, status: 'processing', stage: 'ocr', progress: 75 },
          { id: 7, status: 'processing', stage: 'metrics', progress: 78 },
          { id: 7, status: 'done', stage: 'done', progress: 100 },
        ),
      },
    });
    await screen.findByText(/up to 2 MB\./);
    await pickFile(fileInput, video());
    await fillMatch(user);

    // Tags: add, replace (one value per key), remove.
    const key = screen.getByLabelText('Tag');
    const value = screen.getByLabelText('Value');
    await user.type(key, 'Weather');
    await user.type(value, 'rainy{Enter}');
    await user.type(key, 'weather');
    await user.type(value, 'Sunny{Enter}');
    expect(screen.getByText('Replaced Weather: Rainy with Sunny (one value per tag).')).toBeInTheDocument();
    await user.type(key, 'Pitch');
    await user.type(value, 'Turf{Enter}');
    await user.type(key, 'Attendance');
    await user.type(value, 'Busy{Enter}');
    await user.click(screen.getByRole('button', { name: 'Remove Attendance: Busy' }));
    const list = screen.getByRole('list', { name: 'Tags on this match' });
    expect(within(list).getAllByRole('listitem').map((li) => li.textContent)).toEqual(['Weather·Sunny', 'Pitch·Turf']);

    // Score: away side, 1-2 -> a win for us.
    await user.click(screen.getByRole('radio', { name: 'Away · Rival United' }));
    const [home, away] = screen.getAllByPlaceholderText('–');
    await user.type(home, '1');
    await user.type(away, '2');
    expect(screen.getByTitle('Win')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Start analysis' }));
    await waitFor(() => expect(xhr.sent).toHaveLength(1));
    const form = xhr.sent[0].form;
    expect(JSON.parse(form.get('tags'))).toEqual([
      { key: 'Weather', value: 'Sunny' },
      { key: 'Pitch', value: 'Turf' },
    ]);
    expect(form.get('our_side')).toBe('away');
    expect(form.get('home_team')).toBe('Capstone FC');
    expect(xhr.sent[0].headers.Authorization).toBe('Bearer test-token');

    const current = () => document.querySelector('li[aria-current=step]')?.textContent;
    await waitFor(() => expect(current()).toBe('Detecting players (queued)'));
    await waitFor(() => expect(api.find('PATCH', '/api/matches/3')).toHaveLength(1));
    expect(api.find('PATCH', '/api/matches/3')[0].body).toEqual({ home_score: 1, away_score: 2 });

    // Step through fake time in small slices and record each distinct current step.
    const seen = [];
    for (let i = 0; i < 60 && !screen.queryAllByText('Analysis complete.').length; i += 1) {
      await act(() => vi.advanceTimersByTimeAsync(250));
      const c = current();
      if (c && c !== seen[seen.length - 1]) seen.push(c);
    }
    expect(seen).toEqual(['Detecting players', 'Tracking', 'Reading jersey numbers', 'Computing metrics']);
    expect(await screen.findAllByRole('link', { name: 'View results' })).not.toHaveLength(0);
    expect(api.find('GET', '/api/videos/7')).toHaveLength(5);
  });

  it('shows the failed step when processing fails', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mockXHR(() => [202, { id: 8, status: 'queued', stage: 'queued', progress: 0 }]);
    const { user, fileInput } = setup({
      userOptions: { advanceTimers: vi.advanceTimersByTime },
      routes: { 'GET /api/videos/8': { id: 8, status: 'failed', stage: 'failed', progress: 72, error_message: 'Tracker crashed' } },
    });
    await screen.findByText(/up to 2 MB\./);
    await pickFile(fileInput, video());
    await fillMatch(user);
    await user.click(screen.getByRole('button', { name: 'Start analysis' }));
    await act(() => vi.advanceTimersByTimeAsync(400));
    expect(await screen.findByText('Failed at tracking')).toBeInTheDocument();
    expect(screen.getByText(/Tracker crashed/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Report issue/ })).toHaveAttribute('href', expect.stringMatching(/^mailto:/));
  });
});
