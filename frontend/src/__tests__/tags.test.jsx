import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { TagChip, TagInput, TagList } from '../components/Tags';
import { matchesTagFilter, tagsOf, upsertTag } from '../lib/tags';
import Profile from '../pages/Profile';
import { ME, mockFetch, signIn } from '../test/mockApi';
import { renderRoutes } from '../test/render';

const tag = (key, value) => ({ key, value });

describe('TagChip variants', () => {
  it('static: key · value, no controls', () => {
    render(<TagChip tag={tag('Weather', 'Rainy')} />);
    expect(screen.getByText('Weather')).toBeInTheDocument();
    expect(screen.getByText('Rainy')).toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  it('removable: a labelled remove button', async () => {
    const onRemove = vi.fn();
    render(<TagChip tag={tag('Pitch', 'Turf')} variant="removable" onRemove={onRemove} />);
    await userEvent.click(screen.getByRole('button', { name: 'Remove Pitch: Turf' }));
    expect(onRemove).toHaveBeenCalledTimes(1);
  });

  it('selectable: a toggle button with aria-pressed and an optional count', async () => {
    const onToggle = vi.fn();
    const { rerender } = render(<TagChip tag={tag('Weather', 'Sunny')} variant="selectable" count={4} onToggle={onToggle} />);
    const b = screen.getByRole('button', { name: /Weather.*Sunny.*4/ });
    expect(b).toHaveAttribute('aria-pressed', 'false');
    await userEvent.click(b);
    expect(onToggle).toHaveBeenCalled();
    rerender(<TagChip tag={tag('Weather', 'Sunny')} variant="selectable" selected count={4} onToggle={onToggle} />);
    expect(screen.getByRole('button', { name: /Sunny/ })).toHaveAttribute('aria-pressed', 'true');
  });

  it('TagList: shows max chips then a "+N" popover with the rest', async () => {
    const tags = [tag('Weather', 'Rainy'), tag('Pitch', 'Turf'), tag('Opponent', 'Rivals'), tag('Competition', 'Cup')];
    render(<TagList tags={tags} max={2} />);
    expect(screen.queryByText('Cup')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Show 2 more tags' }));
    expect(screen.getByText('Cup')).toBeInTheDocument();
    expect(screen.getByText('Rivals')).toBeInTheDocument();
  });
});

describe('TagInput', () => {
  function Harness({ initial = [], index = [] }) {
    const [tags, setTags] = useState(initial);
    return <TagInput tags={tags} onChange={setTags} index={index} idPrefix="t" />;
  }

  it('adds, replaces a key’s value, and removes', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.type(screen.getByLabelText('Tag'), 'weather');
    await user.type(screen.getByLabelText('Value'), 'raining{Enter}');
    expect(screen.getByText('Added Weather: Raining.')).toBeInTheDocument(); // preset casing
    await user.type(screen.getByLabelText('Tag'), 'Weather');
    await user.type(screen.getByLabelText('Value'), 'Sunny');
    await user.click(screen.getByRole('button', { name: 'Add' }));
    expect(screen.getByText('Replaced Weather: Raining with Sunny (one value per tag).')).toBeInTheDocument();
    const list = screen.getByRole('list', { name: 'Tags on this match' });
    expect(within(list).getAllByRole('listitem')).toHaveLength(1);
    await user.click(screen.getByRole('button', { name: 'Remove Weather: Sunny' }));
    expect(screen.queryByRole('list', { name: 'Tags on this match' })).not.toBeInTheDocument();
    expect(screen.getByText('Removed Weather: Sunny.')).toBeInTheDocument();
  });

  it('quick-add chips fill the key and hide once used', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole('button', { name: '+ Pitch' }));
    expect(screen.getByLabelText('Tag')).toHaveValue('Pitch');
    await user.type(screen.getByLabelText('Value'), 'Turf{Enter}');
    expect(screen.queryByRole('button', { name: '+ Pitch' })).not.toBeInTheDocument();
  });

  it('rejects an empty key, a missing value and a ":" in the key', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole('button', { name: 'Add' }));
    expect(screen.getByText('Enter a tag name, like Weather.')).toBeInTheDocument();
    await user.type(screen.getByLabelText('Tag'), 'Kick:off');
    await user.click(screen.getByRole('button', { name: 'Add' }));
    expect(screen.getByText('Tag names can’t contain “:”.')).toBeInTheDocument();
    await user.clear(screen.getByLabelText('Tag'));
    await user.type(screen.getByLabelText('Tag'), 'Opponent');
    await user.click(screen.getByRole('button', { name: 'Add' }));
    expect(screen.getByText('Enter a value for Opponent.')).toBeInTheDocument();
  });

  it('keeps the server’s tag spelling (no "Kickoff Time" from "Kickoff time")', () => {
    expect(tagsOf({ tags: [tag('Kickoff time', 'Evening'), tag('weather', 'raining'), tag('Pitch', '3G')] })).toEqual([
      tag('Kickoff time', 'Evening'),
      tag('Weather', 'Raining'),
      tag('Pitch', '3G'),
    ]);
  });

  it('upsertTag keeps one value per key (case-insensitive)', () => {
    const { tags, replaced } = upsertTag([tag('Weather', 'Rainy')], tag('weather', 'Sunny'));
    expect(tags).toHaveLength(1);
    expect(tags[0].value).toBe('Sunny');
    expect(replaced).toEqual(tag('Weather', 'Rainy'));
  });
});

