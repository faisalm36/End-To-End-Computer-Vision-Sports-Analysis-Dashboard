import { describe, expect, it } from 'vitest';
import {
  bboxToRect,
  buildIssues,
  buildSegments,
  fitRect,
  frameToTime,
  frameView,
  nextIssue,
  normalizeDetections,
  normalizeFrames,
  normalizeTrack,
  lostRuns,
  prevIssue,
  seekTimeForFrame,
  stepFrame,
  summarize,
  timeToFrame,
  trackStep,
} from '../lib/tracking';
import FRAMES from '../test/fixtures/track-frames.json';

const data = normalizeFrames(FRAMES);

describe('frame ↔ time at the native fps', () => {
  it('t = f / fps and f = round(t * fps), clamped', () => {
    expect(frameToTime(50, 25)).toBe(2);
    expect(timeToFrame(2, 25)).toBe(50);
    expect(timeToFrame(2.019, 25)).toBe(50);
    expect(timeToFrame(2.021, 25)).toBe(51);
    expect(timeToFrame(-1, 25, 250)).toBe(0);
    expect(timeToFrame(99, 25, 250)).toBe(249);
    expect(frameToTime(1, 29.97)).toBeCloseTo(0.033367, 5);
  });
  it('seeking to a frame lands inside it and maps back to the same frame', () => {
    for (const fps of [24, 25, 29.97, 30, 50, 60]) for (const f of [0, 1, 7, 123, 999]) expect(timeToFrame(seekTimeForFrame(f, fps), fps)).toBe(f);
  });
  it('frame step clamps to the clip', () => {
    expect(stepFrame(0, -1, 250)).toBe(0);
    expect(stepFrame(10, 1, 250)).toBe(11);
    expect(stepFrame(249, 1, 250)).toBe(249);
  });
});

describe('letterboxing (object-fit: contain)', () => {
  it('pillarboxes a 16:9 frame in a tall box and maps normalised boxes', () => {
    const r = fitRect(375, 400, 1920, 1080);
    expect(r.w).toBeCloseTo(375);
    expect(r.h).toBeCloseTo(210.94, 1);
    expect(r.y).toBeCloseTo((400 - 210.9375) / 2);
    const b = bboxToRect([0.5, 0.5, 0.1, 0.2], r);
    expect(b.x).toBeCloseTo(187.5);
    expect(b.y).toBeCloseTo(r.y + 105.47, 1);
  });
  it('letterboxes sideways in a wide box', () => {
    const r = fitRect(1000, 300, 640, 360);
    expect(r.h).toBe(300);
    expect(r.w).toBeCloseTo(533.33, 1);
    expect(r.x).toBeCloseTo(233.33, 1);
  });
});

describe('segments, summary and issues from per-frame track data', () => {
  it('builds runs of tracked / occluded / lost', () => {
    expect(buildSegments(data.frames)).toEqual([
      { state: 'tracked', start: 0, end: 79 },
      { state: 'occluded', start: 80, end: 99 },
      { state: 'tracked', start: 100, end: 149 },
      { state: 'lost', start: 150, end: 179 },
      { state: 'tracked', start: 180, end: 249 },
    ]);
  });
  it('summary: % tracked, longest lost gap, re-acquisitions, avg conf', () => {
    const s = summarize(data.frames, 25);
    expect(s.trackedPct).toBe(80);
    expect(s.lostSegments).toBe(1);
    expect(s.longestLostFrames).toBe(30);
    expect(s.longestLostSec).toBeCloseTo(1.2);
    expect(s.reacquisitions).toBe(1);
    expect(s.avgConf).toBeGreaterThan(0.7);
    expect(s.avgConf).toBeLessThan(0.9);
  });
  it('issues: occluded, lost and low-confidence runs with times', () => {
    const issues = buildIssues(data.frames, 25);
    expect(issues.map((i) => [i.kind, i.start, i.end])).toEqual([
      ['occluded', 80, 99],
      ['lost', 150, 179],
      ['low', 200, 211],
    ]);
    expect(issues[1].startT).toBe(6);
    expect(issues[1].duration).toBeCloseTo(1.2);
    expect(nextIssue(issues, 0).start).toBe(80);
    expect(nextIssue(issues, 80).start).toBe(150);
    expect(nextIssue(issues, 240)).toBeNull();
    expect(prevIssue(issues, 160).start).toBe(80);
    expect(prevIssue(issues, 120).start).toBe(80);
    expect(prevIssue(issues, 10)).toBeNull();
  });
  it('a gap in the frames list counts as lost; missing frame_count is derived', () => {
    const d = normalizeFrames({
      fps: 10,
      frames: [
        { f: 0, bbox: [0.1, 0.1, 0.1, 0.1], conf: 0.9, state: 'tracked' },
        { f: 3, bbox: [0.1, 0.1, 0.1, 0.1], conf: 0.9 },
      ],
    });
    expect(d.frame_count).toBe(4);
    expect(d.frames.map((r) => r.state)).toEqual(['tracked', 'lost', 'lost', 'tracked']);
    expect(summarize(d.frames, 10).reacquisitions).toBe(1);
  });
});

