import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router';
import { useAuth } from '../auth/useAuth';
import { btn, card, container, focusRing, label } from '../components/classes';
import { ProgressBar } from '../components/Progress';
import PickMode from '../components/track/PickMode';
import Replay from '../components/track/Replay';
import { Icon, NoticeBanner, Skeleton } from '../components/ui';
import { createTrack, deleteTrack, frameSrc, getDetections, getTrack, getTrackFrames, getVideo, getVideoStats, listTracks, annotatedSrc, videoSourceSrc } from '../lib/api';
import { formatDate, videoTitle } from '../lib/format';
import { normalizePlayers } from '../lib/playerStats';
import { SAMPLE_VIDEOS } from '../lib/sampleData';
import * as demo from '../lib/trackDemo';
import { ERROR_CODE_TEXT, TRACK_STEPS, isActiveTrack, targetLabel, trackStep } from '../lib/tracking';

const POLL_MS = 1500;
const backLink = `rounded text-body text-fg-muted hover:text-fg ${focusRing}`;

// Real API vs the labelled sample (demo session only).
const REAL = { getDetections, createTrack, listTracks, getTrack, getTrackFrames, deleteTrack };
const DEMO = {
  getDetections: (_id, f) => demo.demoDetections(f),
  createTrack: demo.demoCreateTrack,
  listTracks: demo.demoListTracks,
  getTrack: demo.demoGetTrack,
  getTrackFrames: demo.demoFrames,
  deleteTrack: demo.demoDeleteTrack,
};

const unavailable = (err) => err?.status === 404 || err?.status === 405 || err?.status === 501 || err?.status === 503;

function videoMeta(video) {
  const pm = video?.pipeline_meta || {};
  const fps = Number(video?.fps ?? pm.fps) || null;
  const dur = Number(video?.duration_seconds ?? pm.duration_s) || null;
  const frameCount = Number(pm.frame_count) || (fps && dur ? Math.round(fps * dur) : null);
  const res = Array.isArray(pm.resolution) ? pm.resolution : [];
  return { fps, frameCount, width: Number(res[0]) || null, height: Number(res[1]) || null };
}

function TrackStepper({ track }) {
  const { current, failed } = trackStep(track);
  return (
    <ol className="flex flex-wrap items-start gap-x-1 gap-y-3 sm:flex-nowrap">
      {TRACK_STEPS.map((s, i) => {
        const isFailed = failed && i === Math.max(1, current);
        const last = TRACK_STEPS.length - 1;
        const done = !failed ? i < current || current === last : i < Math.max(1, current);
        const isCur = !failed && i === current && current < last;
        return (
          <li key={s} aria-current={isCur ? 'step' : undefined} className="flex min-w-[40%] flex-1 items-start gap-2 sm:min-w-0 sm:flex-col sm:items-center sm:text-center">
            <span
              className={`relative flex size-6 shrink-0 items-center justify-center rounded-full ${
                isFailed
                  ? 'bg-risk-high-bg text-risk-high ring-2 ring-risk-high'
                  : done
                    ? 'bg-slate-800 text-slate-100 ring-1 ring-slate-600'
                    : isCur
                      ? 'bg-accent/10 ring-2 ring-accent'
                      : 'ring-1 ring-slate-600'
              }`}
            >
              {isFailed ? (
                <Icon name="x" className="size-3.5" />
              ) : done ? (
                <Icon name="check" className="size-3.5" />
              ) : isCur ? (
                <span className="size-2 rounded-full bg-accent motion-safe:animate-pulse" />
              ) : null}
            </span>
            <span className={`text-caption ${isFailed ? 'font-medium text-risk-high' : done ? 'text-slate-100' : isCur ? 'font-medium text-fg' : 'text-slate-400'}`}>{s}</span>
          </li>
        );
      })}
    </ol>
  );
}

