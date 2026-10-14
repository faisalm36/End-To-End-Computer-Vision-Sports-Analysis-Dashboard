import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { Link } from 'react-router';
import { useAuth } from '../auth/useAuth';
import { btn, card, container, focusRing, input, label } from '../components/classes';
import { Field } from '../components/FormField';
import { ProcessingStatus, ProgressBar } from '../components/Progress';
import { ScoreFields } from '../components/MatchScore';
import { TagInput } from '../components/Tags';
import { ErrorBanner, Icon, NoticeBanner, Spinner, Toast } from '../components/ui';
import { PROCESSING_STAGES, VIDEO_TYPES, getVideo, isUnsupported, listMatches, updateMatch, uploadVideo, videoError, videoProgress } from '../lib/api';
import { formatBytes, formatDate, formatDuration, stageTitle, toMB, videoId } from '../lib/format';
import { FOOTAGE_REQUIREMENTS } from '../lib/metrics';
import { addEtaSample } from '../lib/progressSteps';
import { scoreFormFrom, scorePatch, validateScore } from '../lib/score';
import { useTagIndex } from '../lib/useTagIndex';
import { useUploadConfig } from '../lib/useUploadConfig';

const POLL_MS = 2000;
const MAX_POLL_FAILURES = 5;
const EMPTY_META = { title: '', match_id: '', match_date: '', home_team: '', away_team: '' };

function checkFile(file, rules) {
  const name = file.name.toLowerCase();
  const ext = name.includes('.') ? name.split('.').pop() : '';
  if (!rules.extensions.includes(ext)) {
    return `“${file.name}” isn’t a supported video. Use ${rules.typesText}.`;
  }
  if (file.type && !file.type.startsWith('video/') && file.type !== 'application/octet-stream') {
    return `“${file.name}” doesn’t look like a video file. Use ${rules.typesText}.`;
  }
  if (rules.maxUploadMb && file.size > rules.maxUploadMb * 1024 * 1024) {
    return `“${file.name}” is ${formatBytes(file.size)}, over the ${rules.maxUploadMb} MB limit.`;
  }
  if (file.size === 0) return `“${file.name}” is empty.`;
  return '';
}