describe('badge state per frame', () => {
  it('lost (no box), occluded (estimated box), low confidence (dashed), tracked', () => {
    expect(frameView(data.frames, 160)).toMatchObject({ state: 'lost', bbox: null });
    expect(frameView(data.frames, 90)).toMatchObject({ state: 'occluded', estimate: true });
    expect(frameView(data.frames, 90).bbox).not.toBeNull();
    expect(frameView(data.frames, 205)).toMatchObject({ state: 'tracked', low: true });
    expect(frameView(data.frames, 10)).toMatchObject({ state: 'tracked', low: false, estimate: false });
  });
});

describe('adapter', () => {
  it('normalises a track (target with team/frame/bbox, annotated_url null until done)', () => {
    const t = normalizeTrack({
      track_id: 3,
      video_id: 6,
      status: 'processing',
      stage: 'Tracking',
      progress: '42',
      target: { player_id: null, jersey_number: 10, team: 'A', frame: 120, bbox: [0.4, 0.3, 0.05, 0.16] },
      fps: 25,
      annotated_url: null,
    });
    expect(t).toMatchObject({ track_id: 3, status: 'processing', stage: 'tracking', progress: 42, annotated_url: null });
    expect(t.target).toEqual({ player_id: null, jersey_number: 10, team: 'A', frame: 120, t: null, mode: null, bbox: [0.4, 0.3, 0.05, 0.16] });
    expect(trackStep(t).current).toBe(2);
    expect(trackStep({ ...t, stage: 'rendering' }).current).toBe(3);
    expect(trackStep({ ...t, status: 'done' }).current).toBe(4);
    expect(trackStep({ ...t, status: 'queued', stage: 'queued' }).current).toBe(0);
  });
  it('normalises detections: null player_id, class, team, invalid boxes dropped', () => {
    const d = normalizeDetections({
      frame: 5,
      players: [
        { player_id: null, jersey_number: null, team: 'B', class: 'referee', bbox: [0.1, 0.2, 0.05, 0.1], conf: 0.7 },
        { player_id: 1, bbox: [0, 0, 0, 0] },
        { player_id: 2, class: 'coach', bbox: [0.2, 0.2, 0.1, 0.1] },
      ],
    });
    expect(d.players).toHaveLength(2);
    expect(d.players[0]).toMatchObject({ player_id: null, jersey_number: null, team: 'B', cls: 'referee' });
    expect(d.players[1].cls).toBe('player');
  });
});

