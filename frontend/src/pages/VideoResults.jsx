import { useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router';
import { useAuth } from '../auth/useAuth';
import { btn, card, container, focusRing } from '../components/classes';
import { ProcessingStatus } from '../components/Progress';
import { ErrorBanner, NoticeBanner, Skeleton, StatusBadge } from '../components/ui';
import MatchScore from '../components/MatchScore';
import VideoTags from '../components/VideoTags';
import Dashboard from '../Dashboard';
import { getVideo, getVideoStats, videoError, videoProgress } from '../lib/api';
import { formatDate, formatDuration, matchOf, videoTitle } from '../lib/format';
import { VIDEO_TYPES } from '../lib/api';
import { addEtaSample } from '../lib/progressSteps';
import { SAMPLE_PLAYERS, SAMPLE_VIDEOS } from '../lib/sampleData';
import { useTagIndex } from '../lib/useTagIndex';

const POLL_MS = 2000;

function LoadingState() {
  return (
    <div className={`${container} py-8`} aria-busy="true">
      <Skeleton className="h-4 w-40" />
      <Skeleton className="mt-3 h-9 w-72" />
      <div className="mt-8 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className={`${card} p-5`}>
            <Skeleton className="h-3 w-24" />
            <Skeleton className="mt-4 h-8 w-20" />
          </div>
        ))}
      </div>
      <div className={`${card} mt-6 space-y-3 p-5`}>
        {[0, 1, 2, 3, 4].map((i) => (
          <Skeleton key={i} className="h-4 w-full" />
        ))}
      </div>
      <p className="mt-3 text-caption text-fg-muted">Loading match results…</p>
    </div>
  );
}


const VIDEO_TYPE_LABEL = Object.fromEntries(VIDEO_TYPES.map((t) => [t.value, t.label]));

function VideoMetaChips({ video }) {
  if (!video) return null;
  const type = video.video_type ? VIDEO_TYPE_LABEL[video.video_type] || video.video_type : null;
  const res = video.resolution || (Array.isArray(video.pipeline_meta?.resolution) ? `${video.pipeline_meta.resolution[0]}x${video.pipeline_meta.resolution[1]}` : null);
  const dur = video.duration_seconds != null ? Number(video.duration_seconds) : null;
  const bits = [
    type ? { k: 'type', label: type } : null,
    res ? { k: 'res', label: res } : null,
    Number.isFinite(dur) && dur > 0 ? { k: 'dur', label: formatDuration(dur) } : null,
  ].filter(Boolean);
  if (!bits.length) return null;
  return (
    <ul className="mt-2 flex flex-wrap gap-2" data-video-meta aria-label="Video details">
      {bits.map((b) => (
        <li key={b.k} className="rounded-full bg-surface-overlay px-2.5 py-0.5 font-mono text-caption text-fg-secondary ring-1 ring-inset ring-line" data-meta={b.k}>
          {b.label}
        </li>
      ))}
    </ul>
  );
}

const backLink = `rounded text-body text-fg-muted hover:text-fg ${focusRing}`;