describe('History tag filter logic', () => {
  const v = (tags) => ({ tags });
  const rainyTurf = v([tag('Weather', 'Rainy'), tag('Pitch', 'Turf')]);
  const sunnyGrass = v([tag('Weather', 'Sunny'), tag('Pitch', 'Grass')]);
  const snowTurf = v([tag('Weather', 'Snow'), tag('Pitch', 'Turf')]);
  const all = [rainyTurf, sunnyGrass, snowTurf];
  const run = (sel) => all.filter((x) => matchesTagFilter(x, sel));

  it('no selection matches everything', () => expect(run([])).toHaveLength(3));
  it('same key = OR', () => expect(run([tag('Weather', 'Rainy'), tag('Weather', 'Sunny')])).toEqual([rainyTurf, sunnyGrass]));
  it('different keys = AND', () => expect(run([tag('Weather', 'Rainy'), tag('Weather', 'Snow'), tag('Pitch', 'Turf')])).toEqual([rainyTurf, snowTurf]));
  it('AND can exclude everything', () => expect(run([tag('Weather', 'Sunny'), tag('Pitch', 'Turf')])).toEqual([]));
  it('is case-insensitive', () => expect(run([tag('weather', 'RAINY')])).toEqual([rainyTurf]));
  it('matches any of several values the backend stores for one key', () => {
    expect(matchesTagFilter(v([tag('Opponent', 'Rivals'), tag('Opponent', 'Derby')]), [tag('Opponent', 'Derby')])).toBe(true);
  });
});

describe('Profile history filter', () => {
  const vid = (id, title, tags) => ({ id, title, status: 'done', stage: 'done', progress: 100, match_date: '2026-09-0' + id, created_at: `2026-09-0${id}T12:00:00Z`, tags });
  const VIDEOS = [
    vid(1, 'Rainy turf', [tag('Weather', 'Rainy'), tag('Pitch', 'Turf')]),
    vid(2, 'Sunny grass', [tag('Weather', 'Sunny'), tag('Pitch', 'Grass')]),
    vid(3, 'Sunny turf', [tag('Weather', 'Sunny'), tag('Pitch', 'Turf')]),
    vid(4, 'Untagged', []),
  ];

  async function open({ serverFilters }) {
    signIn();
    const api = mockFetch({
      'GET /api/auth/me': ME,
      'GET /api/tags': [200, []],
      'GET /api/videos': (req) => {
        const sel = req.params.getAll('tag').map((s) => {
          const [k, ...rest] = s.split(':');
          return tag(k, rest.join(':'));
        });
        // serverFilters=false mimics an older backend that ignores ?tag=.
        return [200, serverFilters ? VIDEOS.filter((x) => matchesTagFilter(x, sel)) : VIDEOS];
      },
    });
    const utils = renderRoutes({ at: '/profile', protectedRoutes: { '/profile': <Profile /> }, stubs: ['/videos/:id', '/upload'] });
    await screen.findAllByText('Rainy turf');
    await utils.user.click(screen.getByRole('button', { expanded: false, name: /Tags/ }));
    const pop = screen.getByRole('dialog', { name: 'Filter by tags' });
    const pick = (value) => utils.user.click(within(pop).getByRole('button', { name: new RegExp(value) }));
    const counter = () => document.querySelector('[data-filter-source]');
    return { api, pick, counter };
  }

  for (const serverFilters of [true, false]) {
    it(`OR within a key, AND across keys (${serverFilters ? 'server ?tag= filter' : 'client fallback'})`, async () => {
      const { api, pick, counter } = await open({ serverFilters });
      await pick('Sunny');
      await pick('Rainy');
      await waitFor(() => expect(counter()).toHaveTextContent('Showing 3 of 4'));
      await pick('Turf');
      await waitFor(() => expect(counter()).toHaveTextContent('Showing 2 of 4'));
      await waitFor(() => expect(counter()).toHaveAttribute('data-filter-source', serverFilters ? 'server' : 'client'));
      const last = api.find('GET', '/api/videos').at(-1);
      expect(last.params.getAll('tag').sort()).toEqual(['Pitch:Turf', 'Weather:Rainy', 'Weather:Sunny']);
      expect(screen.queryAllByText('Sunny grass')).toHaveLength(0);
      expect(screen.getAllByText('Sunny turf').length).toBeGreaterThan(0);
    });
  }
});