function TrackProgress({ track, onRetry, onPickAgain, retrying }) {
  const failed = track.status === 'failed';
  const { current, unknown } = trackStep(track);
  const codeText = track.error_code ? ERROR_CODE_TEXT[track.error_code] || `Error code: ${track.error_code}` : null;
  const text = failed
    ? `Tracking failed${track.error_message ? `: ${track.error_message}` : codeText ? `: ${codeText}` : ''}`
    : track.status === 'queued'
      ? 'Queued: waiting for the tracker'
      : `${unknown || TRACK_STEPS[current] || track.stage || 'Working'}${track.progress != null ? ` · ${Math.round(track.progress)}%` : ''}`;
  return (
    <section aria-labelledby="track-progress-title" className={`${card} p-5 sm:p-6 ${failed ? 'border-risk-high-ring' : ''}`} data-track-progress>
      <h2 id="track-progress-title" className="text-title text-fg">
        {failed ? 'Couldn’t track this player' : `Tracking ${targetLabel(track.target)}`}
      </h2>
      <p className="mt-1 text-body text-fg-muted">
        {failed
          ? `${codeText && track.error_message ? `${codeText} ` : ''}Try again, or pick the player on a clearer frame.`
          : 'Tracking runs on the server. You can leave this page and come back; it’s listed under Past tracks.'}
      </p>
      <div className="mt-5">
        <TrackStepper track={track} />
        <div className="mt-5">
          <ProgressBar value={failed ? 100 : track.status === 'queued' ? null : track.progress} labelText="Tracking progress" tone={failed ? 'danger' : 'accent'} />
        </div>
        <p className={`mt-2 font-mono text-caption ${failed ? 'text-risk-high' : 'text-fg-secondary'}`} aria-live="polite" role="status">
          {text}
        </p>
        {failed && (
          <div className="mt-4 flex flex-wrap gap-3">
            <button type="button" className={btn.primary} onClick={onRetry} disabled={retrying}>
              {retrying ? 'Retrying…' : 'Retry'}
            </button>
            <button type="button" className={btn.secondary} onClick={onPickAgain}>
              Pick a different frame
            </button>
          </div>
        )}
      </div>
    </section>
  );
}