// Segmented choice between an existing match (match_id) and a new one.
function MatchModeToggle({ mode, onChange, disabledExisting }) {
  const opts = [
    { key: 'existing', label: 'Existing match', disabled: disabledExisting },
    { key: 'new', label: 'New match' },
  ];
  return (
    <div role="radiogroup" aria-label="Match" className="inline-flex rounded-control bg-surface-sunken p-1 ring-1 ring-inset ring-line">
      {opts.map((o) => (
        <button
          key={o.key}
          type="button"
          role="radio"
          aria-checked={mode === o.key}
          disabled={o.disabled}
          onClick={() => onChange(o.key)}
          className={`h-8 rounded-md px-3 text-caption font-medium transition-colors ${focusRing} disabled:cursor-not-allowed disabled:text-fg-disabled ${
            mode === o.key ? 'bg-surface-overlay text-fg shadow-card' : 'text-fg-muted hover:text-fg'
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

// Simulated upload for demo sessions (nothing leaves the browser).
function simulate({ onProgress, onUploaded }) {
  let pct = 0;
  const timer = setInterval(() => {
    pct = Math.min(100, pct + 7);
    onProgress(pct);
    if (pct >= 100) {
      clearInterval(timer);
      onUploaded({ id: 'sample-2', status: 'queued', stage: 'queued', progress: 0 });
    }
  }, 180);
  return () => clearInterval(timer);
}

const DEMO_STAGES = ['queued', ...PROCESSING_STAGES.map((s) => s.key), 'done'];

export default function Upload() {
  const { isDemo } = useAuth();
  const rules = useUploadConfig();
  const inputId = useId();
  const fileInput = useRef(null);
  const abortRef = useRef(null);
  const urlRef = useRef(null);

  const [file, setFile] = useState(null);
  const [previewUrl, setPreviewUrl] = useState(null);
  const [duration, setDuration] = useState(null);
  const [rejectReason, setRejectReason] = useState('');
  const [dragOver, setDragOver] = useState(false);
  const [meta, setMeta] = useState(EMPTY_META);
  const [videoType, setVideoType] = useState('tactical_cam');
  const [metaErrors, setMetaErrors] = useState({});
  const [tags, setTags] = useState([]);
  // Optional final score + which side is ours. our_side goes with the upload; the score
  // is PATCHed onto the match once the upload returns its match_id.
  const [score, setScore] = useState(() => scoreFormFrom(null));
  const [scoreError, setScoreError] = useState(null);
  const [scoreNote, setScoreNote] = useState(null);
  const [toast, setToast] = useState(false);
  const [eta, setEta] = useState(null);
  const tagIndex = useTagIndex({ isDemo });

  // Existing matches for "pick an existing match".
  const [matches, setMatches] = useState({ loading: !isDemo, list: [], error: null });
  const [matchMode, setMatchMode] = useState('new');
  const [matchesKey, setMatchesKey] = useState(0);

  const [phase, setPhase] = useState('select'); // select | uploading | processing | done | failed
  const [progress, setProgress] = useState({ loaded: 0, total: 0, percent: 0 });
  const [video, setVideo] = useState(null);
  const [failure, setFailure] = useState(null); // { where, message, status }
  const [pollKey, setPollKey] = useState(0);
  const [announce, setAnnounce] = useState('');

  useEffect(() => {
    if (isDemo) return undefined;
    const controller = new AbortController();
    listMatches({ signal: controller.signal })
      .then((list) => {
        setMatches({ loading: false, list, error: null });
        if (list.length) setMatchMode((m) => (m === 'new' && !matchesKey ? 'existing' : m));
      })
      .catch((err) => {
        if (err?.kind === 'abort') return;
        setMatches({ loading: false, list: [], error: err });
        setMatchMode('new');
      });
    return () => controller.abort();
  }, [isDemo, matchesKey]);

  const setPreview = (f) => {
    if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    urlRef.current = f ? URL.createObjectURL(f) : null;
    setPreviewUrl(urlRef.current);
  };

  useEffect(
    () => () => {
      abortRef.current?.();
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    },
    [],
  );

  useEffect(() => {
    if (phase !== 'uploading') return undefined;
    const onUnload = (e) => {
      e.preventDefault();
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', onUnload);
    return () => window.removeEventListener('beforeunload', onUnload);
  }, [phase]);

  const chooseFile = (f) => {
    if (!f) return;
    const reason = checkFile(f, rules);
    if (reason) {
      setRejectReason(reason);
      setAnnounce(reason);
      return;
    }
    setRejectReason('');
    setFile(f);
    setPreview(f);
    setDuration(null);
    setFailure(null);
    setPhase('select');
    setMeta((m) => ({ ...m, title: m.title || f.name.replace(/\.[^.]+$/, '') }));
    setAnnounce(`Selected ${f.name}, ${formatBytes(f.size)}.`);
  };

  const openPicker = () => fileInput.current?.click();

  // Title is always required; then either match_id, or date + both teams.
  const validateMeta = (name, value, mode = matchMode) => {
    const v = String(value ?? '').trim();
    if (name === 'title') return v ? (v.length > 120 ? 'Keep the title under 120 characters.' : '') : 'Enter a match title.';
    if (mode === 'existing') return name === 'match_id' && !v ? 'Choose a match.' : '';
    if (name === 'match_id') return '';
    const required = { match_date: 'Enter the match date.', home_team: 'Enter the home team.', away_team: 'Enter the away team.' };
    if (!v) return required[name] || '';
    if (name === 'match_date' && Number.isNaN(new Date(v).getTime())) return 'Enter a valid date.';
    if (v.length > 80) return 'Keep team names under 80 characters.';
    return '';
  };
  const metaProps = (name) => ({
    name,
    value: meta[name],
    onChange: (e) => {
      const v = e.target.value;
      setMeta((m) => ({ ...m, [name]: v }));
      if (metaErrors[name]) setMetaErrors((s) => ({ ...s, [name]: validateMeta(name, v) }));
    },
    onBlur: () => setMetaErrors((s) => ({ ...s, [name]: validateMeta(name, meta[name]) })),
    error: metaErrors[name],
  });

  const startUpload = useCallback(() => {
    if (!file) return;
    setFailure(null);
    setVideo(null);
    setProgress({ loaded: 0, total: file.size, percent: 0 });
    setPhase('uploading');
    setAnnounce('Upload started.');

    const selectedMatch = matchMode === 'existing' ? matches.list.find((m) => String(m.match_id) === String(meta.match_id)) ?? null : null;
    const patch = scorePatch(score, selectedMatch ?? { our_side: 'home' });
    const saveScore = (created) => {
      const scorePart = patch && ('home_score' in patch ? { home_score: patch.home_score, away_score: patch.away_score } : null);
      const matchId = created?.match_id ?? created?.match?.match_id ?? selectedMatch?.match_id;
      if (isDemo || !scorePart || matchId == null) return;
      updateMatch(matchId, scorePart)
        .then(() => setScoreNote(null))
        .catch((err) =>
          setScoreNote(
            isUnsupported(err)
              ? 'This server can’t store scores yet, so the score wasn’t saved.'
              : `The video uploaded, but the score wasn’t saved (${err?.message || 'error'}). You can add it on the results page.`,
          ),
        );
    };

    const onUploaded = (created) => {
      abortRef.current = null;
      saveScore(created);
      if (videoId(created) == null) {
        setFailure({ where: 'upload', message: 'The server accepted the upload but did not return a video id.' });
        setPhase('failed');
        return;
      }
      const v = { ...created, id: videoId(created) };
      setVideo(v);
      if (videoProgress(v).phase === 'complete') {
        setPhase('done');
        setAnnounce('Analysis complete.');
      } else {
        setPhase('processing');
        setAnnounce('Upload complete. Queued for processing.');
      }
    };

    if (isDemo) {
      abortRef.current = simulate({
        onProgress: (pct) => setProgress({ loaded: (file.size * pct) / 100, total: file.size, percent: pct }),
        onUploaded,
      });
      return;
    }

    const fields =
      matchMode === 'existing'
        ? { title: meta.title.trim(), match_id: meta.match_id }
        : { title: meta.title.trim(), match_date: meta.match_date, home_team: meta.home_team.trim(), away_team: meta.away_team.trim() };
    const our_side = matchMode === 'new' || (patch && 'our_side' in patch) ? score.our_side : undefined;
    const { promise, abort } = uploadVideo({ file, ...fields, tags, our_side, video_type: videoType || undefined }, { onProgress: setProgress });
    abortRef.current = abort;
    promise.then(onUploaded).catch((err) => {
      abortRef.current = null;
      if (err?.kind === 'abort') {
        setPhase('select');
        setAnnounce('Upload cancelled. Your file is still selected.');
        return;
      }
      setFailure({ where: 'upload', message: err?.message || 'Upload failed.', status: err?.status });
      setPhase('failed');
      setAnnounce(`Upload failed. ${err?.message || ''}`);
    });
  }, [file, meta, matchMode, isDemo, tags, score, matches.list, videoType]);

  const cancelUpload = () => {
    const abort = abortRef.current;
    abortRef.current = null;
    abort?.();
    if (isDemo) {
      setPhase('select');
      setAnnounce('Upload cancelled. Your file is still selected.');
    }
  };

  // Poll GET /api/videos/{id} every ~2s until done or failed.
  const vid = video?.id;
  useEffect(() => {
    if (phase !== 'processing' || vid == null) return undefined;
    let cancelled = false;
    let timer;
    let failures = 0;
    let demoStep = 0;
    let lastKey = '';
    let etaSamples = [];
    const controller = new AbortController();

    const apply = (next) => {
      setVideo((v) => ({ ...v, ...next, id: vid }));
      const prog = videoProgress(next);
      const r = addEtaSample(etaSamples, prog.phase === 'processing' ? prog.percent : null);
      etaSamples = r.samples;
      setEta(r.eta);
      const key = `${prog.phase}:${prog.stageIdx}`;
      if (key !== lastKey) {
        lastKey = key;
        if (prog.phase === 'processing' || prog.phase === 'queued') setAnnounce(`Processing: ${stageTitle(prog)}.`);
      }
      if (prog.phase === 'complete') {
        setPhase('done');
        setAnnounce('Analysis complete.');
        setToast(true);
        return true;
      }
      if (prog.phase === 'failed') {
        setFailure({ where: 'processing', message: videoError(next) || 'Processing failed on the server.' });
        setPhase('failed');
        setAnnounce('Processing failed.');
        return true;
      }
      return false;
    };

    const tick = async () => {
      if (isDemo) {
        demoStep += 1;
        const stage = DEMO_STAGES[Math.min(demoStep, DEMO_STAGES.length - 1)];
        const done = stage === 'done';
        if (apply({ status: done ? 'done' : 'processing', stage, progress: Math.round((demoStep / (DEMO_STAGES.length - 1)) * 100) })) return;
        timer = setTimeout(tick, 1000);
        return;
      }
      try {
        const data = await getVideo(vid, { signal: controller.signal });
        if (cancelled) return;
        failures = 0;
        if (apply(data?.video ?? data)) return;
      } catch (err) {
        if (cancelled || err?.kind === 'abort') return;
        failures += 1;
        if (failures >= MAX_POLL_FAILURES) {
          setFailure({ where: 'poll', message: err?.message || 'Lost contact with the server.' });
          setPhase('failed');
          setAnnounce('Lost contact with the server while checking status.');
          return;
        }
      }
      timer = setTimeout(tick, POLL_MS * (failures + 1));
    };
    timer = setTimeout(tick, isDemo ? 600 : 300);
    return () => {
      cancelled = true;
      controller.abort();
      clearTimeout(timer);
    };
  }, [phase, vid, pollKey, isDemo]);

  const retry = () => {
    if (failure?.where === 'poll') {
      setFailure(null);
      setPhase('processing');
      setPollKey((k) => k + 1);
      return;
    }
    startUpload(); // same file, same details
  };

  const reset = () => {
    setFile(null);
    setPreview(null);
    setVideo(null);
    setFailure(null);
    setPhase('select');
    setMeta(EMPTY_META);
    setMetaErrors({});
    setTags([]);
    setScore(scoreFormFrom(null));
    setScoreError(null);
    setScoreNote(null);
    setProgress({ loaded: 0, total: 0, percent: 0 });
    if (fileInput.current) fileInput.current.value = '';
  };

  const onSubmit = (e) => {
    e.preventDefault();
    const errs = Object.fromEntries(Object.keys(meta).map((k) => [k, validateMeta(k, meta[k])]));
    setMetaErrors(errs);
    const firstBad = Object.keys(errs).find((k) => errs[k]);
    if (firstBad) {
      e.currentTarget.elements.namedItem(firstBad)?.focus();
      return;
    }
    const badScore = validateScore(score);
    setScoreError(badScore);
    if (badScore) {
      document.getElementById(`${inputId}-score-home`)?.focus();
      return;
    }
    startUpload();
  };

  const switchMode = (mode) => {
    setMatchMode(mode);
    setMetaErrors({});
    const m = mode === 'existing' ? matches.list.find((x) => String(x.match_id) === String(meta.match_id)) : null;
    setScore(scoreFormFrom(m));
  };

  const closeToast = useCallback(() => setToast(false), []);
  const busy = phase === 'uploading' || phase === 'processing';
  const limitText = rules.maxUploadMb ? `up to ${rules.maxUploadMb} MB` : 'size limit set by the server';
  const uploadPct = Number.isFinite(progress.percent) ? progress.percent : 0;
  const vprog = videoProgress(video);
  const failureTitle =
    failure?.status === 413
      ? failure.message || 'File is too large'
      : failure?.status === 415
        ? `Unsupported file type (use ${rules.typesText})`
        : failure?.where === 'processing'
          ? 'Processing failed'
          : failure?.where === 'poll'
            ? 'Lost contact while checking status'
            : 'Upload failed';
  const hasMatches = matches.list.length > 0;

  return (
    <div className={`${container} py-10 sm:py-12`}>
      <header className="border-b border-line pb-6">
        <p className={label}>New analysis</p>
        <h1 className="mt-2 text-3xl font-bold tracking-tight text-fg sm:text-4xl">Upload a match</h1>
        <p className="mt-2 text-body text-fg-muted">
          {rules.typesText}, {limitText}. A fixed, wide shot of the whole pitch works best.
        </p>
      </header>

      <div aria-live="polite" role="status" className="sr-only">
        {announce}
      </div>

      {isDemo && (
        <NoticeBanner className="mt-6">
          Demo mode: the backend isn’t connected, so uploads are simulated and nothing leaves your device.
        </NoticeBanner>
      )}

      <div className="mt-8 grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          {!busy && phase !== 'done' && (
            <div>
              <div
                role="button"
                tabIndex={0}
                aria-describedby={rejectReason ? `${inputId}-reject` : `${inputId}-help`}
                aria-label={file ? `Replace video. Selected: ${file.name}` : 'Choose a match video to upload'}
                onClick={openPicker}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    openPicker();
                  }
                }}
                onDragOver={(e) => {
                  e.preventDefault();
                  setDragOver(true);
                }}
                onDragLeave={() => setDragOver(false)}
                onDrop={(e) => {
                  e.preventDefault();
                  setDragOver(false);
                  chooseFile(e.dataTransfer.files?.[0]);
                }}
                className={`flex min-h-64 cursor-pointer flex-col items-center justify-center rounded-card border-2 border-dashed px-6 py-10 text-center transition-colors ${focusRing} ${
                  dragOver ? 'border-accent bg-accent/5' : rejectReason ? 'border-risk-high-ring' : 'border-line-strong hover:border-fg-muted'
                }`}
              >
                <span className="flex size-12 items-center justify-center rounded-xl bg-surface-overlay text-fg ring-1 ring-inset ring-line-strong">
                  <Icon name="upload" className="size-6" />
                </span>
                <p className="mt-4 text-title text-fg">{file ? 'Drop a different video to replace it' : 'Drag a match video here'}</p>
                <span className={`${btn.secondary} pointer-events-none mt-4`}>or browse files</span>
                <p id={`${inputId}-help`} className="mt-4 text-caption text-fg-muted">
                  {rules.extensions.map((e) => `.${e}`).join(' · ')} · {limitText}
                </p>
              </div>
              <input
                id={inputId}
                ref={fileInput}
                type="file"
                accept={rules.accept}
                className="sr-only"
                tabIndex={-1}
                aria-hidden="true"
                onChange={(e) => chooseFile(e.target.files?.[0])}
              />
              {rejectReason && (
                <p id={`${inputId}-reject`} role="alert" className="mt-2 text-sm text-status-danger">
                  {rejectReason}
                </p>
              )}
            </div>
          )}

          {file && (
            <section aria-labelledby="file-card" className={`${card} p-5`}>
              <div className="flex items-start gap-4">
                <div className="relative aspect-video w-32 shrink-0 overflow-hidden rounded-xl bg-surface-sunken ring-1 ring-inset ring-line sm:w-40">
                  {previewUrl ? (
                    <video
                      src={previewUrl}
                      muted
                      playsInline
                      preload="metadata"
                      aria-hidden="true"
                      className="h-full w-full object-cover"
                      onLoadedMetadata={(e) => setDuration(e.currentTarget.duration)}
                    />
                  ) : (
                    <Icon name="film" className="absolute inset-0 m-auto size-6 text-fg-muted" />
                  )}
                </div>
                <div className="min-w-0 flex-1">
                  <h2 id="file-card" className="truncate text-body font-semibold text-fg" title={file.name}>
                    {file.name}
                  </h2>
                  <p className="mt-1 font-mono text-caption tabular-nums text-fg-muted">
                    {formatBytes(file.size)} · {duration ? formatDuration(duration) : 'duration —'}
                  </p>
                  {!busy && phase !== 'done' && (
                    <button type="button" onClick={reset} className={`${btn.ghost} -ml-3 mt-2 h-8 px-3 text-caption`}>
                      Remove
                    </button>
                  )}
                </div>
              </div>

              {(phase === 'select' || phase === 'failed') && (
                <form noValidate className="mt-6 grid gap-4 sm:grid-cols-2" onSubmit={onSubmit}>
                  <Field label="Match title" required placeholder="e.g. U16 cup quarter-final" className="sm:col-span-2" {...metaProps('title')} />
                  <div className="sm:col-span-2">
                    <label htmlFor="video-type" className="mb-1.5 block text-body font-medium text-fg-secondary">
                      Camera / footage type
                    </label>
                    <select
                      id="video-type"
                      value={videoType}
                      onChange={(e) => setVideoType(e.target.value)}
                      className={input}
                      data-video-type
                    >
                      {VIDEO_TYPES.map((t) => (
                        <option key={t.value} value={t.value}>
                          {t.label}
                        </option>
                      ))}
                    </select>
                    <p className="mt-1.5 text-caption text-fg-muted">Tactical cam is the usual full-pitch angle. Broadcast and end-zone cam change how the pipeline expects the shot.</p>
                  </div>

                  <fieldset className="space-y-4 sm:col-span-2">
                    <legend className="mb-2 flex w-full flex-wrap items-center justify-between gap-3">
                      <span className="text-body font-medium text-fg-secondary">Match</span>
                    </legend>
                    <div className="flex flex-wrap items-center gap-3">
                      <MatchModeToggle mode={matchMode} onChange={switchMode} disabledExisting={!hasMatches} />
                      {matches.loading && (
                        <span className="flex items-center gap-2 text-caption text-fg-muted">
                          <Spinner className="size-3.5" /> Loading your matches…
                        </span>
                      )}
                      {!matches.loading && !matches.error && !hasMatches && !isDemo && (
                        <span className="text-caption text-fg-muted">No saved matches yet, so add a new one.</span>
                      )}
                      {matches.error && (
                        <span className="text-caption text-fg-muted">
                          Couldn’t load your matches.{' '}
                          <button
                            type="button"
                            onClick={() => {
                              setMatches((m) => ({ ...m, loading: true, error: null }));
                              setMatchesKey((k) => k + 1);
                            }}
                            className={`rounded font-medium text-fg underline underline-offset-4 ${focusRing}`}
                          >
                            Try again
                          </button>{' '}
                          or add a new match.
                        </span>
                      )}
                    </div>

                    {matchMode === 'existing' ? (
                      <div>
                        <label htmlFor={`${inputId}-match`} className="mb-1.5 block text-body font-medium text-fg-secondary">
                          Choose a match
                        </label>
                        <select
                          id={`${inputId}-match`}
                          name="match_id"
                          value={meta.match_id}
                          required
                          aria-invalid={metaErrors.match_id ? true : undefined}
                          aria-describedby={metaErrors.match_id ? `${inputId}-match-error` : undefined}
                          onChange={(e) => {
                            const v = e.target.value;
                            setMeta((m) => ({ ...m, match_id: v }));
                            // Prefill the score / side already saved on that match.
                            setScore(scoreFormFrom(matches.list.find((x) => String(x.match_id) === String(v))));
                            setScoreError(null);
                            if (metaErrors.match_id) setMetaErrors((s) => ({ ...s, match_id: validateMeta('match_id', v) }));
                          }}
                          onBlur={() => setMetaErrors((s) => ({ ...s, match_id: validateMeta('match_id', meta.match_id) }))}
                          className={input}
                        >
                          <option value="">Select a match…</option>
                          {matches.list.map((m) => (
                            <option key={m.match_id} value={m.match_id}>
                              {formatDate(m.match_date)} · {m.home_team || 'Home'} vs {m.away_team || 'Away'}
                              {Number.isFinite(Number(m.video_count)) ? ` (${m.video_count} video${Number(m.video_count) === 1 ? '' : 's'})` : ''}
                            </option>
                          ))}
                        </select>
                        {metaErrors.match_id && (
                          <p id={`${inputId}-match-error`} className="mt-1.5 text-sm text-status-danger">
                            {metaErrors.match_id}
                          </p>
                        )}
                      </div>
                    ) : (
                      <div className="grid gap-4 sm:grid-cols-2">
                        <Field label="Match date" required type="date" {...metaProps('match_date')} />
                        <div className="hidden sm:block" />
                        <Field label="Home team" required autoComplete="off" {...metaProps('home_team')} />
                        <Field label="Away team" required autoComplete="off" {...metaProps('away_team')} />
                      </div>
                    )}
                  </fieldset>

                  <fieldset className="sm:col-span-2">
                    <legend className="mb-1 text-body font-medium text-fg-secondary">
                      Match tags <span className="font-normal text-fg-muted">(optional)</span>
                    </legend>
                    <p className="mb-3 text-caption text-fg-muted">
                      Conditions like weather or pitch. Tag your matches to compare them later in Insights.
                    </p>
                    <TagInput tags={tags} onChange={setTags} index={tagIndex} idPrefix={`${inputId}-tag`} />
                  </fieldset>

                  <fieldset className="sm:col-span-2">
                    <legend className="mb-1 text-body font-medium text-fg-secondary">
                      Final score <span className="font-normal text-fg-muted">(optional)</span>
                    </legend>
                    <p className="mb-3 text-caption text-fg-muted">Add it now or later on the results page. It powers the W/D/L comparison in Insights.</p>
                    <ScoreFields
                      value={score}
                      onChange={(v) => {
                        setScore(v);
                        if (scoreError) setScoreError(validateScore(v));
                      }}
                      homeTeam={matchMode === 'existing' ? matches.list.find((x) => String(x.match_id) === String(meta.match_id))?.home_team : meta.home_team.trim()}
                      awayTeam={matchMode === 'existing' ? matches.list.find((x) => String(x.match_id) === String(meta.match_id))?.away_team : meta.away_team.trim()}
                      idPrefix={`${inputId}-score`}
                      error={scoreError}
                    />
                  </fieldset>

                  <div className="flex flex-wrap gap-3 sm:col-span-2">
                    <button type="submit" className={`${btn.primary} h-11 px-6`}>
                      {phase === 'failed' && failure?.where !== 'poll' ? 'Retry upload' : 'Start analysis'}
                    </button>
                  </div>
                </form>
              )}
            </section>
          )}

          {phase === 'failed' && failure && failure.where === 'processing' && (
            <section aria-labelledby="progress-failed-title" className={`${card} p-5 sm:p-6`}>
              <h2 id="progress-failed-title" className="text-title text-fg">
                Analysis progress
              </h2>
              <div className="mt-5">
                <ProcessingStatus progress={vprog} error={failure.message} onRetry={retry} retryLabel="Upload again" videoRef={video?.id} />
              </div>
            </section>
          )}

          {phase === 'failed' && failure && failure.where !== 'processing' && (
            <ErrorBanner title={failureTitle} onRetry={retry} retryLabel={failure.where === 'poll' ? 'Keep checking' : 'Retry'}>
              <p>
                {failure.status === 413
                  ? `The server rejected this ${formatBytes(file?.size)} file because it exceeds the upload size limit${rules.maxUploadMb ? ` (${rules.maxUploadMb} MB)` : ''}. Try a shorter or more compressed video.`
                  : failure.status === 415
                    ? `The server only accepts ${rules.typesText} video files.`
                    : failure.message}
              </p>
              <p className="mt-1 text-caption text-fg-muted">
                {failure.where === 'poll'
                  ? 'Your video was uploaded. Processing may still be running on the server.'
                  : failure.status === 413 || failure.status === 415
                    ? 'Your match details are kept. Choose a different file above, or retry with this one.'
                    : 'Your file and match details are still selected, so you can retry without choosing them again.'}
              </p>
            </ErrorBanner>
          )}

          {(busy || phase === 'done') && (
            <section aria-labelledby="progress-title" className={`${card} p-5 sm:p-6`}>
              <h2 id="progress-title" className="sr-only">
                Analysis progress
              </h2>
              {phase === 'uploading' && (
                <div>
                  <div className="flex items-baseline justify-between gap-4">
                    <p className="text-body font-medium text-fg">Uploading…</p>
                    <p className="font-mono text-body tabular-nums text-fg">{Math.round(uploadPct)}%</p>
                  </div>
                  <div className="mt-3">
                    <ProgressBar value={uploadPct} labelText="Upload progress" />
                  </div>
                  <div className="mt-3 flex items-center justify-between gap-4">
                    <p className="font-mono text-caption tabular-nums text-fg-muted">
                      {toMB(progress.loaded)} / {toMB(progress.total || file?.size)} MB
                    </p>
                    <button type="button" onClick={cancelUpload} className={`${btn.secondary} h-9`}>
                      Cancel
                    </button>
                  </div>
                </div>
              )}

              {phase === 'processing' && (
                <div>
                  <ProcessingStatus progress={vprog} eta={eta} />
                  <p className="mt-2 text-caption text-fg-muted">
                    Find it later in{' '}
                    <Link to="/profile" className={`rounded underline underline-offset-4 hover:text-fg ${focusRing}`}>
                      your uploads
                    </Link>
                    .
                  </p>
                </div>
              )}

              {phase === 'done' && (
                <div>
                  <p className="flex items-center gap-2 text-title text-fg">
                    <Icon name="check" className="size-5 text-status-success" />
                    Analysis complete
                  </p>
                  <p className="mt-1 text-body text-fg-muted">Player speed, distance and workload indicator results are ready.</p>
                  {scoreNote && (
                    <p role="status" className="mt-3 rounded-lg border border-line-strong bg-surface-sunken px-3 py-2 text-caption text-fg-secondary">
                      {scoreNote}
                    </p>
                  )}
                  <div className="mt-5 flex flex-col gap-3 sm:flex-row">
                    <Link to={`/videos/${encodeURIComponent(video?.id)}`} className={`${btn.primary} h-11 px-6`}>
                      View results
                    </Link>
                    <button type="button" onClick={reset} className={`${btn.secondary} h-11`}>
                      Upload another
                    </button>
                  </div>
                </div>
              )}
            </section>
          )}
        </div>

        <aside className={`${card} h-fit p-5`}>
          <h2 className={label}>Footage we need</h2>
          <ul className="mt-4 space-y-3 text-body text-fg-secondary">
            {FOOTAGE_REQUIREMENTS.map((r) => (
              <li key={r}>{r}.</li>
            ))}
            <li>Clear, contrasting kits make shirt numbers easier to read. You can correct any misread number afterwards.</li>
          </ul>
          <p className="mt-4 text-caption text-fg-muted">
            Physical stats are estimated from video, so a panning or zoomed camera makes them unreliable.
          </p>
        </aside>
      </div>
      {toast && phase === 'done' && (
        <Toast
          onClose={closeToast}
          action={
            <Link to={`/videos/${encodeURIComponent(video?.id)}`} className={`${btn.primary} h-9 shrink-0 px-3`}>
              View results
            </Link>
          }
        >
          Analysis complete.
        </Toast>
      )}
    </div>
  );
}