export default function VideoResults() {
  const { id } = useParams();
  const { isDemo } = useAuth();
  // kind: loading | stats | pending (409: not done / failed) | error
  const [state, setState] = useState({ kind: 'loading', video: null, stats: null, pending: null, error: null, sample: false });
  const [reloadKey, setReloadKey] = useState(0);
  const [tagsOverride, setTagsOverride] = useState(null);
  const [eta, setEta] = useState(null);
  const etaSamples = useRef([]);
  const tagIndex = useTagIndex({ isDemo });

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    let timer;
    (async () => {
      if (isDemo) {
        const video = SAMPLE_VIDEOS.find((v) => String(v.id) === id) || SAMPLE_VIDEOS[1];
        setState({ kind: 'stats', video: { ...video, status: 'done', stage: 'done' }, stats: SAMPLE_PLAYERS, pending: null, error: null, sample: true });
        return;
      }
      const [videoRes, statsRes] = await Promise.allSettled([getVideo(id, { signal }), getVideoStats(id, { signal })]);
      if (signal.aborted) return;
      const video = videoRes.status === 'fulfilled' ? videoRes.value?.video ?? videoRes.value : null;
      if (statsRes.status === 'fulfilled') {
        setState({ kind: 'stats', video, stats: statsRes.value, pending: null, error: null, sample: false });
        return;
      }
      const err = statsRes.reason;
      if (err?.status === 409) {
        // 409 { detail, status, stage, progress } until done (failed videos too).
        // 409 { detail, status, stage, progress, error_message } until done.
        const pending = { ...(err.data && typeof err.data === 'object' ? err.data : {}) };
        const merged = { ...(video || {}), ...pending, error_message: videoError(video) || videoError(pending) || null };
        const prog = videoProgress(merged);
        const r = addEtaSample(etaSamples.current, prog.phase === 'processing' ? prog.percent : null);
        etaSamples.current = r.samples;
        setEta(r.eta);
        setState({ kind: 'pending', video: merged, stats: null, pending: { ...prog, detail: pending.detail }, error: null, sample: false });
        if (prog.phase !== 'failed') timer = setTimeout(() => setReloadKey((k) => k + 1), POLL_MS);
        return;
      }
      if (err?.isNetwork) {
        setState({ kind: 'stats', video, stats: SAMPLE_PLAYERS, pending: null, error: err, sample: true });
      } else {
        setState({ kind: 'error', video, stats: null, pending: null, error: err, sample: false });
      }
    })();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [id, isDemo, reloadKey]);

  if (state.kind === 'loading') return <LoadingState />;

  const { stats, error, sample, pending } = state;
  const video = state.video && tagsOverride ? { ...state.video, tags: tagsOverride } : state.video;
  const tagsEditor = video ? (
    <>
      <MatchScore key={`score-${video.match_id ?? video.id ?? id}`} video={video} demo={isDemo || sample} />
      <VideoTags key={video.id ?? id} video={{ ...video, id: video.id ?? id }} index={tagIndex} demo={isDemo || sample} onSaved={setTagsOverride} />
    </>
  ) : null;
  const title = video ? videoTitle(video) : `Match ${id}`;
  const retry = () => setReloadKey((k) => k + 1);
  const m = matchOf(video);

  if (state.kind === 'pending') {
    const failed = pending.phase === 'failed';
    return (
      <div className={`${container} py-10`}>
        <Link to="/profile" className={backLink}>← Back to uploads</Link>
        <h1 className="mt-4 text-3xl font-bold tracking-tight text-fg">{title}</h1>
        <div className="mt-2">
          <StatusBadge status={failed ? 'failed' : 'processing'} />
        </div>
        {tagsEditor}
        <div className="mt-8">
          <section aria-labelledby="pending-title" className={`${card} p-5 sm:p-6`}>
            <h2 id="pending-title" className="text-title text-fg">
              {failed ? 'This match couldn’t be analyzed' : 'Results aren’t ready yet'}
            </h2>
            <p className="mt-1 text-body text-fg-muted">
              {failed ? (
                <>
                  You can{' '}
                  <Link to="/upload" className={`rounded underline underline-offset-4 hover:text-fg ${focusRing}`}>
                    upload it again
                  </Link>{' '}
                  with a steadier, full-pitch recording.
                </>
              ) : (
                'This match is still being processed. This page updates automatically.'
              )}
            </p>
            <div className="mt-5">
              <ProcessingStatus
                progress={pending}
                eta={eta}
                error={videoError(video) || pending.detail}
                onRetry={failed ? retry : undefined}
                retryLabel="Check again"
                videoRef={id}
              />
            </div>
          </section>
        </div>
      </div>
    );
  }

  if (state.kind === 'error') {
    const gone = error?.status === 404;
    return (
      <div className={`${container} py-10`}>
        <Link to="/profile" className={backLink}>← Back to uploads</Link>
        <h1 className="mt-4 text-3xl font-bold tracking-tight text-fg">{video ? title : gone ? 'Video not found' : 'Match results'}</h1>
        {gone ? (
          <div className={`${card} mt-8 p-5 sm:p-6`}>
            <p className="text-body text-fg-secondary">This video doesn’t exist or has been deleted. It may also belong to another account.</p>
            <div className="mt-4 flex flex-wrap gap-3">
              <Link to="/profile" className={`${btn.secondary} h-9`}>
                Go to your uploads
              </Link>
              <Link to="/upload" className={`${btn.ghost} h-9`}>
                Upload a match
              </Link>
            </div>
          </div>
        ) : (
          <ErrorBanner className="mt-8" title="Couldn’t load results" onRetry={retry}>
            {error?.message}
          </ErrorBanner>
        )}
      </div>
    );
  }

  const subtitle =
    [m.home_team && m.away_team ? `${m.home_team} vs ${m.away_team}` : null, m.match_date ? `Played ${formatDate(m.match_date)}` : null]
      .filter(Boolean)
      .join(' · ') || 'Top speed, distance covered and a workload indicator for this match.';

  return (
    <Dashboard
      key={`${id}-${reloadKey}`}
      players={stats}
      sample={sample}
      videoId={video?.id ?? id}
      headerExtra={
        <>
          <VideoMetaChips video={video} />
          {tagsEditor}
        </>
      }
      title={title}
      eyebrow="Match results"
      subtitle={subtitle}
      actions={
        <>
          {(isDemo || !sample) && (
            <Link to={`/videos/${video?.id ?? id}/track`} className={`${btn.primary} h-9 px-3`}>
              Track a player
            </Link>
          )}
          <Link to="/profile" className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-sm font-medium text-slate-200 transition hover:border-slate-500 hover:text-white">
            All uploads
          </Link>
        </>
      }
      notice={
        sample ? (
          <NoticeBanner
            action={
              !isDemo && (
                <button type="button" onClick={retry} className={`${btn.secondary} h-9 shrink-0`}>
                  Retry
                </button>
              )
            }
          >
            {isDemo ? 'Demo mode: showing sample data.' : 'Backend not reachable, showing sample data.'}
          </NoticeBanner>
        ) : null
      }
    />
  );
}