// Stub banner (source === 'stub') plus any other server warnings, listed.
function TrackNotices({ track }) {
  const stub = track.source === 'stub';
  const others = track.warnings.filter((w) => !(stub && /^STUB\b/i.test(w)));
  if (!stub && !others.length) return null;
  return (
    <NoticeBanner className="mb-4">
      <span data-track-notice={stub ? 'stub' : 'warnings'}>
        {stub && <strong className="font-medium">Stub track: generated by the server’s stub tracker, not real computer vision.</strong>}
        {others.length > 0 && (
          <ul className={`${stub ? 'mt-1 ' : ''}list-disc pl-5`} data-track-warnings>
            {others.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        )}
      </span>
    </NoticeBanner>
  );
}

const PAST_SHOWN = 5;

function PastTracks({ tracks, videoId, currentId, onDelete }) {
  const [confirm, setConfirm] = useState(null);
  const [all, setAll] = useState(false);
  if (!tracks.length) return null;
  const shown = all ? tracks : tracks.slice(0, PAST_SHOWN);
  return (
    <section className={`${card} mt-8 p-4 sm:p-5`} aria-labelledby="past-tracks">
      <h2 id="past-tracks" className={label}>
        Past tracks for this video
      </h2>
      <ul className="mt-3 divide-y divide-line" data-past-tracks>
        {shown.map((t) => (
          <li key={t.track_id} className="flex flex-wrap items-center gap-3 py-2.5">
            <Link
              to={`/videos/${videoId}/track/${t.track_id}`}
              aria-current={String(t.track_id) === String(currentId) ? 'page' : undefined}
              className={`rounded font-mono text-body text-fg underline-offset-4 hover:underline ${focusRing}`}
            >
              {targetLabel(t.target)}
            </Link>
            <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[11px] font-medium text-slate-200 ring-1 ring-slate-600">
              {t.status === 'done'
                ? 'Done'
                : t.status === 'failed'
                  ? 'Failed'
                  : t.status === 'queued'
                    ? 'Queued'
                    : `Running${t.progress != null ? ` ${Math.round(t.progress)}%` : ''}`}
            </span>
            {t.created_at && <span className="text-caption text-fg-muted">{formatDate(t.created_at)}</span>}
            <span className="ml-auto">
              {confirm === t.track_id ? (
                <span className="flex items-center gap-2">
                  <button type="button" className={`${btn.danger} h-9 px-3`} onClick={() => (setConfirm(null), onDelete(t))}>
                    Delete track
                  </button>
                  <button type="button" className={`${btn.ghost} h-9 px-3`} onClick={() => setConfirm(null)}>
                    Keep
                  </button>
                </span>
              ) : (
                <button type="button" className={`${btn.ghost} h-9 px-3`} onClick={() => setConfirm(t.track_id)} aria-label={`Delete track ${targetLabel(t.target)}`}>
                  Delete
                </button>
              )}
            </span>
          </li>
        ))}
      </ul>
      {tracks.length > PAST_SHOWN && (
        <button type="button" className={`${btn.ghost} mt-2 h-9 px-2`} aria-expanded={all} onClick={() => setAll((a) => !a)}>
          {all ? 'Show fewer' : `Show all ${tracks.length}`}
        </button>
      )}
    </section>
  );
}

function LoadingSkeleton() {
  return (
    <div className="grid gap-6 lg:grid-cols-3" aria-busy="true">
      <div className="lg:col-span-2">
        <Skeleton className="aspect-video w-full rounded-2xl" />
        <Skeleton className="mt-6 h-10 w-full" />
      </div>
      <Skeleton className="h-48 w-full" />
    </div>
  );
}

export default function TrackPlayer() {
  const { id, trackId } = useParams();
  const { isDemo } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const api = isDemo ? DEMO : REAL;
  const [page, setPage] = useState({ status: 'loading', video: null, roster: [], error: null });
  const [tracks, setTracks] = useState({ status: 'loading', list: [] });
  // Each async result remembers which track it belongs to, so switching tracks never shows stale data.
  const [trackState, setTrackState] = useState(null);
  const [framesState, setFramesState] = useState(null);
  const [thumbState, setThumbState] = useState(null);
  const track = trackId && trackState?.forId === trackId ? trackState.value : null;
  const frames = trackId && framesState?.forId === trackId ? framesState : null;
  const thumb = trackId && thumbState?.forId === trackId ? thumbState : null;
  const [start, setStart] = useState({ busy: false, error: null, active: null });
  const [retrying, setRetrying] = useState(false);
  const initialFrame = useMemo(() => {
    const f = Number(new URLSearchParams(location.search).get('frame'));
    return Number.isFinite(f) && f >= 0 && location.search.includes('frame=') ? f : null;
  }, [location.search]);

  // Video + roster + tracks list (a 404 on the tracks list = no tracking on this server).
  useEffect(() => {
    const ac = new AbortController();
    (async () => {
      if (isDemo) {
        const v = SAMPLE_VIDEOS.find((x) => String(x.id) === id) || SAMPLE_VIDEOS[0];
        setPage({
          status: 'ready',
          video: { ...v, source_url: demo.DEMO_SOURCE_URL, fps: demo.DEMO_META.fps, duration_seconds: 10, pipeline_meta: { frame_count: 250, resolution: [640, 360] } },
          roster: await demo.demoRoster(),
          error: null,
        });
        setTracks({ status: 'ready', list: await demo.demoListTracks() });
        return;
      }
      const [vRes, sRes, tRes] = await Promise.allSettled([getVideo(id, { signal: ac.signal }), getVideoStats(id, { signal: ac.signal }), listTracks(id, { signal: ac.signal })]);
      if (ac.signal.aborted) return;
      if (vRes.status === 'rejected') {
        setPage({ status: vRes.reason?.status === 404 ? 'notfound' : 'error', video: null, roster: [], error: vRes.reason });
        return;
      }
      const video = vRes.value?.video ?? vRes.value;
      const pending = sRes.status === 'rejected' && sRes.reason?.status === 409;
      setPage({ status: pending ? 'pending' : 'ready', video, roster: sRes.status === 'fulfilled' ? normalizePlayers(sRes.value) : [], error: null });
      if (tRes.status === 'fulfilled') setTracks({ status: 'ready', list: tRes.value });
      else setTracks({ status: unavailable(tRes.reason) ? 'unavailable' : 'error', list: [], error: tRes.reason });
    })();
    return () => ac.abort();
  }, [id, isDemo]);

  const refreshTracks = useCallback(
    () =>
      api
        .listTracks(id)
        .then((list) => setTracks({ status: 'ready', list }))
        .catch(() => {}),
    [api, id],
  );

  // Poll the selected track until it finishes; then load its per-frame data.
  useEffect(() => {
    if (!trackId) return undefined;
    let timer;
    const ac = new AbortController();
    const tick = async () => {
      try {
        const t = await api.getTrack(trackId, { signal: ac.signal });
        if (ac.signal.aborted) return;
        if (!t) throw Object.assign(new Error('Track not found'), { status: 404 });
        setTrackState({ forId: trackId, value: t });
        if (isActiveTrack(t)) timer = setTimeout(tick, POLL_MS);
        else refreshTracks();
      } catch (err) {
        if (ac.signal.aborted) return;
        setTrackState({ forId: trackId, value: { error: err } });
      }
    };
    tick();
    return () => {
      ac.abort();
      clearTimeout(timer);
    };
  }, [trackId, api, refreshTracks]);

  const done = track?.status === 'done';
  useEffect(() => {
    if (!done) return undefined;
    const ac = new AbortController();
    api
      .getTrackFrames(trackId, { signal: ac.signal })
      .then((d) => !ac.signal.aborted && setFramesState({ forId: trackId, status: 'ready', data: d }))
      .catch((err) => !ac.signal.aborted && setFramesState({ forId: trackId, status: 'error', error: err }));
    // Crop thumbnail of the target from the frame it was picked on.
    const f = track.target.frame ?? 0;
    if (track.target.bbox && !isDemo)
      api
        .getDetections(id, f, { signal: ac.signal })
        .then((d) => !ac.signal.aborted && setThumbState({ forId: trackId, src: frameSrc(d.frame_url, f), bbox: track.target.bbox }))
        .catch(() => {});
    return () => ac.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [done, trackId, api, id, isDemo]);

  const loadDetections = useCallback((f, opts) => api.getDetections(id, f, opts), [api, id]);

  const begin = async (body) => {
    setStart({ busy: true, error: null, active: null });
    try {
      const t = await api.createTrack(id, body);
      setStart({ busy: false, error: null, active: null });
      refreshTracks();
      navigate(`/videos/${id}/track/${t.track_id}`);
    } catch (err) {
      if (err?.status === 405 || err?.status === 501) setTracks((s) => ({ ...s, status: 'unavailable' }));
      let active = null;
      if (err?.status === 409) {
        const list = await api.listTracks(id).catch(() => []);
        setTracks({ status: 'ready', list });
        // 409 {detail, track_id, status, progress}: one active track per video.
        const runningId = err.data?.track_id;
        active =
          list.find((t) => runningId != null && String(t.track_id) === String(runningId)) ??
          list.find(isActiveTrack) ??
          (runningId != null ? { track_id: runningId, target: {} } : null);
      }
      setStart({ busy: false, error: err?.message || 'Couldn’t start tracking.', active });
    }
  };
  const retry = async () => {
    const tg = track.target;
    const body =
      tg.bbox && tg.frame != null
        ? { frame: tg.frame, bbox: tg.bbox, player_id: tg.player_id ?? undefined, jersey_number: tg.jersey_number ?? undefined, team: tg.team ?? undefined }
        : { player_id: tg.player_id ?? undefined, jersey_number: tg.jersey_number ?? undefined, team: tg.team ?? undefined };
    setRetrying(true);
    await begin(body);
    setRetrying(false);
  };
  const pickAgain = (f) => navigate(`/videos/${id}/track${f != null ? `?frame=${f}` : ''}`);
  const remove = async (t) => {
    await api.deleteTrack(t.track_id).catch(() => {});
    await refreshTracks();
    if (String(t.track_id) === String(trackId)) navigate(`/videos/${id}/track`);
  };

  const video = page.video;
  const meta = videoMeta(video);
  const title = video ? videoTitle(video) : `Match ${id}`;
  const sourceUrl = videoSourceSrc(video);
  const header = (
    <>
      <Link to={`/videos/${id}`} className={backLink}>
        ← Back to match results
      </Link>
      <p className={`${label} mt-4`}>Track a player</p>
      <h1 className="mt-1 text-3xl font-bold tracking-tight text-fg">{title}</h1>
      {isDemo && (
        <NoticeBanner className="mt-4">
          Demo mode: a synthetic sample clip with a pre-made sample track (it always follows the red #10). Nothing here is from a real match.
        </NoticeBanner>
      )}
    </>
  );

  let body;
  if (page.status === 'loading') body = <LoadingSkeleton />;
  else if (page.status === 'notfound')
    body = (
      <div className={`${card} p-5`}>
        <p className="text-body text-fg-secondary">This video doesn’t exist or has been deleted.</p>
        <Link to="/profile" className={`${btn.secondary} mt-4 h-9`}>
          Go to your uploads
        </Link>
      </div>
    );
  else if (page.status === 'error')
    body = (
      <div role="alert" className="rounded-xl border border-risk-high-ring bg-status-danger-bg p-4 text-body text-status-danger">
        Couldn’t load this video: {page.error?.message}
      </div>
    );
  else if (page.status === 'pending')
    body = (
      <div className={`${card} p-5`}>
        <p className="text-body text-fg-secondary">This match is still being processed. You can track a player once its results are ready.</p>
        <Link to={`/videos/${id}`} className={`${btn.secondary} mt-4 h-9`}>
          See progress
        </Link>
      </div>
    );
  else if (tracks.status === 'unavailable')
    body = (
      <div className={`${card} p-5 sm:p-6`} data-unavailable>
        <h2 className="text-title text-fg">Player tracking isn’t available on this server yet</h2>
        <p className="mt-1 text-body text-fg-muted">
          {tracks.error?.status === 503
            ? `The server has tracking but isn’t set up for it yet (${tracks.error.message}).`
            : 'This backend doesn’t have the tracking endpoints. Once it’s updated, you’ll be able to pick a player here and replay them with a box around them.'}
        </p>
        <Link to={`/videos/${id}`} className={`${btn.secondary} mt-4 h-9`}>
          Back to match results
        </Link>
      </div>
    );
  else if (trackId) {
    if (!track) body = <LoadingSkeleton />;
    else if (track.error)
      body = (
        <div className={`${card} p-5`}>
          <p className="text-body text-fg-secondary">
            {track.error.status === 404 ? 'This track doesn’t exist or was deleted.' : `Couldn’t load this track: ${track.error.message}`}
          </p>
          <button type="button" className={`${btn.secondary} mt-4 h-9`} onClick={() => pickAgain()}>
            Pick a player
          </button>
        </div>
      );
    else if (!done) body = <TrackProgress track={track} onRetry={retry} retrying={retrying} onPickAgain={() => pickAgain(track.target.frame)} />;
    else if (!frames) body = <LoadingSkeleton />;
    else if (frames.status === 'error')
      body = (
        <div role="alert" className="rounded-xl border border-risk-high-ring bg-status-danger-bg p-4 text-body text-status-danger">
          Couldn’t load the track data: {frames.error?.message}
        </div>
      );
    else {
      const player =
        page.roster.find((r) => r.player_id != null && r.player_id === track.target.player_id) ||
        page.roster.find((r) => track.target.jersey_number != null && r.jersey_number === track.target.jersey_number) ||
        null;
      body = (
        <>
          <TrackNotices track={track} />
          <Replay
            key={track.track_id}
            track={track}
            data={frames.data}
            sourceUrl={sourceUrl}
            annotatedUrl={annotatedSrc(track)}
            player={player}
            thumb={thumb}
            videoId={id}
            demo={isDemo}
            onPickAgain={() => pickAgain()}
          />
        </>
      );
    }
  } else {
    const active = tracks.list.find(isActiveTrack);
    body = (
      <>
        {active && (
          <NoticeBanner
            className="mb-4"
            action={
              <Link to={`/videos/${id}/track/${active.track_id}`} className={`${btn.secondary} h-9 shrink-0`}>
                View progress
              </Link>
            }
          >
            A track for {targetLabel(active.target)} is running. Only one track runs at a time per video.
          </NoticeBanner>
        )}
        {!meta.fps && <p className="mb-3 text-caption text-fg-muted">Frame rate not reported for this video; assuming 25 fps for frame stepping.</p>}
        <PickMode
          fps={meta.fps || 25}
          frameCount={meta.frameCount || 250}
          width={meta.width}
          height={meta.height}
          sourceUrl={sourceUrl}
          loadDetections={loadDetections}
          roster={page.roster.filter((r) => r.player_id != null)}
          initialFrame={initialFrame}
          onStart={begin}
          starting={start.busy}
          startError={
            start.error ? (
              <>
                {start.error}
                {start.active && (
                  <>
                    {' '}
                    <Link to={`/videos/${id}/track/${start.active.track_id}`} className={`rounded font-semibold underline underline-offset-4 ${focusRing}`}>
                      View the running track ({targetLabel(start.active.target)})
                    </Link>
                  </>
                )}
              </>
            ) : null
          }
        />
        {!sourceUrl && <p className="mt-3 text-caption text-fg-muted">The original video isn’t available from this server, so you can scrub frame stills but not play the clip.</p>}
      </>
    );
  }

  return (
    <div className={`${container} py-8 sm:py-10`}>
      {header}
      <div className="mt-6">{body}</div>
      {tracks.status === 'ready' && <PastTracks tracks={tracks.list} videoId={id} currentId={trackId} onDelete={remove} />}
    </div>
  );
}