describe('adapter: backend v0.5.0 track object', () => {
  const RAW = {
    track_id: 3,
    video_id: 6,
    status: 'failed',
    stage: 'tracking',
    progress: 55,
    error_message: null,
    error_code: 'target_not_found',
    target: { mode: 'bbox', player_id: 24, jersey_number: 10, team: 'A', frame: 120, t: 4.8, bbox: [0.41, 0.33, 0.05, 0.16] },
    fps: 25,
    frame_count: 250,
    width: 1920,
    height: 1080,
    annotated_url: null,
    frames_url: '/api/tracks/3/frames?token=k',
    source: 'stub',
    summary: {
      tracked_frames: 210,
      occluded_frames: 15,
      lost_frames: 25,
      coverage_pct: 90,
      avg_conf: 0.81,
      reacquisition_count: 2,
      lost_segments: [
        [80, 92],
        [150, 162],
      ],
      player_uid: 'u',
    },
    stats: { top_speed_mph: 17.2, distance_km: 0.42 },
    warnings: ['STUB: fake demo track'],
    created_at: 'a',
    updated_at: 'b',
    finished_at: 'c',
  };
  it('keeps the new fields: summary, stats, warnings, error_code, finished_at, target.mode/t', () => {
    const t = normalizeTrack(RAW);
    expect(t).toMatchObject({
      track_id: 3,
      fps: 25,
      frame_count: 250,
      width: 1920,
      height: 1080,
      source: 'stub',
      error_code: 'target_not_found',
      finished_at: 'c',
      warnings: ['STUB: fake demo track'],
    });
    expect(t.target).toMatchObject({ mode: 'bbox', t: 4.8, bbox: [0.41, 0.33, 0.05, 0.16] });
    expect(t.summary).toMatchObject({
      coverage_pct: 90,
      avg_conf: 0.81,
      reacquisition_count: 2,
      lost_segments: [
        [80, 92],
        [150, 162],
      ],
    });
    expect(t.stats).toEqual({ top_speed_mph: 17.2, distance_km: 0.42 });
    expect(normalizeTrack({ ...RAW, stats: null, summary: null })).toMatchObject({ stats: null, summary: null });
  });

  it('stages: queued → detect → tracking → rendering → done; unknown names shown as-is', () => {
    const t = normalizeTrack({ ...RAW, status: 'processing', error_code: null });
    expect(trackStep({ ...t, status: 'queued', stage: 'queued' }).current).toBe(0);
    expect(trackStep({ ...t, stage: 'detect' }).current).toBe(1);
    expect(trackStep({ ...t, stage: 'tracking' }).current).toBe(2);
    expect(trackStep({ ...t, stage: 'rendering' }).current).toBe(3);
    expect(trackStep({ ...t, status: 'done', stage: 'done' }).current).toBe(4);
    expect(trackStep({ ...t, stage: 'reid' })).toMatchObject({ current: 1, unknown: 'reid' });
  });

  it('frames: occluded keeps its (interpolated) box, lost has bbox null and no confidence', () => {
    const d = normalizeFrames({
      fps: 25,
      frame_count: 3,
      frames: [
        { f: 0, bbox: [0.1, 0.1, 0.1, 0.2], conf: 0.9, state: 'tracked' },
        { f: 1, bbox: [0.12, 0.1, 0.1, 0.2], conf: 0.31, state: 'occluded' },
        { f: 2, bbox: null, conf: 0, state: 'lost' },
      ],
    });
    expect(d.frames.map((r) => r.state)).toEqual(['tracked', 'occluded', 'lost']);
    expect(d.frames[2]).toMatchObject({ bbox: null, conf: null });
    expect(frameView(d.frames, 1)).toMatchObject({ state: 'occluded', estimate: true });
  });

  it('summary uses the server numbers; lost_segments feed the timeline runs and the Issues list', () => {
    const s = summarize(data.frames, 25, normalizeTrack(RAW).summary);
    expect(s).toMatchObject({ trackedPct: 90, lostSegments: 2, avgConf: 0.81, reacquisitions: 2, fromServer: true });
    const runs = lostRuns(data.frames, [
      [10, 12],
      [150, 162],
    ]);
    expect(runs).toContainEqual({ start: 10, end: 12 });
    expect(runs).toContainEqual({ start: 150, end: 179 }); // merged with the frames' own lost run 150-179
    const lost = buildIssues(data.frames, 25, { lostSegments: [[10, 12]] }).filter((i) => i.kind === 'lost');
    expect(lost.map((i) => [i.start, i.end])).toEqual([
      [10, 12],
      [150, 179],
    ]);
  });
});

describe('contract frames window', () => {
  it('passes inclusive ?start&end to /tracks/{id}/frames', async () => {
    const { mockFetch, signIn } = await import('../test/mockApi');
    const api = await import('../lib/api');
    signIn();
    const calls = mockFetch({ 'GET /api/tracks/5/frames': { fps: 25, frame_count: 3, frames: [{ f: 1, bbox: [0.1, 0.1, 0.1, 0.1], conf: 0.9, state: 'tracked' }] } });
    const d = await api.getTrackFrames(5, { start: 1, end: 2 });
    expect(calls.find('GET', '/api/tracks/5/frames')[0].params.get('start')).toBe('1');
    expect(calls.find('GET', '/api/tracks/5/frames')[0].params.get('end')).toBe('2');
    expect(d.frames[1].state).toBe('tracked');
  });
});
